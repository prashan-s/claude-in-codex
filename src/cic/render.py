"""Compact markdown renderings for the orchestrator.

Output is written for an agent reader: highest-value information first,
no decoration, every follow-up command spelled out.
"""

from __future__ import annotations

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
    if route.get("score") is not None and not route.get("explicit_model"):
        bits.append(f"routed {route.get('tier')} (score {route.get('score')})")
    return " · ".join(bits)


def _list(title: str, items: list | None) -> list[str]:
    items = [i for i in (items or []) if str(i).strip()]
    if not items:
        return []
    return [f"### {title}"] + [f"- {i}" for i in items] + [""]


def render_final(job: dict) -> str:
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
    elif schema == "task" and report:
        lines += _task_body(job, report)
    else:
        text = (job.get("result_text") or "").strip()
        if text:
            lines += [text, ""]
        elif job.get("status") != "done":
            lines += ["(no answer text)", ""]
    if job.get("verification"):
        lines += _verification_body(job["verification"])
    progress = job.get("progress") or {}
    if progress.get("denials"):
        tools = sorted({d.get("tool") or "?" for d in progress["denials"]})
        lines += [f"Permission denials during the run: {', '.join(tools)}. Widen access with --access auto, "
                  "--allow 'Bash(<cmd> *)', or --access full if the task genuinely needs them.", ""]
    lines += _footer(job)
    return "\n".join(lines).rstrip() + "\n"


def _task_body(job: dict, report: dict) -> list[str]:
    lines = []
    if report.get("summary"):
        lines += [report["summary"].strip(), ""]
    changes = report.get("changes") or []
    if changes:
        lines.append("### Changes")
        lines += [f"- `{c.get('path')}`: {c.get('change')}" for c in changes]
        lines.append("")
    claims = report.get("verification") or []
    if claims:
        lines.append("### Checks Claude reports running")
        marks = {"pass": "pass", "fail": "FAIL", "not_run": "not run"}
        lines += [f"- [{marks.get(c.get('outcome'), c.get('outcome'))}] `{c.get('command')}`: {oneline(c.get('details'), 160)}"
                  for c in claims]
        lines.append("")
    lines += _list("Open questions", report.get("open_questions"))
    lines += _list("Assumptions", report.get("assumptions"))
    lines += _list("Risks", report.get("risks"))
    lines += _list("Next steps", report.get("next_steps"))
    if report.get("confidence") is not None:
        lines += [f"Confidence: {report['confidence']}", ""]
    return lines


def _review_body(report: dict) -> list[str]:
    lines = [f"Verdict: **{report.get('verdict')}**: {report.get('summary', '').strip()}", ""]
    findings = sorted(report.get("findings") or [], key=lambda f: _SEVERITY.get(f.get("severity"), 9))
    if not findings:
        lines += ["No material findings.", ""]
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
