"""Delegation contracts, briefs, and follow-up messages.

Two layers, kept separate on purpose:

* The *contract* is appended to Claude Code's system prompt. It is static text
  per job family so the prompt cache is reused across jobs, and Claude Code
  records it on the first request, so it survives --resume.
* The *brief* is the user message. It carries the four prompt elements
  (instruction, context, input data, output indicator) plus a technique block
  chosen per task kind.

Every template applies techniques from https://www.promptingguide.ai/ ; the
mapping lives in ``TECHNIQUES`` and is printed by ``cic run --dry-run``.
"""

from __future__ import annotations

import re
from pathlib import Path

from .util import git_info, run, today

# ----------------------------------------------------------------- contracts

CONTRACT_WORK = """\
# Delegated task protocol

You are running headless as a delegated engineer. An orchestrating agent (usually Codex) assigned this task and will read your final structured report. No human is watching this session, and nobody can answer questions until you finish.

## How to work
- Investigate before editing. Read the code you will touch, find the existing patterns, helpers, and tests to reuse, and confirm assumptions with tools rather than guessing.
- Make the smallest change that fully solves the task, in the style of the surrounding code. Keep the diff focused on the task: unrelated refactors, renames, and formatting churn make the orchestrator's review harder.
- Fix root causes rather than symptoms. Keep tests honest: a test that exposes a real bug is a finding to report, never something to weaken, skip, or delete.
- Verify your work by running the most relevant tests, build, or lint commands. If verification cannot run (denied permission, missing tooling), say so plainly instead of implying success.
- For counting, arithmetic, dates, or data processing, write and run a small script rather than estimating.
- When something is ambiguous, take the most reasonable low-risk interpretation, record it under assumptions, and keep going. Stop early only when a missing decision would change correctness, security, or an irreversible action; then finish with status "needs_input" and precise questions.
- When the orchestrator sends back failed checks or review findings, start by reflecting in two sentences: what in your previous attempt caused the failure, and what you will do differently. Carry those lessons through the rest of the task.
- Leave all changes uncommitted in the working tree; the orchestrator reviews and commits. Commit, push, publish, deploy, or delete data only when the task explicitly asks.
- Keep side effects inside the working directory: the orchestrator's machine is shared. Project-local setup (a virtualenv or node_modules inside the repo) is fine when the task needs it; global or user-wide installs, shell-profile edits, and system settings are not. If a required tool is missing, finish with status "blocked" and name the exact command that would provide it.
- Do the work yourself rather than handing it to another agent or CLI (Codex, Gemini, another Claude).
- Keep going until the task is complete or you are genuinely blocked. A plan or a partial fix is not a finished task.
- A user message that arrives mid-task is steering from the orchestrator. Fold it into the work.

## Final report
Finish with the structured report. Be factual and specific: every file you changed, every verification command you ran with its real outcome, and anything left undone. Status meanings:
- done: every acceptance criterion is met and verified (or verification was impossible and you said why)
- partial: some criteria remain; list them in next_steps
- needs_input: only the orchestrator can make a required decision; list the questions
- blocked: an external obstacle such as missing permissions, credentials, or a broken environment
- failed: no meaningful progress was possible
Confidence anchors: 0.9 or above means every criterion was verified by a command you ran and saw pass; 0.7 to 0.89 means verified, but one edge case or path was not exercised; 0.5 to 0.69 means at least one criterion was inferred rather than run; below 0.5 means the work is partial. Whenever you are below 0.9, name the unverified item in risks.
"""

CONTRACT_READ = """\
# Delegated analysis protocol

You are running headless for an orchestrating agent (usually Codex) that will read your final answer. No human is watching, and nobody can answer questions until you finish.

- Work read-only: inspect files and run read-only commands; leave every file and all state unchanged.
- Ground every claim in what you actually inspected: cite file paths with line numbers, commands you ran, or sources you read. Label inferences as inferences.
- For counting, arithmetic, or data questions, compute the answer with a small read-only script rather than estimating.
- Prefer one well-supported conclusion over many weak ones. When evidence is missing, say exactly what is unknown.
- Do the work yourself rather than handing it to another agent or CLI.
- Lead with the answer and keep the rest compact and structured. The orchestrator pays for every token it reads.
"""

CONTRACT_CHAT = """\
# Conversation protocol

You are in a multi-turn working conversation with another AI agent (usually Codex) that is coordinating work for its user, sometimes relaying the user's words. Each message is one turn of the dialogue and a genuine request from that orchestrator: treat it as you would a message from the user. Earlier turns are shared context you can rely on.

- Answer directly and concisely; lead with the answer, then the essential reasoning.
- Ground claims in the repository when relevant: cite file paths with line numbers.
- You may ask clarifying questions when a decision genuinely needs them.
- Change files only when a message explicitly asks you to; otherwise discuss, analyze, and propose.
- Do the work yourself unless a message asks you to involve another agent.
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
    elif kind in ("review", "research", "plan", "explain", "ask", "improve"):
        text = CONTRACT_READ
    else:
        text = CONTRACT_WORK
    if role:
        text += f"\n## Your role\n{role.strip()}\n"
    return text


# ----------------------------------------------------------------- techniques
# promptingguide.ai technique -> how each task kind applies it. Printed by
# `cic run --dry-run`, documented in docs/prompt-audit.md, checked by tests.

TECHNIQUES: dict[str, list[tuple[str, str]]] = {
    "implement": [
        ("generated knowledge", "list and confirm the facts the change depends on before editing"),
        ("chain-of-thought", "five-line plan: files to touch and how each is verified"),
        ("tree of thoughts", "compare two designs in one sentence each when the choice is hard to reverse"),
        ("ReAct", "act with tools, observe results, iterate until checks pass"),
        ("reflexion", "self-review of the diff; failed checks come back with a reflection step"),
    ],
    "fix": [
        ("ReAct", "reproduce first, then observe -> act -> verify"),
        ("chain-of-thought", "state the root cause in one sentence before editing"),
        ("tree of thoughts", "keep 2-3 candidate causes when the first does not hold"),
        ("reflexion", "regression test plus re-verification"),
    ],
    "debug": [
        ("ReAct", "observe -> hypothesize -> experiment loop"),
        ("tree of thoughts", "rank hypotheses, prune by evidence"),
        ("PAL", "probe scripts instead of guessing"),
        ("chain-of-thought", "separate confirmed facts from inferences"),
    ],
    "refactor": [
        ("generated knowledge", "write down the invariants that must not change"),
        ("ReAct", "characterization tests, then small verified steps"),
    ],
    "test": [
        ("generated knowledge", "enumerate behaviors and edge cases first"),
        ("reflexion", "confirm each test can fail for the right reason"),
    ],
    "docs": [
        ("generated knowledge", "read the code before describing it"),
        ("PAL", "run every documented command and snippet; grep every named path and flag"),
        ("prompt elements", "audience and output shape stated"),
    ],
    "chore": [
        ("few-shot", "repository commit or changelog examples when the task is about messages"),
        ("zero-shot", "exact mechanical change"),
    ],
    "research": [
        ("prompt chaining", "extract evidence first, then answer only from it"),
        ("tree of thoughts", "compare options against criteria, one trade-off bullet per option"),
        ("prompt elements", "fixed output shape: recommendation, evidence, trade-offs, open questions"),
        ("grounding", "uncited claims are marked (unverified)"),
    ],
    "plan": [
        ("tree of thoughts", "2-3 options, viability rating, prune, choose"),
        ("prompt chaining", "plan feeds a fresh execution run (--plan)"),
    ],
    "explain": [
        ("prompt elements", "answer-first output shape with a word budget"),
        ("few-shot", "one format example of answer plus cited bullets"),
        ("PAL", "scripts for counting or data questions"),
    ],
    "ask": [
        ("prompt elements", "answer-first output shape with a word budget"),
        ("few-shot", "one format example of answer plus cited bullets"),
        ("PAL", "scripts for counting or data questions"),
    ],
    "review": [
        ("chain-of-thought", "trace input -> path -> wrong outcome for every finding"),
        ("self-refutation", "try to disprove each finding (guards, callers, tests) before keeping it"),
        ("ReAct", "read surrounding code and tests before judging"),
        ("prompt elements", "schema-enforced findings with severity and confidence"),
    ],
}
CROSS_CUTTING = [
    ("meta prompting", "every brief uses the same XML structure: task, context, criteria, verification, approach"),
    ("reflexion", "cic re-runs --verify; failures return to the same session with a reflection step"),
    ("active-prompt", "a report below the confidence threshold triggers one targeted uncertainty pass"),
    ("self-consistency", "cic council (several models or several samples, then a moderator)"),
    ("APE", "cic improve drafts two rewrites, scores them on a rubric, and returns the winner"),
    ("calibration", "confidence anchors tie the reported number to what was actually verified"),
]


def techniques_for(kind: str, *, hints: bool = False, examples: bool = False, images: bool = False,
                   plan: bool = False) -> list[tuple[str, str]]:
    applied = list(TECHNIQUES.get(kind, []))
    if hints:
        applied.append(("directional stimulus", "orchestrator hints, labeled as unverified"))
    if examples:
        applied.append(("few-shot", "examples that fix format and style, not content"))
    if images:
        applied.append(("multimodal CoT", "describe what the images show, then act on that rationale"))
    if plan:
        applied.append(("prompt chaining", "opus plan -> fresh execution run"))
    return applied


APPROACH = {
    "implement": """\
1. Orient (generated knowledge): read the code this change touches. Write down the three to five facts your change depends on (APIs, invariants, callers, existing tests) and confirm each one in the code before relying on it.
2. Plan in at most five lines: the files to touch and how you will verify each. If two designs are plausible and the choice is hard to reverse, compare them in one sentence each, pick one, and record the choice under assumptions. Then implement the smallest complete change, reusing the patterns you found.
3. Prove it: add or update tests for the new behavior, run the verification commands, and iterate until they pass.
4. Re-read your diff as a strict reviewer would: edge cases, error handling, naming, leftover debug code.""",
    "fix": """\
1. Reproduce first: find or write the smallest failing test or command that shows the bug. If it will not reproduce, say what you tried.
2. Trace the failing path and state the root cause in one sentence before editing. If the evidence does not support your first candidate, keep two or three candidates and test the cheapest one next.
3. Fix it at the root with the smallest safe change; keep behavior outside the failing path unchanged.
4. Confirm the reproduction now passes, add a regression test if none exists, then run the broader verification.""",
    "debug": """\
Investigate in an observe -> hypothesize -> experiment loop:
1. Observe: collect the exact error text, logs, recent changes (git log / git diff), and the code path involved.
2. Hypothesize: list plausible causes, ranked by likelihood and by how cheaply each can be checked.
3. Experiment: run the cheapest check that discriminates between the top hypotheses (targeted logging, a probe script, a minimal test, narrowing inputs). Update the ranking from what you observe; never assert a cause you have not confirmed.
4. {finish}
In the summary, separate confirmed facts from inferences.""",
    "refactor": """\
1. Write down the invariants that must not change: public behavior, return values, error types, side effects.
2. Build a safety net: run the existing tests for the affected area; if coverage is thin, add characterization tests that pin current behavior.
3. Refactor in small, behavior-preserving steps, keeping public interfaces stable unless the task says otherwise.
4. Re-run the tests: behavior must be identical. Call out any intentional behavior change explicitly.""",
    "test": """\
1. Enumerate the behaviors that matter before writing code: happy path, boundaries, invalid input, error paths, and time or concurrency where relevant. Follow the project's existing test framework and style.
2. Test observable behavior rather than implementation details. Keep tests deterministic: no real network, fixed seeds and clocks.
3. Make sure each new test can fail for the right reason: state what breakage it catches (or briefly check it against the broken behavior).
4. Run the new tests and the surrounding suite. If a new test fails because of a real product bug, report it as a finding instead of bending the test.""",
    "docs": """\
Read the code before you describe it, and ground every statement in what you read. Write for the stated audience (default: a developer new to this code): lead with what the reader needs to do, keep examples runnable, and match the existing documentation's tone and format. Run every command and snippet you document, and confirm with grep that every path, flag, and function name you mention exists. Fix or remove anything that fails.""",
    "chore": """\
Make exactly the mechanical change requested, nothing more, then run a quick check (build, lint, or the tests touching the change).""",
    "research": """\
Work in two steps:
1. Evidence: survey the realistic options breadth-first and collect the evidence that bears on the question: file paths with line numbers, short quotes, documentation URLs. Go deep only where evidence would change the recommendation.
2. Answer: compare the options against the stated criteria and answer using only that evidence.""",
    "plan": """\
Explore the relevant code first. Then generate two or three materially different approaches. Rate each against the acceptance criteria (correctness, risk, effort, reversibility) as strong, possible, or ruled out, prune the ruled-out ones, and choose one with a clear rationale. Produce ordered steps where each step names its files and how to verify it.""",
    "explain": """\
Answer from the code, citing file paths with line numbers. For counting or data questions, compute with a small script instead of estimating. Say plainly when something is uncertain.""",
    "ask": """\
Answer from what you read, citing files where relevant. For counting or data questions, compute with a small script instead of estimating. Say plainly when something is uncertain.""",
}

# Output indicators for free-text kinds (structured kinds use a JSON schema).
_ANSWER_SHAPE = (
    "Lead with a one-to-three sentence answer. Then add up to five bullets of supporting evidence with file:line "
    "references. Stay under 250 words unless the question asks for more.\n"
    "Format example:\n"
    "Retries are capped at 3 (src/net.py:42).\n"
    "- Backoff doubles from 1s (src/net.py:51).\n"
    "- Covered by tests/test_net.py:18."
)
OUTPUT_SHAPE = {
    "explain": _ANSWER_SHAPE,
    "ask": _ANSWER_SHAPE,
    "research": (
        "Use these sections: Recommendation (two sentences), Evidence (bullets with sources), Trade-offs, "
        "Open questions. Stay under 500 words.\n"
        "Under Trade-offs, write one bullet per option: \"Option: strength / weakness / when to pick it\". "
        "Mark any claim without a cited source as (unverified)."
    ),
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
_MESSAGE_TASK = re.compile(r"\bcommit message|\bchangelog|\brelease notes?\b|\bPR (title|description)\b", re.I)


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


def repo_message_examples(cwd: str, limit: int = 12) -> list[str]:
    """Recent commit subjects: few-shot style examples for message-writing chores."""
    code, out, _ = run(["git", "log", f"-n{limit}", "--format=%s"], cwd=cwd, timeout=10)
    if code != 0:
        return []
    return [line.strip() for line in out.splitlines() if line.strip()]


def wants_message_examples(task: str, kind: str) -> bool:
    return kind in ("chore", "docs") and bool(_MESSAGE_TASK.search(task))


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
    hints: list[str] | None = None,
    examples: list[str] | None = None,
    image_count: int = 0,
) -> str:
    """Assemble the user message for a delegated task."""
    parts = [f"<task>\n{task.strip()}\n</task>"]
    parts.append("<context>\n" + _context_block(cwd, files or [], context or [], context_files or []) + "\n</context>")

    if image_count:
        parts.append(
            f"<images>\n{image_count} image(s) are attached. First describe, in a few lines, what they show that matters "
            "for this task (UI state, error text, layout). Then use that description as evidence for the work.\n</images>"
        )

    if hints:
        parts.append("<hints>\nHints from the orchestrator. They are likely but unverified: confirm each one before relying on it.\n"
                     + "\n".join(f"- {h.strip()}" for h in hints) + "\n</hints>")

    if examples:
        blocks = "\n\n".join(f"<example>\n{e.strip()}\n</example>" for e in examples)
        parts.append("<examples>\nMatch the format and style of these examples, not their content.\n" + blocks + "\n</examples>")

    if plan:
        parts.append("<plan>\nFollow this reviewed plan. Deviate only if you find it is wrong, and say why in the report.\n"
                     + render_plan(plan) + "\n</plan>")

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
        cons.append("Read-only: leave every file unchanged.")
    if cons:
        parts.append("<constraints>\n" + "\n".join(f"- {c}" for c in cons) + "\n</constraints>")

    approach = APPROACH.get(kind)
    if approach:
        if kind == "debug":
            finish = (
                "Conclude: stop at a confirmed root cause and describe the smallest safe fix without editing files."
                if read_only
                else "Conclude: once the cause is confirmed, fix it with the smallest root-cause change and verify."
            )
            approach = approach.format(finish=finish)
        parts.append(f"<approach>\n{approach}\n</approach>")

    shape = OUTPUT_SHAPE.get(kind)
    if shape:
        parts.append(f"<output>\n{shape}\n</output>")
    return "\n\n".join(parts) + "\n"


def chat_opening(message: str, *, cwd: str) -> str:
    """First turn of a conversation: shared context once, then the message itself."""
    return f"<context>\n{_context_block(cwd, [], [], [])}\n</context>\n\n{message.strip()}\n"


def build_plan_brief(task: str, *, cwd: str, files: list[str] | None, context: list[str] | None,
                     context_files: list[str] | None, criteria: list[str] | None, verify: list[str] | None,
                     constraints: list[str] | None, hints: list[str] | None = None) -> str:
    brief = build_brief(task, kind="plan", cwd=cwd, files=files, context=context, context_files=context_files,
                        criteria=criteria, verify=None, constraints=constraints, read_only=True, hints=hints)
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


# ----------------------------------------------------------------- follow-ups (reflexion, active-prompt)

_REFLECT = ("Begin with a two-sentence reflection: what in your previous attempt led to this result, and what you "
            "will do differently. Name the failing check or open item and your hypothesis for it. Recall the approaches "
            "you already tried in this session and do not repeat one that failed. If a check also fails without your "
            "change (for example, it failed before you started), report it as pre-existing instead of editing unrelated "
            "code. Then act on it.")


_REPAIR_BUDGET = 6000  # characters of check output per repair turn, across all failing checks


def verification_failed_message(results: list[dict], attempt: int, max_attempts: int) -> str:
    failing = [item for item in results if not item["ok"]]
    share = max(800, _REPAIR_BUDGET // max(1, len(failing)))
    blocks = []
    for item in failing:
        output = item["output_tail"]
        if len(output) > share:
            output = "…[earlier output trimmed]…\n" + output[-share:]
        blocks.append(
            f"<check command=\"{item['command']}\" exit_code=\"{item['exit_code']}\">\n{output}\n</check>"
        )
    return (
        "<verification_failed>\n"
        "The orchestrator re-ran the required checks after your report, and some failed:\n\n"
        + "\n\n".join(blocks)
        + "\n</verification_failed>\n\n"
        f"This is repair attempt {attempt} of {max_attempts - 1}. {_REFLECT} Diagnose why each check fails, fix the "
        "root cause (not the test), re-run the checks yourself until they pass, then send an updated structured report."
    )


def continue_message(report: dict | None) -> str:
    remaining = ""
    if report and report.get("next_steps"):
        remaining = "\nRemaining items from your report:\n" + "\n".join(f"- {s}" for s in report["next_steps"])
    return (
        "<continue>\nThe task is not finished yet. Keep working until every acceptance criterion is met and verified."
        f"{remaining}\n{_REFLECT} If you are truly blocked, explain exactly why. Finish with an updated structured "
        "report.\n</continue>"
    )


def uncertainty_message(report: dict, threshold: float) -> str:
    """Active-prompt: spend extra effort exactly where the agent says it is unsure."""
    known = report.get("risks") or []
    listed = ("\nRisks you already listed:\n" + "\n".join(f"- {r}" for r in known)) if known else ""
    return (
        f"<uncertainty_check>\nYou reported confidence {report.get('confidence')}, below the {threshold} bar for "
        f"accepting this work.{listed}\nName the specific things you are unsure about. Resolve each one with tools: "
        "read the relevant code, run a targeted test or script, or check an edge case. Fix anything you find wrong. "
        "Then send an updated structured report. Any uncertainty you cannot resolve goes in open_questions or risks, "
        "with the confidence adjusted to match.\n</uncertainty_check>"
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


# ----------------------------------------------------------------- APE: improve a brief before delegating

def build_improve_prompt(task: str, *, kind: str, cwd: str) -> str:
    return f"""<role>
You are a prompt engineer improving a delegation brief before it is sent to a coding agent (Claude Code) that runs headless with no one to ask. A weak brief yields a plausible but wrong result; your rewrite should make the result checkable.
</role>

<brief kind="{kind}">
{task.strip()}
</brief>

<context>
Working directory: {cwd}
Today: {today()}
Inspect the repository (read-only) to make the brief concrete: real file paths, the project's actual test or build commands, existing patterns.
</context>

<principles>
These come from https://www.promptingguide.ai/ :
- Prompt elements: a clear instruction, the context the agent cannot discover, the input data (exact error text, failing test), and the output indicator (what done looks like).
- Specificity: state the observable outcome and acceptance criteria rather than vague goals.
- Directive framing: say what to do, not only what to avoid.
- Grounding (generated knowledge): name the files and facts the work depends on.
- Verification (reflexion): propose check commands that really run in this repository.
- Chaining: if the brief bundles unrelated asks, keep the first and list the rest as follow-ups.
- Hints (directional stimulus): add likely leads you found, phrased as unverified hints.
</principles>

<instructions>
1. Diagnose the brief's problems against those principles.
2. Draft two candidate rewrites with different emphasis. Score each from 0 to 2 on four tests: observable outcome, named real files, a verify command that runs, and single scope. Return the higher-scoring one.
3. Keep the user's intent and scope. List acceptance criteria you inferred, rather than read in the brief, with the prefix "(proposed)".
4. Every verify command must be one you confirmed exists, such as a script in package.json or a test runner the project uses.

Example of the transformation:
- Weak: "fix the login bug"
- Strong: "Login returns 500 when the email contains '+' (reproduced by tests/test_auth.py::test_plus_email). Done when that test passes and `pytest tests/test_auth.py` is green."

Return the structured result.
</instructions>
"""


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
        "- Before reporting a finding, walk it through step by step: the triggering input or state, the exact code path, "
        "and the wrong outcome. Drop candidates that do not survive this trace.\n"
        "- Then try to refute each surviving finding: look for a guard, caller check, test, or config that prevents it. "
        "Keep it only if the refutation fails, and say in the body what you checked.\n"
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
Report only material findings an engineer would act on: correctness, security, data integrity, reliability, performance regressions, broken contracts, missing tests for risky behavior. Leave out style, naming, and formatting. Each finding names the file and line range, says what goes wrong, why this code path is vulnerable, the likely impact, and a concrete fix.
</finding_bar>

<grounding>
Every finding must be defensible from code you inspected. Never invent files, lines, or runtime behavior. If a conclusion rests on an inference, say so in the body and lower its confidence.
</grounding>

<calibration>
Prefer one strong finding over several weak ones. Use verdict "approve" when you cannot support a material finding, and write the summary as a terse ship / no-ship call. This review is read-only: leave files unchanged.
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
You are one member of a panel of independent AI agents answering the same question; a moderator will compare the answers. Reason independently, and consider at least one serious alternative before you commit. Ground claims about the repository in files you actually read (cite path:line), and leave everything unchanged.

Answer in this shape, in under 350 words:
ANSWER: the direct answer or recommendation
REASONS: the 2-5 strongest reasons, with evidence
ALTERNATIVE: the strongest competing answer and why you rejected it
RISKS: what would make this answer wrong, including the single observation that would change your answer
CONFIDENCE: a number from 0 to 1
</instructions>
"""


_PANEL_ANSWER_LIMIT = 3500  # members are asked for under 350 words; this caps runaway answers


def council_synth_prompt(question: str, answers: list[tuple[str, str]], unavailable: list[tuple[str, str]]) -> str:
    def clip(text: str) -> str:
        text = text.strip()
        return text if len(text) <= _PANEL_ANSWER_LIMIT else text[:_PANEL_ANSWER_LIMIT] + "\n…[trimmed]"

    panel = "\n\n".join(f'<answer agent="{name}">\n{clip(text)}\n</answer>' for name, text in answers)
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
You are the moderator. Weigh evidence, not votes. Where the answers conflict on a checkable fact about the repository, check it yourself (read-only) and say who was right. Where the evidence is balanced, prefer the answer most members converged on (self-consistency), but only when at least two of them cite independent evidence. If the agreement is uncited, say so and lower your confidence. Produce, in under 450 words:
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
Trace each acceptance criterion to the code and test that satisfy it. A criterion with no supporting evidence in the change is a finding. Read surrounding code as needed (read-only). Report only material problems: unmet requirements, correctness bugs, regressions, security issues, missing tests for new behavior. Approve when the work meets the acceptance criteria and you cannot support a material finding; never withhold approval over style.
</instructions>
"""


def findings_for_driver(navigator: str, round_no: int, report: dict | None, fallback_text: str) -> str:
    if not report:
        return (f"The navigator ({navigator}) reviewed round {round_no}:\n{fallback_text.strip()}\n\n"
                f"{_REFLECT} Address the issues raised, re-run the checks, and report again.")
    lines = [f"The navigator ({navigator}) reviewed round {round_no} and requested changes: {report.get('summary', '').strip()}"]
    for index, finding in enumerate(report.get("findings") or [], 1):
        where = finding.get("file") or "?"
        if finding.get("line_start"):
            where += f":{finding['line_start']}"
        lines.append(f"{index}. [{str(finding.get('severity', '?')).upper()}] {finding.get('title')} ({where}): "
                     f"{finding.get('body', '').strip()} Fix: {finding.get('recommendation', '').strip()}")
    lines.append(f"\n{_REFLECT} Address every finding, or explain in your report why one is invalid. Then re-run the "
                 "checks and send an updated report.")
    return "\n".join(lines)


# ----------------------------------------------------------------- lint

_VAGUE_REF = re.compile(r"\b(this|that|the) (bug|issue|error|problem|thing|file|function)\b", re.I)
_SECRET = re.compile(r"(sk-[A-Za-z0-9_-]{16,}|AKIA[0-9A-Z]{16}|ghp_[A-Za-z0-9]{20,}|xox[bp]-[A-Za-z0-9-]{10,})")


def lint_brief(task: str, *, kind: str, criteria: list[str] | None, verify: list[str] | None,
               files: list[str] | None, context: list[str] | None, context_files: list[str] | None,
               tier: str | None = None, plan: bool = False) -> list[str]:
    """Cheap, deterministic checks for briefs that tend to produce bad delegations."""
    warnings = []
    words = len(task.split())
    write = kind in ("implement", "fix", "debug", "refactor", "test", "docs", "chore")
    if write and words < 8:
        warnings.append("brief is very short: say what done looks like and where the work happens (or run `cic improve`)")
    if write and not criteria and words < 40:
        warnings.append("no --done criteria: kind defaults will be used")
    if write and not verify:
        warnings.append("no --verify command: cic cannot independently confirm the result")
    if _VAGUE_REF.search(task) and not (files or context or context_files):
        warnings.append("vague reference (e.g. 'the bug'): add --file, --context, or the exact error text")
    asks = len(re.findall(r"(?:^|\n)\s*(?:\d+[.)]|[-*])\s+", task)) + task.lower().count(" and also ")
    if asks >= 6:
        warnings.append("many separate asks in one brief: consider splitting into separate jobs (prompt chaining)")
    if write and tier == "opus" and not plan and kind in ("implement", "refactor"):
        warnings.append("large or risky change routed to opus: consider --plan (opus plans, a fresh run executes)")
    if _SECRET.search(task) or any(_SECRET.search(c) for c in (context or [])):
        warnings.append("brief appears to contain a secret token: remove it before delegating")
    return warnings
