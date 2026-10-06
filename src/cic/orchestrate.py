"""Multi-agent modes built on the job machinery and the bus.

council: same question to several agents in parallel (Claude / Codex / Gemini),
         then a moderator synthesizes: cross-vendor self-consistency.
pair:    driver implements, navigator reviews the real diff, loop until the
         navigator approves or rounds run out (Claude<->Claude or Claude<->Codex).

Every exchange is recorded on a bus thread (``cic bus log <thread>``).
"""

from __future__ import annotations

import os
import time
from concurrent.futures import ThreadPoolExecutor, as_completed

from . import agents, bus, gitctx, jobs, prompts, router
from .agents import AgentResult
from .util import append_line, atomic_write_text, fmt_cost, now_iso, oneline


class Orchestration:
    def __init__(self, job_id: str):
        self.id = job_id
        self.job = jobs.load(job_id)
        self.dir = jobs.job_dir(job_id)
        self.params = self.job["params"]
        self.thread = self.params.get("thread") or f"{self.job['kind']}-{job_id}"
        self.job["thread"] = self.thread

    def log(self, line: str) -> None:
        append_line(self.dir / "log.txt", f"[{time.strftime('%H:%M:%S')}] {line}")

    def save(self, **fields) -> None:
        self.job.update(fields)
        jobs.save(self.job)

    def note(self, sender: str, to: str | list[str], body: str, kind: str = "message", meta: dict | None = None) -> None:
        bus.record(sender, to, body, thread=self.thread, kind=kind, meta=meta)

    def cancelled(self) -> bool:
        return any(m.get("type") == "cancel" for m in jobs.take_controls(self.id))

    def finish(self, status: str, body: str, *, reason: str | None = None, cost: float = 0.0) -> None:
        self.job.update(status=status, phase="finished", finished_at=now_iso(), reason=reason,
                        cost_usd=round(cost, 6), result_text=body)
        self.job["elapsed"] = jobs.refresh(dict(self.job)).get("elapsed")
        header = f"## {status.upper().replace('_', ' ')} · {self.job['kind']} · {self.id}\n"
        if reason:
            header += f"Reason: {reason}\n"
        footer = f"\nTranscript: `cic bus log {self.thread}` · step log: `cic logs {self.id}`"
        if cost:
            footer += f" · est. Claude cost {fmt_cost(cost)}"
        atomic_write_text(self.dir / "final.md", header + "\n" + body.rstrip() + "\n" + footer + "\n")
        jobs.save(self.job)
        self.log(f"finished: {status}" + (f" ({reason})" if reason else ""))


def _cost(result: AgentResult) -> float:
    try:
        return float(result.meta.get("cost_usd") or 0.0)
    except (TypeError, ValueError):
        return 0.0


def _member_labels(members: list[str]) -> list[str]:
    counts: dict[str, int] = {}
    labels = []
    for spec in members:
        counts[spec] = counts.get(spec, 0) + 1
        labels.append(spec if members.count(spec) == 1 else f"{spec}#{counts[spec]}")
    return labels


def _pin_model(spec: str, text: str, kind: str) -> str:
    """Give a bare `claude` spec a concrete tier once, so every round stays on one model (cache-friendly)."""
    vendor, model = agents.parse_spec(spec)
    if vendor != "claude" or model:
        return spec
    return f"claude:{router.route(text, kind=kind).model}"


# ----------------------------------------------------------------- council

def run_council(o: Orchestration) -> None:
    p = o.params
    question, cwd = p["question"], p["cwd"]
    members: list[str] = p["members"]
    synth: str = p.get("synth") or "none"
    o.save(status="running", phase="asking the panel", started_at=now_iso(), worker_pid=os.getpid())
    o.note("cic", members, question, kind="task")
    prompt = prompts.council_member_prompt(question, cwd=cwd, context=p.get("context"), files=p.get("files"))
    # Members are keyed by position, so the same spec may appear several times:
    # e.g. claude:sonnet x3 is classic self-consistency (independent samples, then a vote).
    labels = _member_labels(members)
    results: dict[int, AgentResult] = {}
    with ThreadPoolExecutor(max_workers=max(1, min(len(members), int(p.get("parallel") or 3)))) as pool:
        futures = {
            pool.submit(agents.run, spec, prompt, cwd=cwd, kind="research", access="read", parent=o.id,
                        title=f"council: {question}"): index
            for index, spec in enumerate(members)
        }
        for future in as_completed(futures):
            index = futures[future]
            label = labels[index]
            try:
                result = future.result()
            except Exception as exc:  # one broken member must not sink the panel
                result = AgentResult(members[index], False, "", error=repr(exc))
            result.spec = label
            results[index] = result
            o.log(f"{label}: {'answered' if result.ok else 'unavailable'}" + ("" if result.ok else f" ({result.error})"))
            o.note(label.replace("#", "-"), "cic", result.text if result.ok else f"[unavailable] {result.error}",
                   kind="reply", meta={"ok": result.ok})
    ordered = [results[i] for i in range(len(members))]
    answered = [r for r in ordered if r.ok]
    missing = [r for r in ordered if not r.ok]
    cost = sum(_cost(r) for r in ordered)
    synthesis: AgentResult | None = None
    if synth != "none" and answered and not o.cancelled():
        o.save(phase="synthesizing")
        synth_prompt = prompts.council_synth_prompt(
            question, [(r.spec, r.text) for r in answered], [(r.spec, r.error or "failed") for r in missing])
        synthesis = agents.run(synth, synth_prompt, cwd=cwd, kind="research", access="read", parent=o.id,
                               title=f"council synthesis: {question}")
        cost += _cost(synthesis)
        o.note(synth, "cic", synthesis.text if synthesis.ok else f"[failed] {synthesis.error}", kind="reply")

    lines = [f"Question: {question.strip()}", ""]
    if synthesis is not None:
        lines += [f"### Synthesis ({synth})", (synthesis.text if synthesis.ok else f"Synthesis failed: {synthesis.error}"), ""]
    lines.append("### Panel")
    for result in ordered:
        state = "answered" if result.ok else f"unavailable: {result.error}"
        model = f" · {result.meta.get('model')}" if result.meta.get("model") else ""
        lines.append(f"- **{result.spec}**{model}: {state}")
    for result in answered:
        text = result.text if len(result.text) <= 2500 else result.text[:2500] + "\n…[trimmed; full text in the transcript]"
        lines += ["", f"#### {result.spec}", text]
    if synthesis is not None and synthesis.ok:
        status = "done"
    elif synth == "none" and answered:
        status = "done"
    else:
        status = "partial" if answered else "failed"
    reason = None if answered else "no panel member produced an answer"
    if answered and missing:
        reason = f"{len(missing)} of {len(ordered)} members unavailable"
    o.finish(status, "\n".join(lines), reason=reason, cost=cost)


# ----------------------------------------------------------------- pair

def _driver_report_text(result: AgentResult) -> str:
    report = result.data or {}
    if not report:
        return result.text
    lines = [f"Status: {report.get('status')}. {report.get('summary', '')}"]
    for change in report.get("changes") or []:
        lines.append(f"- changed {change.get('path')}: {change.get('change')}")
    for claim in report.get("verification") or []:
        lines.append(f"- ran `{claim.get('command')}`: {claim.get('outcome')} ({oneline(claim.get('details'), 120)})")
    return "\n".join(lines)


def run_pair(o: Orchestration) -> None:
    p = o.params
    task, cwd = p["task"], p["cwd"]
    kind = p.get("kind") or "implement"
    rounds = max(1, int(p.get("rounds") or 3))
    verify = p.get("verify") or []
    driver = _pin_model(p["driver"], task, kind)
    navigator = _pin_model(p["navigator"], task, "review")
    o.save(status="running", phase="round 1: driver", started_at=now_iso(), worker_pid=os.getpid(),
           driver=driver, navigator=navigator)
    o.note("cic", [driver, navigator], task, kind="task")

    brief = prompts.build_brief(task, kind=kind, cwd=cwd, files=p.get("files"), context=p.get("context"),
                                criteria=p.get("criteria"), verify=verify, constraints=p.get("constraints"))
    driver_resume: str | None = None
    navigator_resume: str | None = None
    message = brief
    history: list[dict] = []
    status, reason, cost = "partial", None, 0.0

    for round_no in range(1, rounds + 1):
        if o.cancelled():
            status, reason = "cancelled", "cancelled on request"
            break
        o.save(phase=f"round {round_no}: driver")
        drive = agents.run(driver, message, cwd=cwd, kind=kind, schema="task", access=p.get("access") or "auto",
                           resume=driver_resume, parent=o.id, title=f"pair r{round_no} driver: {task}",
                           verify=verify, max_attempts=int(p.get("driver_attempts") or 2))
        cost += _cost(drive)
        driver_resume = drive.meta.get("session_id") or drive.meta.get("thread_id") or driver_resume
        report_text = _driver_report_text(drive)
        o.note(driver, navigator, report_text or f"[driver error] {drive.error}", kind="reply",
               meta={"round": round_no, "status": drive.meta.get("status"), "job": drive.meta.get("job_id")})
        entry = {"round": round_no,
                 "driver_status": (drive.meta.get("status") or (drive.data or {}).get("status")
                                   or ("done" if drive.ok else "failed")),
                 "driver_job": drive.meta.get("job_id") or drive.meta.get("thread_id")}
        history.append(entry)
        if entry["driver_status"] in ("needs_input", "blocked", "cancelled") or (not drive.ok and not drive.data):
            status, reason = (entry["driver_status"] if entry["driver_status"] in ("needs_input", "blocked", "cancelled")
                              else "failed"), f"driver stopped in round {round_no}: {drive.error or entry['driver_status']}"
            break

        o.save(phase=f"round {round_no}: navigator")
        change = gitctx.working_tree(cwd, limit=40_000)  # navigators read the rest themselves
        checks = None
        if drive.meta.get("job_id"):
            checks = jobs.load(drive.meta["job_id"]).get("verification")
        elif verify:  # non-Claude driver: cic runs the checks itself so the navigator sees ground truth
            from .verify import run_checks

            checks = run_checks(verify, cwd, float(p.get("verify_timeout") or 900))
            o.log("checks for non-Claude driver: " + ", ".join(
                f"{c['command']}={'PASS' if c['ok'] else 'FAIL'}" for c in checks))
        review_prompt = prompts.pair_review_prompt(task=task, criteria=p.get("criteria"), round_no=round_no,
                                                   driver_report=report_text, checks=checks,
                                                   change_text=gitctx.render_for_prompt(change))
        nav = agents.run(navigator, review_prompt, cwd=cwd, kind="review", schema="review", access="read",
                         resume=navigator_resume, parent=o.id, title=f"pair r{round_no} navigator: {task}")
        cost += _cost(nav)
        navigator_resume = nav.meta.get("session_id") or nav.meta.get("thread_id") or navigator_resume
        verdict = (nav.data or {}).get("verdict")
        entry.update(navigator_verdict=verdict,
                     navigator_job=nav.meta.get("job_id") or nav.meta.get("thread_id"),
                     findings=len((nav.data or {}).get("findings") or []),
                     review=nav.data)
        o.note(navigator, driver, nav.text if nav.ok else f"[navigator error] {nav.error}", kind="reply",
               meta={"round": round_no, "verdict": verdict})
        o.log(f"round {round_no}: driver {entry['driver_status']}, navigator {verdict or 'error'}")
        if not nav.data:
            status, reason = "partial", f"navigator produced no review in round {round_no}: {nav.error}"
            break
        if verdict == "approve":
            status = "done" if entry["driver_status"] == "done" else "partial"
            break
        message = prompts.findings_for_driver(navigator, round_no, nav.data, nav.text)
        if round_no == rounds:
            status, reason = "partial", f"navigator still requesting changes after {rounds} round(s)"

    lines = [f"Task: {oneline(task, 300)}", f"Driver: {driver} · Navigator: {navigator}", "", "### Rounds"]
    for entry in history:
        lines.append(f"- round {entry['round']}: driver {entry['driver_status']} (job {entry.get('driver_job')}), "
                     f"navigator {entry.get('navigator_verdict') or 'n/a'} with {entry.get('findings', 0)} finding(s) "
                     f"(job {entry.get('navigator_job')})")
    last = history[-1] if history else {}
    if last.get("review"):
        from .render import _review_body

        lines += ["", f"### Last review ({navigator})"] + _review_body(last["review"])
    o.job["rounds"] = [{k: v for k, v in e.items() if k != "review"} for e in history]
    o.finish(status, "\n".join(lines), reason=reason, cost=cost)


def run_job(job_id: str) -> int:
    o = Orchestration(job_id)
    try:
        if o.job["kind"] == "council":
            run_council(o)
        else:
            run_pair(o)
    except Exception as exc:
        import traceback

        atomic_write_text(o.dir / "worker-error.txt", traceback.format_exc())
        o.finish("failed", f"Orchestration error: {exc!r}", reason="worker error (see worker-error.txt)")
        return 1
    return 0
