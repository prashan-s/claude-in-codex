"""Delegation contracts and brief construction.

Two layers, kept separate on purpose:

* The *contract* is appended to Claude Code's system prompt. It is static text
  per job family so the prompt cache is reused across jobs, and Claude Code
  records it on the first request, so it survives --resume.
* The *brief* is the user message: task, context, acceptance criteria,
  verification, constraints, and a technique block chosen per task kind
  (plan-then-act, reproduce-first, hypothesis loops, tree-of-thought options...).
"""

from __future__ import annotations

import re
from pathlib import Path

from .util import git_info, today

# ----------------------------------------------------------------- contracts

CONTRACT_WORK = """\
# Delegated task protocol

You are running headless as a delegated engineer. An orchestrating agent (usually Codex) assigned this task and will read your final structured report. No human is watching this session, and nobody can answer questions until you finish.

## How to work
- Investigate before editing. Read the code you will touch, find the existing patterns, helpers, and tests to reuse, and confirm assumptions with tools rather than guessing.
- Make the smallest change that fully solves the task, in the style of the surrounding code. Skip unrelated refactors, renames, and formatting churn: they make the orchestrator's review harder.
- Fix root causes rather than symptoms. Never weaken, skip, or delete tests to make them pass; a test that exposes a real bug is a finding to report.
- Verify your work by running the most relevant tests, build, or lint commands. If verification cannot run (denied permission, missing tooling), say so plainly instead of implying success.
- When something is ambiguous, take the most reasonable low-risk interpretation, record it under assumptions, and keep going. Stop early only when a missing decision would change correctness, security, or an irreversible action; then finish with status "needs_input" and precise questions.
- Leave all changes uncommitted in the working tree. Do not commit, push, publish, deploy, or delete data unless the task explicitly asks.
- Keep side effects inside the working directory. Do not install packages globally or user-wide, edit shell profiles, or change system settings: the orchestrator's machine is shared. Project-local setup (a virtualenv or node_modules inside the repo) is fine when the task needs it. If a required tool is missing, finish with status "blocked" and name the exact command that would provide it.
- Do not hand this task to another agent or CLI (Codex, Gemini, another Claude); do the work yourself.
- Keep going until the task is complete or you are genuinely blocked. A plan or a partial fix is not a finished task.
- A user message that arrives mid-task is steering from the orchestrator. Fold it into the work.

## Final report
Finish with the structured report. Be factual and specific: every file you changed, every verification command you ran with its real outcome, and anything left undone. Status meanings:
- done: every acceptance criterion is met and verified (or verification was impossible and you said why)
- partial: some criteria remain; list them in next_steps
- needs_input: only the orchestrator can make a required decision; list the questions
- blocked: an external obstacle such as missing permissions, credentials, or a broken environment
- failed: no meaningful progress was possible
Rate confidence honestly between 0 and 1.
"""

CONTRACT_READ = """\
# Delegated analysis protocol

You are running headless for an orchestrating agent (usually Codex) that will read your final answer. No human is watching, and nobody can answer questions until you finish.

- This is a read-only assignment. Do not create, edit, or delete files, and do not run commands that change state.
- Ground every claim in what you actually inspected: cite file paths with line numbers, commands you ran, or sources you read. Label inferences as inferences.
- Prefer one well-supported conclusion over many weak ones. When evidence is missing, say exactly what is unknown.
- Do not hand this work to another agent or CLI; do it yourself.
- Keep the final answer compact and structured. The orchestrator pays for every token it reads.
"""

CONTRACT_CHAT = """\
# Conversation protocol

You are in a multi-turn working conversation with another AI agent (usually Codex) that is coordinating work for its user, sometimes relaying the user's words. Each message is one turn of the dialogue and a genuine request from that orchestrator: treat it as you would a message from the user. Earlier turns are shared context you can rely on.

- Answer directly and concisely; lead with the answer, then the essential reasoning.
- Ground claims in the repository when relevant: cite file paths with line numbers.
- You may ask clarifying questions when a decision genuinely needs them.
- Only change files when a message explicitly asks you to; otherwise discuss, analyze, and propose.
- Do not hand work to another agent or CLI unless asked.
"""

BUS_ADDENDUM = """\

## Messaging other agents
You are bus agent `{name}`; this conversation is thread `{thread}`. Other agents (for example `codex` or other Claude agents) are reachable through the cic message bus with single plain commands:
- Ask a peer and wait for its reply: cic bus ask --from {name} --to <agent> --thread {thread} "<message>" --wait 100 (if it times out, run cic bus recv --as {name} --thread {thread} --wait 100 to keep waiting)
- Notify a peer without waiting: cic bus send --from {name} --to <agent> --thread {thread} "<message>"
Message peers only when you need their input or must hand them something, and keep messages short and self-contained. Your final reply to this message is delivered to the sender automatically.
"""


def contract_for(kind: str, *, chat: bool = False, role: str | None = None) -> str:
    if chat:
        text = CONTRACT_CHAT
    elif kind in ("review", "research", "plan", "explain", "ask"):
        text = CONTRACT_READ
    else:
        text = CONTRACT_WORK
    if role:
        text += f"\n## Your role\n{role.strip()}\n"
    return text


# ----------------------------------------------------------------- techniques
# Each kind gets the technique that best fits it (see claude-prompting skill):
# plan-then-act, reproduce-first, ReAct-style hypothesis loops, characterization
# tests, tree-of-thought option comparison, grounded research.

APPROACH = {
    "implement": """\
1. Orient: read the code this change touches and find the existing patterns, helpers, and tests to reuse.
2. Plan briefly, then implement the smallest complete change.
3. Prove it: add or update tests for the new behavior, run the verification commands, and iterate until they pass.
4. Re-read your diff as a strict reviewer would: edge cases, error handling, naming, leftover debug code.""",
    "fix": """\
1. Reproduce first: find or write the smallest failing test or command that shows the bug. If it will not reproduce, say what you tried.
2. Trace the failing path to the root cause and state it in one sentence before editing.
3. Fix it at the root with the smallest safe change; keep behavior outside the failing path unchanged.
4. Confirm the reproduction now passes, add a regression test if none exists, then run the broader verification.""",
    "debug": """\
Investigate in an observe -> hypothesize -> test loop:
1. Collect observations: exact error text, logs, recent changes (git log / git diff), and the code path involved.
2. Rank plausible causes by likelihood and by how cheaply each can be checked.
3. Run the cheapest experiment that discriminates between the top hypotheses (targeted logging, a probe test, narrowing inputs). Update the ranking from evidence; never assert a cause you have not confirmed.
4. {finish}
In the summary, separate confirmed facts from inferences.""",
    "refactor": """\
1. Build a safety net first: run the existing tests for the affected area; if coverage is thin, add characterization tests that pin current behavior.
2. Refactor in small, behavior-preserving steps. Keep public interfaces stable unless the task says otherwise.
3. Re-run the tests: behavior must be identical. Call out any intentional behavior change explicitly.""",
    "test": """\
1. List the behaviors that matter: happy path, boundaries, invalid input, error paths, and time or concurrency where relevant. Follow the project's existing test framework and style.
2. Test observable behavior rather than implementation details. Keep tests deterministic: no real network, fixed seeds and clocks.
3. Run the new tests and the surrounding suite. If a new test fails because of a real product bug, report it as a finding instead of bending the test.""",
    "docs": """\
Ground every statement in the code: read it before you describe it. Lead with what the reader needs to do, keep examples runnable, and match the existing documentation's tone and format.""",
    "chore": """\
Make exactly the mechanical change requested, nothing more, then run a quick check (build, lint, or the tests touching the change).""",
    "research": """\
Survey the realistic options breadth-first, then go deep only where the evidence would change the recommendation. Ground claims in sources you actually inspected (file paths with line numbers, documentation URLs). Separate observed facts, inferences, and open questions, and end with a clear recommendation.""",
    "plan": """\
Explore the relevant code first. Then generate two or three materially different approaches, evaluate each against the acceptance criteria (correctness, risk, effort, reversibility), and choose one with a clear rationale. Produce ordered steps where each step names its files and how to verify it.""",
    "explain": """\
Answer directly and concisely, grounded in the code, citing file paths with line numbers. Say plainly when something is uncertain.""",
    "ask": """\
Answer directly and concisely. Ground repository claims in files you read and cite them. Say plainly when something is uncertain.""",
}

DEFAULT_CRITERIA = {
    "implement": [
        "The requested behavior works as described.",
        "Existing tests still pass, and the new behavior is covered by tests where the project has tests.",
        "No unrelated changes.",
    ],
    "fix": [
        "The bug no longer reproduces.",
        "A regression test covers it where the project has tests.",
        "Behavior outside the failing path is unchanged.",
    ],
    "debug": [
        "The root cause is identified with evidence.",
        "The fix is applied and verified.",
    ],
    "refactor": [
        "Behavior is unchanged and all tests pass.",
        "The code is measurably simpler or clearer in the way the task asks.",
    ],
    "test": [
        "New tests pass and are deterministic.",
        "The important behaviors and edge cases are covered.",
    ],
    "docs": ["The documentation is accurate against the current code and easy to act on."],
    "chore": ["The change is applied exactly as requested and nothing else changed."],
    "research": ["A clear recommendation backed by inspected evidence, with trade-offs and open questions."],
    "plan": ["A chosen approach with rationale, rejected alternatives, and verifiable ordered steps."],
}

_MAX_INLINE_FILE = 20_000
_MAX_INLINE_TOTAL = 60_000


def _context_block(cwd: str, files: list[str], context: list[str], context_files: list[str]) -> str:
    lines = [f"Working directory: {cwd}", f"Today: {today()}"]
    git = git_info(cwd)
    if git.get("is_repo"):
        dirty = f", {git['changed']} uncommitted change(s)" if git["changed"] else ", clean tree"
        lines.append(f"Git: branch {git['branch']}{dirty}")
        if git["changed"]:
            lines.extend(f"  {line}" for line in git["status_lines"][:12])
    else:
        lines.append("Git: not a repository")
    if files:
        lines.append("Start with these files: " + ", ".join(files))
    for item in context:
        lines.append(item.strip())
    budget = _MAX_INLINE_TOTAL
    for path in context_files:
        p = Path(path).expanduser()
        if not p.is_absolute():
            p = Path(cwd) / p
        try:
            data = p.read_text(encoding="utf-8", errors="replace")
        except OSError:
            lines.append(f"(context file not readable: {path})")
            continue
        if len(data) > _MAX_INLINE_FILE or len(data) > budget:
            lines.append(f"Read this file for background (too large to inline): {p}")
            continue
        budget -= len(data)
        lines.append(f'<file path="{p}">\n{data.rstrip()}\n</file>')
    return "\n".join(lines)


def build_brief(
    task: str,
    *,
    kind: str,
    cwd: str,
    files: list[str] | None = None,
    context: list[str] | None = None,
    context_files: list[str] | None = None,
    criteria: list[str] | None = None,
    verify: list[str] | None = None,
    constraints: list[str] | None = None,
    read_only: bool = False,
    plan: dict | None = None,
) -> str:
    """Assemble the user message for a delegated task."""
    parts = [f"<task>\n{task.strip()}\n</task>"]
    parts.append("<context>\n" + _context_block(cwd, files or [], context or [], context_files or []) + "\n</context>")

    if plan:
        parts.append("<plan>\nFollow this reviewed plan. Deviate only if you find it is wrong, and say why in the report.\n" + render_plan(plan) + "\n</plan>")

    crit = criteria or DEFAULT_CRITERIA.get(kind)
    if crit:
        if kind == "debug" and read_only and not criteria:
            crit = ["The root cause is identified with evidence, and the smallest safe fix is described but not applied."]
        parts.append("<acceptance_criteria>\n" + "\n".join(f"- {c}" for c in crit) + "\n</acceptance_criteria>")

    if verify:
        checks = "\n".join(f"- `{cmd}`" for cmd in verify)
        parts.append(
            "<verification>\nThese checks must pass. The orchestrator re-runs them independently after you finish:\n"
            f"{checks}\n</verification>"
        )

    cons = list(constraints or [])
    if read_only:
        cons.append("Read-only: do not modify any files.")
    if cons:
        parts.append("<constraints>\n" + "\n".join(f"- {c}" for c in cons) + "\n</constraints>")

    approach = APPROACH.get(kind)
    if approach:
        if kind == "debug":
            finish = (
                "Stop at a confirmed root cause and describe the smallest safe fix without editing files."
                if read_only
                else "Once the cause is confirmed, fix it with the smallest root-cause change and verify."
            )
            approach = approach.format(finish=finish)
        parts.append(f"<approach>\n{approach}\n</approach>")
    return "\n\n".join(parts) + "\n"


def chat_opening(message: str, *, cwd: str) -> str:
    """First turn of a conversation: shared context once, then the message itself."""
    return f"<context>\n{_context_block(cwd, [], [], [])}\n</context>\n\n{message.strip()}\n"


def build_plan_brief(task: str, *, cwd: str, files: list[str] | None, context: list[str] | None,
                     context_files: list[str] | None, criteria: list[str] | None, verify: list[str] | None,
                     constraints: list[str] | None) -> str:
    brief = build_brief(task, kind="plan", cwd=cwd, files=files, context=context, context_files=context_files,
                        criteria=criteria, verify=None, constraints=constraints, read_only=True)
    if verify:
        brief += "\nThe implementation will be verified with: " + ", ".join(f"`{v}`" for v in verify) + "\n"
    brief += "\nThis is the planning phase only: a separate implementation run will execute your plan.\n"
    return brief


def render_plan(plan: dict) -> str:
    lines = []
    if plan.get("approach"):
        lines.append(f"Approach: {plan['approach']}")
    for index, step in enumerate(plan.get("steps") or [], 1):
        files = f" [{', '.join(step.get('files') or [])}]" if step.get("files") else ""
        verify = f" (verify: {step['verify']})" if step.get("verify") else ""
        lines.append(f"{index}. {step.get('title', '')}{files}: {step.get('details', '')}{verify}")
    if plan.get("risks"):
        lines.append("Risks: " + "; ".join(plan["risks"]))
    return "\n".join(lines)


# ----------------------------------------------------------------- follow-ups

def verification_failed_message(results: list[dict], attempt: int, max_attempts: int) -> str:
    blocks = []
    for item in results:
        if item["ok"]:
            continue
        blocks.append(
            f"<check command=\"{item['command']}\" exit_code=\"{item['exit_code']}\">\n{item['output_tail']}\n</check>"
        )
    return (
        "<verification_failed>\n"
        "The orchestrator re-ran the required checks after your report, and some failed:\n\n"
        + "\n\n".join(blocks)
        + "\n</verification_failed>\n\n"
        f"This is repair attempt {attempt} of {max_attempts - 1}. Diagnose why each check fails, fix the root cause "
        "(not the test), re-run the checks yourself until they pass, then send an updated structured report."
    )


def continue_message(report: dict | None) -> str:
    remaining = ""
    if report and report.get("next_steps"):
        remaining = "\nRemaining items from your report:\n" + "\n".join(f"- {s}" for s in report["next_steps"])
    return (
        "<continue>\nThe task is not finished yet. Keep working until every acceptance criterion is met and verified."
        f"{remaining}\nIf you are truly blocked, explain exactly why. Finish with an updated structured report.\n</continue>"
    )


REPORT_MISSING_MESSAGE = (
    "Your last turn ended without the structured report. Send the final structured report now, "
    "reflecting the real state of the work."
)


def follow_up_message(text: str) -> str:
    return (
        f"<follow_up>\n{text.strip()}\n</follow_up>\n\n"
        "Continue in the same working tree and finish with an updated structured report."
    )


# ----------------------------------------------------------------- review

_ATTACK_SURFACE = """\
Prioritize failures that are expensive, dangerous, or hard to detect:
- auth, permissions, tenant isolation, and trust boundaries
- data loss, corruption, duplication, and irreversible state changes
- rollback safety, retries, partial failure, and idempotency
- race conditions, ordering assumptions, stale state, and re-entrancy
- empty-state, null, timeout, and degraded-dependency behavior
- version skew, schema drift, migrations, and compatibility
- observability gaps that would hide a failure"""


def build_review_prompt(*, label: str, change_text: str, focus: str | None, adversarial: bool) -> str:
    stance = (
        "Your job is to find the strongest reasons this change should not ship yet, not to validate it. "
        "Assume it can fail in subtle, costly ways until the code proves otherwise; give no credit for intent or likely follow-ups."
        if adversarial
        else "Your job is to catch the problems a careful senior reviewer would block on before merge."
    )
    method = (
        "- Read the surrounding code, not just the diff: callers, invariants, and existing tests.\n"
        "- Trace how bad inputs, retries, concurrent actions, and partial failures move through the changed paths.\n"
        "- After the first plausible issue, check second-order effects: error paths, empty states, stale state, rollback, compatibility."
    )
    if adversarial:
        method += "\n" + _ATTACK_SURFACE
    return f"""<role>
You are reviewing {label} in this repository. {stance}
</role>

<focus>
{focus.strip() if focus else "Correctness, regressions, security, and missing tests for new behavior."}
</focus>

<change>
{change_text}
</change>

<method>
{method}
</method>

<finding_bar>
Report only material findings an engineer would act on: correctness, security, data integrity, reliability, performance regressions, broken contracts, missing tests for risky behavior. Skip style, naming, and formatting. Each finding names the file and line range, says what goes wrong, why this code path is vulnerable, the likely impact, and a concrete fix.
</finding_bar>

<grounding>
Every finding must be defensible from code you inspected. Never invent files, lines, or runtime behavior. If a conclusion rests on an inference, say so in the body and lower its confidence.
</grounding>

<calibration>
Prefer one strong finding over several weak ones. Use verdict "approve" when you cannot support a material finding, and write the summary as a terse ship / no-ship call. This review is read-only: do not modify files.
</calibration>
"""


# ----------------------------------------------------------------- multi-agent

def council_member_prompt(question: str, *, cwd: str, context: list[str] | None = None,
                          files: list[str] | None = None) -> str:
    extra = "\n".join(c.strip() for c in (context or []))
    if files:
        extra += ("\n" if extra else "") + "Relevant files: " + ", ".join(files)
    return f"""<question>
{question.strip()}
</question>

<context>
Working directory: {cwd}
Today: {today()}
{extra}
</context>

<instructions>
You are one member of a panel of independent AI agents answering the same question; a moderator will compare the answers. Reason independently. Ground claims about the repository in files you actually read (cite path:line). Do not modify anything.

Answer in this shape, in under 350 words:
ANSWER: the direct answer or recommendation
REASONS: the 2-5 strongest reasons, with evidence
RISKS: what would make this answer wrong
CONFIDENCE: a number from 0 to 1
</instructions>
"""


def council_synth_prompt(question: str, answers: list[tuple[str, str]], unavailable: list[tuple[str, str]]) -> str:
    panel = "\n\n".join(f'<answer agent="{name}">\n{text.strip()}\n</answer>' for name, text in answers)
    missing = "\n".join(f"- {name}: {why}" for name, why in unavailable) or "(none)"
    return f"""<question>
{question.strip()}
</question>

<panel>
{panel}
</panel>

<unavailable_members>
{missing}
</unavailable_members>

<instructions>
You are the moderator. Weigh evidence, not votes: where the answers conflict on a checkable fact about the repository, check it yourself (read-only) and say who was right. Produce, in under 450 words:
1. Final answer or recommendation
2. Consensus: points every member supports
3. Disagreements: each one with the evidence that resolves it, or why it stays open
4. Confidence (0-1) and the main residual risk
</instructions>
"""


def pair_review_prompt(*, task: str, criteria: list[str] | None, round_no: int, driver_report: str,
                       checks: list[dict] | None, change_text: str) -> str:
    crit = "\n".join(f"- {c}" for c in (criteria or [])) or "- The task is fully and correctly done."
    if checks:
        rerun = "\n".join(f"- [{'PASS' if c.get('ok') else 'FAIL'}] {c.get('command')}" for c in checks)
    else:
        rerun = "(no independent checks configured)"
    previous = ("\nThis is round {n}. Check specifically whether each finding from your previous review was resolved, "
                "then look for anything new.".format(n=round_no)) if round_no > 1 else ""
    return f"""<role>
You are the navigator in a pair-programming loop. The driver, another AI agent, has just finished round {round_no} of the task below. Review the actual changes, not the driver's description of them.{previous}
</role>

<task>
{task.strip()}
</task>

<acceptance_criteria>
{crit}
</acceptance_criteria>

<driver_report>
{driver_report.strip() or "(no report)"}
</driver_report>

<checks_rerun_by_orchestrator>
{rerun}
</checks_rerun_by_orchestrator>

<change>
{change_text}
</change>

<instructions>
Read surrounding code as needed (read-only). Report only material problems: unmet requirements, correctness bugs, regressions, security issues, missing tests for new behavior. Approve when the work meets the acceptance criteria and you cannot support a material finding; never withhold approval over style.
</instructions>
"""


def findings_for_driver(navigator: str, round_no: int, report: dict | None, fallback_text: str) -> str:
    if not report:
        return f"The navigator ({navigator}) reviewed round {round_no}:\n{fallback_text.strip()}\n\nAddress the issues raised, re-run the checks, and report again."
    lines = [f"The navigator ({navigator}) reviewed round {round_no} and requested changes: {report.get('summary', '').strip()}"]
    for index, finding in enumerate(report.get("findings") or [], 1):
        where = finding.get("file") or "?"
        if finding.get("line_start"):
            where += f":{finding['line_start']}"
        lines.append(f"{index}. [{str(finding.get('severity', '?')).upper()}] {finding.get('title')} ({where}): "
                     f"{finding.get('body', '').strip()} Fix: {finding.get('recommendation', '').strip()}")
    lines.append("\nAddress every finding, or explain in your report why one is invalid. Then re-run the checks and send an updated report.")
    return "\n".join(lines)


# ----------------------------------------------------------------- lint

_VAGUE_REF = re.compile(r"\b(this|that|the) (bug|issue|error|problem|thing|file|function)\b", re.I)
_SECRET = re.compile(r"(sk-[A-Za-z0-9_-]{16,}|AKIA[0-9A-Z]{16}|ghp_[A-Za-z0-9]{20,}|xox[bp]-[A-Za-z0-9-]{10,})")


def lint_brief(task: str, *, kind: str, criteria: list[str] | None, verify: list[str] | None,
               files: list[str] | None, context: list[str] | None, context_files: list[str] | None) -> list[str]:
    """Cheap, deterministic checks for briefs that tend to produce bad delegations."""
    warnings = []
    words = len(task.split())
    write = kind in ("implement", "fix", "debug", "refactor", "test", "docs", "chore")
    if write and words < 8:
        warnings.append("brief is very short: say what done looks like and where the work happens")
    if write and not criteria and words < 40:
        warnings.append("no --done criteria: kind defaults will be used")
    if write and not verify:
        warnings.append("no --verify command: cic cannot independently confirm the result")
    if _VAGUE_REF.search(task) and not (files or context or context_files):
        warnings.append("vague reference (e.g. 'the bug'): add --file, --context, or the exact error text")
    asks = len(re.findall(r"(?:^|\n)\s*(?:\d+[.)]|[-*])\s+", task)) + task.lower().count(" and also ")
    if asks >= 6:
        warnings.append("many separate asks in one brief: consider splitting into separate jobs")
    if _SECRET.search(task) or any(_SECRET.search(c) for c in (context or [])):
        warnings.append("brief appears to contain a secret token: remove it before delegating")
    return warnings
