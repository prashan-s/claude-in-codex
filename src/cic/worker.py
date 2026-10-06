"""Job worker: drives one delegated job to a verified finish.

Runs detached (``cic _worker <id>``) or inline for multi-agent modes. The loop:

  1. (optional) planning phase: Opus, read-only, plan schema
  2. start Claude in stream-json mode and send the brief
  3. pump events: progress, steering, model switches, cancel, time limits
  4. on each result: classify strictly, then decide
       done + caller checks pass  -> finish (verified)
       done + checks fail         -> send failures back, same session (reflexion)
       partial / failed           -> ask it to continue; escalate model when warranted
       needs_input / blocked      -> stop and surface to the orchestrator
"""

from __future__ import annotations

import os
import time
import traceback
import uuid

from . import config, jobs, prompts, router, schemas, sessions
from .claude import (EOF, ClaudeProcess, ClaudeSpec, Progress, TurnOutcome, add_tokens, build_argv, classify,
                     printable_argv, user_content)
from .render import render_final
from .util import append_line, atomic_write_json, atomic_write_text, child_env, now_iso, oneline, read_text
from .verify import run_checks

_MODE_FOR_ACCESS = {"read": "dontAsk", "edit": "acceptEdits", "auto": "auto", "full": "bypassPermissions"}
_ERROR_STATUS = {"max_turns": "partial", "budget": "partial", "auth": "blocked", "interrupted": "cancelled"}


class JobRunner:
    def __init__(self, job_id: str):
        self.id = job_id
        self.job = jobs.load(job_id)
        self.dir = jobs.job_dir(job_id)
        self.params = self.job["params"]
        self.progress = Progress()
        self.proc: ClaudeProcess | None = None
        self.cancel_requested = False
        self.timeout_reason: str | None = None
        self.started = time.time()
        self.current_model = self.params.get("model")
        # Usage from finished *other* sessions (the planning phase). A resumed process already
        # reports the whole conversation's totals, so restarts never add to these.
        self.cost_base = 0.0
        self.tokens_base: dict = {}
        self._last_save = 0.0
        self._interrupt_at: float | None = None
        self._warned_mode = False

    # ------------------------------------------------------------- bookkeeping

    def log(self, line: str) -> None:
        append_line(self.dir / "log.txt", f"[{time.strftime('%H:%M:%S')}] {line}")

    def save(self, force: bool = False) -> None:
        now = time.time()
        if not force and now - self._last_save < 0.75:
            return
        self._last_save = now
        self.job["progress"] = self.progress.to_dict()
        self.job["cost_usd"] = round(self.cost_base + self.progress.cost_usd, 6)
        jobs.save(self.job)

    # ------------------------------------------------------------- entry

    def run(self) -> dict:
        self.job.update(status="running", phase="starting", started_at=now_iso(), worker_pid=os.getpid())
        self.save(force=True)
        try:
            if self.params.get("plan") and not self.run_plan_phase():
                return self.job
            self.run_main()
        except Exception as exc:  # keep the job record truthful even on bugs
            atomic_write_text(self.dir / "worker-error.txt", traceback.format_exc())
            self.log(f"worker error: {exc!r}")
            self.finalize("failed", None, reason=f"worker error: {exc!r} (see worker-error.txt)")
        finally:
            if self.proc:
                self.proc.finish(grace=5)
                self.proc = None
        return self.job

    # ------------------------------------------------------------- process control

    def spec(self, **overrides) -> ClaudeSpec:
        p = self.params
        schema_name = p.get("schema")
        system_file = self.dir / "system.md"
        values = dict(
            model=self.current_model,
            cwd=p["cwd"],
            access=p["access"],
            effort=p.get("effort"),
            fallback=p.get("fallback") or [],
            session_id=None if p.get("resume") else self.job["session_id"],
            resume=p.get("resume"),
            fork=bool(p.get("fork")),
            schema=schemas.BY_NAME.get(schema_name) if schema_name else None,
            system_file=str(system_file) if system_file.exists() else None,
            allow=p.get("allow") or [],
            deny=p.get("deny") or [],
            verify=p.get("verify") or [],
            allow_git_write=bool(p.get("allow_git_write")),
            max_turns=p.get("max_turns"),
            budget_usd=p.get("budget"),
            worktree=p.get("worktree"),
            add_dirs=p.get("add_dirs") or [],
            lean=bool(p.get("lean")),
            profile=p.get("profile") or ("lean" if config.get("lean") else config.get("profile")),
            name=p.get("name") or self.id,
        )
        values.update(overrides)
        return ClaudeSpec(**values)

    def start(self, spec: ClaudeSpec) -> ClaudeProcess:
        argv = build_argv(spec)
        append_line(self.dir / "argv.txt", printable_argv(argv))
        self.progress.last_event_at = time.time()
        self.proc = ClaudeProcess(argv, cwd=spec.cwd, env=child_env({"CIC_JOB_ID": self.id}),
                                  raw_log=self.dir / "events.jsonl")
        self.job["claude_pid"] = self.proc.pid
        self.job["expected_permission_mode"] = _MODE_FOR_ACCESS.get(spec.access)
        self._warned_mode = False
        self.save(force=True)
        return self.proc

    def ensure_alive(self) -> None:
        """Restart Claude on the same session if the process exited between turns."""
        if self.proc and self.proc.alive():
            return
        if self.proc:
            self.proc.finish(grace=1)
        sid = self.progress.session_id or self.job.get("session_id")
        self.log("Claude process ended; resuming the same session")
        self.start(self.spec(resume=sid, session_id=None, fork=False))

    def interrupt(self, why: str) -> None:
        if self.proc and self.proc.alive():
            self.proc.control("interrupt")
            self._interrupt_at = time.time()
            self.log(f"interrupt sent: {why}")

    def handle_controls(self) -> None:
        for message in jobs.take_controls(self.id):
            kind = message.get("type")
            if kind == "steer" and message.get("text") and self.proc:
                text = message["text"].strip()
                self.proc.send_user(f'<steering from="orchestrator">\n{text}\n</steering>')
                self.job.setdefault("steering", []).append({"at": now_iso(), "text": text})
                self.log(f"steer: {oneline(text, 140)}")
            elif kind == "model" and message.get("model") and self.proc:
                target = message["model"]
                self.proc.control("set_model", model=target)
                self.job.setdefault("escalations", []).append({"attempt": self.job.get("attempt"), "from": self.current_model, "to": target, "manual": True})
                self.log(f"model switched {self.current_model} -> {target} (requested)")
                self.current_model = target
            elif kind == "cancel" and not self.cancel_requested:
                self.cancel_requested = True
                self.interrupt("cancel requested")

    def check_limits(self) -> None:
        now = time.time()
        if self._interrupt_at and now - self._interrupt_at > 20 and self.proc and self.proc.alive():
            self.log("Claude did not stop after interrupt; terminating the process")
            self._interrupt_at = None
            self.proc.finish(grace=0)
            return
        if self.timeout_reason:
            return
        limit = float(self.params.get("timeout") or config.get("job_timeout"))
        stall = float(config.get("stall_timeout"))
        if now - self.started > limit:
            self.timeout_reason = f"job exceeded its {int(limit)}s time limit"
        elif now - self.progress.last_event_at > stall:
            self.timeout_reason = f"no activity from Claude for {int(stall)}s"
        if self.timeout_reason:
            self.log(self.timeout_reason)
            self.interrupt(self.timeout_reason)

    def on_init(self) -> None:
        sid = self.progress.session_id
        if sid and sid != self.job.get("session_id"):
            self.job["session_id"] = sid
        self.job["session_started"] = True
        expected = self.job.get("expected_permission_mode")
        actual = self.progress.permission_mode
        if expected and actual and actual != expected and not self._warned_mode:
            self._warned_mode = True
            warning = f"Claude Code started in permission mode {actual!r} instead of {expected!r}; unlisted tool calls may be denied"
            self.job.setdefault("warnings", []).append(warning)
            self.log(f"warning: {warning}")
        self.save(force=True)

    def pump(self) -> dict | None:
        """Process events until the current turn (including queued steering) has fully finished."""
        assert self.proc is not None
        last_result = None
        while True:
            self.handle_controls()
            self.check_limits()
            event = self.proc.next_event(0.25)
            if event is EOF:
                return last_result
            if event is None:
                if last_result is not None and time.time() - self.progress.last_event_at > 8:
                    return last_result  # no further acknowledgements are coming
                self.save()
                continue
            line = self.progress.apply(event)
            if line:
                self.log(line)
            etype = event.get("type")
            if etype == "system" and event.get("subtype") == "init":
                self.on_init()
            elif etype == "user" and event.get("isReplay") and not event.get("parent_tool_use_id"):
                self.proc.pending_replays = max(0, self.proc.pending_replays - 1)
            elif etype == "result":
                last_result = event
                if (not event.get("queued_turn_count") and self.proc.pending_replays <= 0
                        and not jobs.controls_pending(self.id)):
                    self.save(force=True)
                    return event
            self.save()

    # ------------------------------------------------------------- phases

    def run_plan_phase(self) -> bool:
        p = self.params
        self.job.update(phase="planning")
        plan_spec = self.spec(
            model=p.get("plan_model") or "opus",
            effort=p.get("plan_effort") or "high",
            fallback=["sonnet"],
            access="read",
            session_id=str(uuid.uuid4()),
            resume=None,
            schema=schemas.PLAN_REPORT,
            system_file=str(self.dir / "system-plan.md"),
            worktree=None,
            name=f"{self.id}-plan",
        )
        self.start(plan_spec)
        self.proc.send_user(read_text(self.dir / "plan-brief.md"))
        result = self.pump()
        outcome = classify(result, expect_report=True, interrupted=self.cancel_requested or bool(self.timeout_reason),
                           stderr_tail=self.proc.stderr_tail())
        self.proc.finish(grace=15)
        self.proc = None
        self.cost_base += self.progress.cost_usd
        self.tokens_base = add_tokens(self.tokens_base, self.progress.tokens)
        self.job["plan_session_id"] = self.progress.session_id
        self.job["plan_progress"] = self.progress.to_dict()
        if self.cancel_requested or outcome.error or not outcome.report:
            self.job["schema"] = "plan"
            status = "cancelled" if self.cancel_requested else "failed"
            self.finalize(status, outcome, reason="planning phase: " + (self.timeout_reason or outcome.message))
            return False
        plan = outcome.report
        atomic_write_json(self.dir / "plan.json", plan)
        self.job["plan"] = plan
        brief = prompts.build_brief(
            p["task"], kind=self.job["kind"], cwd=p["cwd"], files=p.get("files"), context=p.get("context"),
            context_files=p.get("context_files"), criteria=p.get("criteria"), verify=p.get("verify"),
            constraints=p.get("constraints"), read_only=bool(p.get("read_only")), plan=plan,
            hints=p.get("hints"), examples=p.get("examples"), image_count=len(p.get("images") or []),
        )
        atomic_write_text(self.dir / "brief.md", brief)
        self.log(f"plan ready ({len(plan.get('steps') or [])} steps): {oneline(plan.get('approach'), 160)}")
        # Execution starts a fresh session that gets the distilled plan, not the planning transcript.
        self.progress = Progress()
        return True

    def run_main(self) -> None:
        p = self.params
        spec = self.spec()
        expect_report = spec.schema is not None
        max_attempts = max(1, int(p.get("max_attempts") or 1))
        attempt = 1
        self.job.update(phase="working", attempt=attempt, schema=p.get("schema"))
        self.start(spec)
        self.proc.send_user(user_content(read_text(self.dir / "brief.md"), p.get("images")))
        self.save(force=True)

        while True:
            result = self.pump()
            outcome = classify(result, expect_report=expect_report,
                               interrupted=self.cancel_requested or bool(self.timeout_reason),
                               stderr_tail=self.proc.stderr_tail() if self.proc else "")
            self.record_attempt(attempt, outcome)

            if self.cancel_requested:
                return self.finalize("cancelled", outcome, reason="cancelled on request")
            if self.timeout_reason:
                return self.finalize("failed", outcome, reason=self.timeout_reason)
            if outcome.error:
                return self.finalize(_ERROR_STATUS.get(outcome.error, "failed"), outcome, reason=outcome.message)
            if not expect_report:
                return self.finalize("done", outcome)

            report = outcome.report
            if report is None:
                if attempt < max(2, max_attempts):
                    attempt += 1
                    self.send_followup(prompts.REPORT_MISSING_MESSAGE, attempt)
                    continue
                return self.finalize("partial", outcome, reason="Claude finished without a structured report")
            if p.get("schema") in ("review", "plan", "improve"):
                return self.finalize("done", outcome)

            status = report.get("status") or "partial"
            if status in ("needs_input", "blocked"):
                return self.finalize(status, outcome)
            if status != "done" and outcome.denials:
                tools = ", ".join(sorted({d.get("tool") or "?" for d in outcome.denials}))
                return self.finalize("blocked", outcome, reason=f"permission denials ({tools}) stopped progress")
            if status == "done":
                checks = p.get("verify") or []
                verified = False
                if checks:
                    results = self.run_verify(checks)
                    verified = all(r["ok"] for r in results)
                if not checks or verified:
                    if self.wants_uncertainty_pass(report, attempt, max_attempts):
                        attempt += 1
                        self.job["uncertainty_checked"] = True
                        self.log(f"active-prompt: confidence {report.get('confidence')} is low; asking for an uncertainty pass")
                        self.send_followup(prompts.uncertainty_message(report, self.confidence_bar()), attempt)
                        continue
                    return self.finalize("done", outcome, verified=verified)
                failing = [r for r in results if not r["ok"]]
                if all(r.get("env_error") for r in failing):
                    # The check itself cannot run here; editing code will not help.
                    return self.finalize("blocked", outcome, verified=False, reason=(
                        f"verification command cannot run in this environment ({failing[0]['env_error']}). "
                        f"Fix the check (for example the project's own runner or virtualenv), then "
                        f"`cic reply {self.id} \"re-check\" --verify \"<working command>\"`"))
                if attempt < max_attempts:
                    attempt += 1
                    self.maybe_escalate(attempt, hard_failure=False)
                    self.send_followup(prompts.verification_failed_message(results, attempt - 1, max_attempts), attempt)
                    continue
                return self.finalize("failed", outcome, verified=False,
                                     reason=f"checks still failing after {max_attempts} attempt(s)")
            if attempt < max_attempts and self.job["kind"] in router.WRITE_KINDS:
                attempt += 1
                self.maybe_escalate(attempt, hard_failure=(status == "failed"))
                self.send_followup(prompts.continue_message(report), attempt)
                continue
            return self.finalize(status, outcome)

    # ------------------------------------------------------------- helpers

    def send_followup(self, text: str, attempt: int) -> None:
        self.ensure_alive()
        self.job.update(attempt=attempt, phase="repairing")
        atomic_write_text(self.dir / f"followup-{attempt}.md", text)
        self.progress.last_event_at = time.time()
        if not self.proc.send_user(text):
            raise RuntimeError("Claude process stopped accepting input")
        self.log(f"attempt {attempt}: follow-up sent")
        self.save(force=True)

    def account_usage(self) -> None:
        """Per-job usage: this job's share of the session totals (resumed sessions start from a baseline)."""
        session_tokens = add_tokens(self.tokens_base, self.progress.tokens)
        session_cost = self.cost_base + self.progress.cost_usd
        baseline = self.params.get("baseline") or {}
        base_tokens = baseline.get("tokens") or {}
        self.job["session_tokens"] = session_tokens
        self.job["session_cost_usd"] = round(session_cost, 6)
        self.job["tokens"] = {k: max(0, v - int(base_tokens.get(k, 0))) for k, v in session_tokens.items()}
        self.job["cost_usd"] = round(max(0.0, session_cost - float(baseline.get("cost") or 0.0)), 6)

    def confidence_bar(self) -> float:
        return float(self.params.get("low_confidence") or config.get("low_confidence"))

    def wants_uncertainty_pass(self, report: dict, attempt: int, max_attempts: int) -> bool:
        """Active-prompt: one extra, targeted turn when Claude itself reports low confidence."""
        confidence = report.get("confidence")
        return (
            self.job["kind"] in router.WRITE_KINDS
            and not self.job.get("uncertainty_checked")
            and isinstance(confidence, (int, float))
            and confidence < self.confidence_bar()
            and attempt < max_attempts
        )

    def maybe_escalate(self, next_attempt: int, *, hard_failure: bool) -> None:
        """Move one tier up the ladder after repeated failure. Model switches rebuild the
        prompt cache, so the first repair stays on the same model unless the run failed outright."""
        if not self.params.get("escalate"):
            return
        if not hard_failure and next_attempt < 3:
            return
        target = router.next_tier(self.current_model or "sonnet", allow_fable=bool(self.params.get("allow_fable")))
        if not target:
            return
        self.ensure_alive()
        self.proc.control("set_model", model=target)
        self.job.setdefault("escalations", []).append({"attempt": next_attempt, "from": self.current_model, "to": target})
        self.log(f"escalating model {self.current_model} -> {target}")
        self.current_model = target

    def run_verify(self, commands: list[str]) -> list[dict]:
        self.job["phase"] = "verifying"
        self.save(force=True)
        cwd = self.progress.session_cwd or self.params["cwd"]
        self.log("verifying: " + " ; ".join(commands))
        results = run_checks(commands, cwd, float(config.get("verify_timeout")))
        self.job["verification"] = results
        for item in results:
            self.log(f"check {'PASS' if item['ok'] else 'FAIL'} (exit {item['exit_code']}): {item['command']}")
        self.save(force=True)
        return results

    def record_attempt(self, attempt: int, outcome: TurnOutcome) -> None:
        self.job.setdefault("attempts", []).append({
            "attempt": attempt,
            "model": self.progress.model or self.current_model,
            "error": outcome.error,
            "status": (outcome.report or {}).get("status") if outcome.report else None,
            "denials": len(outcome.denials),
            "session_cost_usd": outcome.cost_usd,
            "at": now_iso(),
        })

    def finalize(self, status: str, outcome: TurnOutcome | None, *, reason: str | None = None,
                 verified: bool | None = None) -> None:
        if outcome is not None:
            self.job["report"] = outcome.report
            self.job["result_text"] = None if outcome.report else (outcome.text or "")[:40000]
            self.job["error"] = outcome.error
        self.job.update(status=status, phase="finished", finished_at=now_iso())
        if reason:
            self.job["reason"] = reason
        if verified is not None:
            self.job["verified"] = verified
        self.job["model_final"] = self.progress.model or self.current_model
        self.job["progress"] = self.progress.to_dict()
        self.account_usage()
        self.job["elapsed"] = jobs.refresh(dict(self.job)).get("elapsed")
        if self.job.get("report"):
            atomic_write_json(self.dir / "report.json", self.job["report"])
        atomic_write_text(self.dir / "final.md", render_final(self.job))
        jobs.save(self.job)
        if self.job.get("session_name"):
            sessions.record_turn(self.job["session_name"], job_id=self.id,
                                 started=bool(self.job.get("session_started")),
                                 cost_usd=self.progress.cost_usd, model=self.progress.model,
                                 tokens=self.job.get("session_tokens"))
        self.log(f"finished: {status}" + (f" ({reason})" if reason else ""))
        if self.proc:
            self.proc.finish(grace=20)
            self.proc = None


def main(job_id: str) -> int:
    job = jobs.load(job_id)
    if job.get("kind") in ("pair", "council"):
        from . import orchestrate

        return orchestrate.run_job(job_id)
    JobRunner(job_id).run()
    return 0
