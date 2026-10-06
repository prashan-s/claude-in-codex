"""Compact markdown renderings for the orchestrator.

Output is written for an agent reader: highest-value information first,
no decoration, every follow-up command spelled out.
"""

from __future__ import annotations

import threading

from .util import fmt_cost, fmt_duration, oneline

_LABEL = {
    "done": "DONE",
    "partial": "PARTIAL",
    "needs_input": "NEEDS INPUT",
    "blocked": "BLOCKED",
    "failed": "FAILED",
    "cancelled": "CANCELLED",
    "running": "RUNNING",
    "queued": "QUEUED",
}
_SEVERITY = {"critical": 0, "high": 1, "medium": 2, "low": 3}


# Report budgets: the orchestrator reads every line we print, so long sections are capped
# and the rest stays one command away (`cic result <job> --full`).
_CAPS = {"changes": 12, "claims": 6, "list": 6, "findings": 8, "text": 6000}


def _k(value: int) -> str:
    return f"{value / 1000:.1f}k" if value >= 1000 else str(value)


def token_summary(tokens: dict | None) -> str:
    if not tokens or not any(tokens.values()):
        return ""
    prompt = int(tokens.get("input", 0)) + int(tokens.get("cache_read", 0)) + int(tokens.get("cache_write", 0))
    cached = int(tokens.get("cache_read", 0)) / prompt if prompt else 0.0
    return f"tokens {_k(prompt)} in ({cached:.0%} cached) · {_k(int(tokens.get('output', 0)))} out"


def status_label(job: dict) -> str:
    label = _LABEL.get(job.get("status", ""), str(job.get("status", "?")).upper())
    if job.get("status") == "done" and job.get("schema") == "task":
        label += " ✓ verified" if job.get("verified") else " (not independently verified)"
    return label


def _model_line(job: dict) -> str:
    params = job.get("params") or {}
    route = params.get("route") or {}
    model = params.get("model") or "?"
    effort = f"/{params['effort']}" if params.get("effort") else ""
    bits = [f"model {model}{effort}"]
    for step in job.get("escalations") or []:
        bits.append(f"→ {step['to']} (attempt {step['attempt']})")
    if job.get("attempt"):
        bits.append(f"attempt {job['attempt']}/{params.get('max_attempts', 1)}")
    if job.get("elapsed") is not None:
        bits.append(fmt_duration(job["elapsed"]))
    if job.get("cost_usd"):
        bits.append(f"~{fmt_cost(job['cost_usd'])} est.")
    usage = token_summary(job.get("tokens") or (job.get("progress") or {}).get("tokens"))
    if usage:
        bits.append(usage)
    if route.get("score") is not None and not route.get("explicit_model"):
        bits.append(f"routed {route.get('tier')} (score {route.get('score')})")
    return " · ".join(bits)


class _Budget:
    """Tracks whether any section was trimmed so the report can say how to see the rest."""

    def __init__(self, full: bool):
        self.full = full
        self.trimmed = False

    def take(self, items: list, cap_key: str) -> tuple[list, int]:
        cap = _CAPS[cap_key]
        if self.full or len(items) <= cap:
            return items, 0
        self.trimmed = True
        return items[:cap], len(items) - cap

    def text(self, value: str) -> str:
        cap = _CAPS["text"]
        if self.full or len(value) <= cap:
            return value
        self.trimmed = True
        return value[:cap].rstrip() + "\n…"


_local = threading.local()  # per-thread budget: council members render reports in parallel threads


def _current() -> "_Budget":
    budget = getattr(_local, "budget", None)
    if budget is None:
        budget = _local.budget = _Budget(full=True)
    return budget


def _list(title: str, items: list | None) -> list[str]:
    items = [i for i in (items or []) if str(i).strip()]
    if not items:
        return []
    shown, more = _current().take(items, "list")
    lines = [f"### {title}"] + [f"- {i}" for i in shown]
    if more:
        lines.append(f"- (+{more} more)")
    return lines + [""]


def render_final(job: dict, *, full: bool = False) -> str:
    _local.budget = _Budget(full)
    kind = job.get("kind")
    lines = [f"## {status_label(job)} · {kind} · {job['id']}", _model_line(job), ""]
    if job.get("reason"):
        lines += [f"Reason: {job['reason']}", ""]
    schema = job.get("schema")
    report = job.get("report") or {}
    if schema == "review" and report:
        lines += _review_body(report)
    elif schema == "plan" and report:
        lines += _plan_body(report)
    elif schema == "improve" and report:
        lines += _improve_body(job, report)
    elif schema == "task" and report:
        lines += _task_body(job, report)
    else:
        text = (job.get("result_text") or "").strip()
        if text:
            lines += [_current().text(text), ""]
        elif job.get("status") != "done":
            lines += ["(no answer text)", ""]
    if job.get("verification"):
        lines += _verification_body(job["verification"])
    progress = job.get("progress") or {}
    if progress.get("denials"):
        tools = sorted({d.get("tool") or "?" for d in progress["denials"]})
        if (job.get("params") or {}).get("access") == "read":
            lines += [f"Read-only mode blocked {len(progress['denials'])} attempted action(s) ({', '.join(tools)}); "
                      "conclusions that needed them are inferred from reading code.", ""]
        else:
            lines += [f"Permission denials during the run: {', '.join(tools)}. Widen access with --access auto, "
                      "--allow 'Bash(<cmd> *)', or --access full if the task genuinely needs them.", ""]
    if _current().trimmed:
        lines += [f"(Trimmed for length; `cic result {job['id']} --full` shows everything.)", ""]
    lines += _footer(job)
    return "\n".join(lines).rstrip() + "\n"


def _task_body(job: dict, report: dict) -> list[str]:
    lines = []
    if report.get("summary"):
        lines += [report["summary"].strip(), ""]
    changes = report.get("changes") or []
    if changes:
        shown, more = _current().take(changes, "changes")
        lines.append("### Changes")
        lines += [f"- `{c.get('path')}`: {c.get('change')}" for c in shown]
        if more:
            lines.append(f"- (+{more} more files)")
        lines.append("")
    claims = report.get("verification") or []
    if claims:
        shown, more = _current().take(claims, "claims")
        lines.append("### Checks Claude reports running")
        marks = {"pass": "pass", "fail": "FAIL", "not_run": "not run"}
        lines += [f"- [{marks.get(c.get('outcome'), c.get('outcome'))}] `{c.get('command')}`: {oneline(c.get('details'), 160)}"
                  for c in shown]
        if more:
            lines.append(f"- (+{more} more)")
        lines.append("")
    lines += _list("Open questions", report.get("open_questions"))
    lines += _list("Assumptions", report.get("assumptions"))
    lines += _list("Risks", report.get("risks"))
    lines += _list("Next steps", report.get("next_steps"))
    if report.get("confidence") is not None:
        confidence = report["confidence"]
        note = ""
        if isinstance(confidence, (int, float)) and confidence < 0.7:
            note = " (low: get a second look with `cic review` or `cic council` before relying on it)"
        if job.get("uncertainty_checked"):
            note += " · an uncertainty pass already ran"
        lines += [f"Confidence: {confidence}{note}", ""]
    return lines


def _shell_quote(text: str) -> str:
    import shlex

    return shlex.quote(text)


def _improve_body(job: dict, report: dict) -> list[str]:
    lines = []
    issues = report.get("issues") or []
    if issues:
        lines.append("### What was weak")
        lines += [f"- {i.get('problem')} [{i.get('principle')}]: {i.get('fix')}" for i in issues]
        lines.append("")
    lines += ["### Improved brief", report.get("improved_task", "").strip(), ""]
    for title, key in (("Start files", "files"), ("Acceptance criteria", "done"), ("Checks", "verify"),
                       ("Hints", "hints"), ("Constraints", "constraints"), ("Split-out follow-ups", "follow_ups")):
        lines += _list(title, report.get(key))
    if report.get("notes"):
        lines += [f"Notes: {report['notes']}", ""]
    command = ["cic run", _shell_quote(" ".join((report.get("improved_task") or "").split()))]
    command.append(f"--cwd {_shell_quote(job.get('cwd') or '.')}")
    if report.get("kind"):
        command.append(f"--kind {report['kind']}")
    for flag, key in (("--file", "files"), ("--done", "done"), ("--verify", "verify"), ("--hint", "hints"),
                      ("--constraint", "constraints")):
        command += [f"{flag} {_shell_quote(v)}" for v in report.get(key) or []]
    lines += ["### Ready to run", "```", " ".join(command), "```", ""]
    return lines


def _review_body(report: dict) -> list[str]:
    lines = [f"Verdict: **{report.get('verdict')}**: {report.get('summary', '').strip()}", ""]
    findings = sorted(report.get("findings") or [], key=lambda f: _SEVERITY.get(f.get("severity"), 9))
    if not findings:
        lines += ["No material findings.", ""]
    findings, more = _current().take(findings, "findings")
    if more:
        lines.append(f"Showing the {len(findings)} most severe of {len(findings) + more} findings.")
    for index, f in enumerate(findings, 1):
        where = f.get("file") or "?"
        if f.get("line_start"):
            where += f":{f['line_start']}"
            if f.get("line_end") and f["line_end"] != f["line_start"]:
                where += f"-{f['line_end']}"
        lines.append(f"{index}. [{str(f.get('severity', '?')).upper()}] {f.get('title')} ({where}, confidence {f.get('confidence')})")
        lines.append(f"   {f.get('body', '').strip()}")
        lines.append(f"   Fix: {f.get('recommendation', '').strip()}")
    lines.append("")
    lines += _list("Next steps", report.get("next_steps"))
    return lines


def _plan_body(report: dict) -> list[str]:
    lines = []
    if report.get("summary"):
        lines += [report["summary"].strip(), ""]
    if report.get("approach"):
        lines += ["### Approach", report["approach"].strip(), ""]
    alts = report.get("alternatives") or []
    if alts:
        lines.append("### Rejected alternatives")
        lines += [f"- {a.get('option')}: {a.get('why_not')}" for a in alts]
        lines.append("")
    steps = report.get("steps") or []
    if steps:
        lines.append("### Steps")
        for index, step in enumerate(steps, 1):
            files = f" [{', '.join(step.get('files') or [])}]" if step.get("files") else ""
            lines.append(f"{index}. {step.get('title')}{files}: {step.get('details')}")
            if step.get("verify"):
                lines.append(f"   verify: {step['verify']}")
        lines.append("")
    lines += _list("Risks", report.get("risks"))
    lines += _list("Verification", report.get("verification"))
    lines += _list("Open questions", report.get("open_questions"))
    return lines


def _verification_body(results: list[dict]) -> list[str]:
    lines = ["### Checks re-run by cic (ground truth)"]
    for item in results:
        mark = "PASS" if item.get("ok") else f"FAIL (exit {item.get('exit_code')})"
        if item.get("env_error"):
            mark = f"CANNOT RUN: {item['env_error']}"
        lines.append(f"- [{mark}] `{item.get('command')}` ({item.get('seconds')}s)")
        if not item.get("ok") and item.get("output_tail"):
            snippet = "\n".join(item["output_tail"].splitlines()[-12:])
            lines.append("  ```\n  " + snippet.replace("\n", "\n  ") + "\n  ```")
    lines.append("")
    return lines


def _footer(job: dict) -> list[str]:
    jid = job["id"]
    kind = job.get("kind")
    status = job.get("status")
    tips = []
    if kind in ("pair", "council"):
        tips.append(f"`cic logs {jid}` for the full exchange")
    elif kind == "say":
        name = job.get("session_name")
        tips.append(f'`cic say {name} "<next message>"` to continue')
    elif status in ("partial", "needs_input", "blocked", "failed", "done"):
        if status == "needs_input":
            tips.append(f'`cic reply {jid} "<answers>"` to answer and continue')
        elif status in ("partial", "failed", "blocked"):
            tips.append(f'`cic reply {jid} "<guidance>"` to continue on the same Claude session')
        else:
            tips.append(f'`cic reply {jid} "<follow-up>"` for changes')
        tips.append(f"`cic logs {jid}` for the step log")
        if job.get("schema") == "task":
            tips.append("review the edits with `git diff`")
    sid = job.get("session_id")
    lines = []
    if tips:
        lines.append("Next: " + " · ".join(tips))
    if sid and kind not in ("pair", "council"):
        lines.append(f"Claude session: {sid} (open interactively with `claude --resume {sid}`)")
    return lines


def render_status(job: dict) -> str:
    progress = job.get("progress") or {}
    lines = [f"{job['id']} · {job.get('kind')} · {status_label(job)} · phase {job.get('phase')} · "
             f"{fmt_duration(job.get('elapsed'))}"]
    lines.append(f"task: {job.get('title')}")
    lines.append(_model_line(job))
    if progress:
        uses = progress.get("tool_uses", 0)
        bits = [f"{uses} tool call{'s' if uses != 1 else ''}"]
        if progress.get("files"):
            count = len(progress["files"])
            bits.append(f"{count} file{'s' if count != 1 else ''} edited")
        if progress.get("tool_errors"):
            bits.append(f"{progress['tool_errors']} tool errors")
        if progress.get("denials"):
            bits.append(f"{len(progress['denials'])} denied")
        if progress.get("api_retries"):
            bits.append(f"{progress['api_retries']} API retries ({progress.get('last_error')})")
        if progress.get("rate_limit"):
            bits.append(f"rate limit {progress['rate_limit']}")
        lines.append("activity: " + ", ".join(bits))
        if progress.get("last_tool"):
            lines.append(f"last action: {progress['last_tool']}")
        if progress.get("last_text"):
            lines.append(f"last message: {oneline(progress['last_text'], 200)}")
        if progress.get("permission_mode") and progress.get("permission_mode") != job.get("expected_permission_mode"):
            if job.get("expected_permission_mode"):
                lines.append(f"warning: permission mode is {progress['permission_mode']}, requested {job['expected_permission_mode']}")
    if job.get("reason"):
        lines.append(f"reason: {job['reason']}")
    if job.get("status") in ("queued", "running"):
        lines.append(f"next: `cic wait {job['id']} --timeout 300` · `cic steer {job['id']} \"<message>\"` · `cic cancel {job['id']}`")
    else:
        lines.append(f"next: `cic result {job['id']}`")
    return "\n".join(lines) + "\n"


def render_stats(jobs: list[dict], scope: str) -> str:
    """Token and cost usage across jobs, with concrete advice for spending less."""
    if not jobs:
        return f"No jobs in {scope}.\n"
    by_tier: dict[str, dict] = {}
    statuses: dict[str, int] = {}
    verified = 0
    for job in jobs:
        statuses[job.get("status", "?")] = statuses.get(job.get("status", "?"), 0) + 1
        verified += 1 if job.get("verified") else 0
        model = str(job.get("model_final") or (job.get("params") or {}).get("model") or "?")
        tier = next((t for t in ("haiku", "sonnet", "opus", "fable") if t in model.lower()), model)
        row = by_tier.setdefault(tier, {"jobs": 0, "input": 0, "output": 0, "cache_read": 0, "cache_write": 0,
                                        "cost": 0.0})
        row["jobs"] += 1
        row["cost"] += float(job.get("cost_usd") or 0.0)
        for key in ("input", "output", "cache_read", "cache_write"):
            row[key] += int((job.get("tokens") or {}).get(key, 0))
    done = statuses.get("done", 0)
    attention = sum(statuses.get(s, 0) for s in ("partial", "needs_input", "blocked"))
    failed = statuses.get("failed", 0) + statuses.get("cancelled", 0)
    lines = [f"{len(jobs)} jobs in {scope}: {done} done ({verified} verified) · {attention} need attention · "
             f"{failed} failed/cancelled", "",
             "| model | jobs | prompt tokens | cached | output tokens | est. cost |", "|---|---|---|---|---|---|"]
    total_cost = sum(r["cost"] for r in by_tier.values()) or 0.0
    total_prompt = total_read = 0
    for tier, row in sorted(by_tier.items(), key=lambda item: -item[1]["cost"]):
        prompt = row["input"] + row["cache_read"] + row["cache_write"]
        total_prompt += prompt
        total_read += row["cache_read"]
        share = f"{row['cache_read'] / prompt:.0%}" if prompt else "-"
        lines.append(f"| {tier} | {row['jobs']} | {_k(prompt)} | {share} | {_k(row['output'])} | {fmt_cost(row['cost'])} |")
    lines.append("")
    tips = []
    if total_prompt and total_read / total_prompt < 0.6:
        tips.append("Cache reuse is under 60%: keep the default `standard` profile, reuse sessions for related "
                    "follow-ups (`cic reply`), and avoid switching models mid-session.")
    opus = by_tier.get("opus", {}).get("cost", 0.0)
    if total_cost and opus / total_cost > 0.5:
        tips.append(f"Opus is {opus / total_cost:.0%} of estimated cost: check routing with `cic route`, "
                    "use `--plan` (Opus plans, Sonnet executes), or pin `--tier balanced` for routine work.")
    if attention + failed > done and len(jobs) >= 4:
        tips.append("More jobs need attention than finish: sharpen briefs with `cic improve` and add `--verify` checks.")
    lines += [f"Tip: {t}" for t in tips] or ["Usage looks healthy."]
    return "\n".join(lines) + "\n"


def render_jobs(jobs: list[dict]) -> str:
    if not jobs:
        return "No jobs.\n"
    lines = ["| job | kind | status | model | age | task |", "|---|---|---|---|---|---|"]
    for job in jobs:
        params = job.get("params") or {}
        lines.append(
            f"| {job['id']} | {job.get('kind')} | {_LABEL.get(job.get('status'), job.get('status'))} | "
            f"{params.get('model', '?')} | {fmt_duration(job.get('elapsed'))} | {oneline(job.get('title'), 60)} |"
        )
    return "\n".join(lines) + "\n"
