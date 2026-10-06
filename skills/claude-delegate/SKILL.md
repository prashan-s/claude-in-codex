---
name: claude-delegate
description: Delegate a coding task (implement, fix, debug, refactor, write tests or docs) to Claude Code through the cic CLI, with automatic Haiku/Sonnet/Opus routing, independent verification, and repair retries on the same Claude session. Use when the user wants Claude to do or finish a piece of work in a repository. Not for code review (claude-review), back-and-forth conversation (claude-session), or checking on jobs that are already running (claude-jobs).
metadata:
  short-description: Hand a coding task to Claude Code, get a verified result
---

# Delegate a task to Claude Code

`cic run` starts headless Claude Code with a delegation contract, routes the task to the cheapest model that fits, waits, re-runs your checks itself, and sends failures back to the same Claude session until they pass, escalating the model only after repeated failure. You get one compact report.

## Invocation rules
- Call `cic` as a single plain command: no `cd … &&`, pipes, redirects, or `$(…)`. The Codex exec-policy rule only matches a bare `cic …` command, and Claude cannot read its login inside the sandbox. Pick the directory with `--cwd <repo>`.
- Exit codes: 0 done · 4 needs attention (partial / needs_input / blocked) · 1 failed · 3 still running · 5 delegation depth limit (you are already a delegated agent: do the work yourself) · 6 sandboxed or 127 not found (use `$claude-setup`).

## Workflow
1. Write the brief (below). For anything beyond a one-liner, apply `$claude-prompting`.
2. Run it:
   ```
   cic run "<brief>" --cwd <repo> --verify "<check that must pass>" --done "<criterion>" --file <start-here>
   ```
   It blocks for up to about 9 minutes. Exit 3 means still running: poll with `cic wait <job> --timeout 300` until it finishes. Start long tasks with `--background` and poll the same way.
3. Read the report. The "Checks re-run by cic" section is ground truth; "Checks Claude reports running" are claims.
4. Act on the status:
   - **DONE ✓ verified**: inspect `git diff`, then continue.
   - **DONE (not independently verified)**: no `--verify` was given. Inspect the diff or run checks yourself before you rely on it.
   - **NEEDS INPUT**: answer with `cic reply <job> "<answers>"`.
   - **PARTIAL / FAILED**: `cic reply <job> "<specific guidance>"`, or re-run with a sharper brief or `--model opus`.
   - **BLOCKED**: fix the named cause, then reply. For permissions use `--access auto` or `--allow 'Bash(<cmd> *)'`. For a check that cannot run, fix the `--verify` command.
5. Tell the user what Claude changed and how it was verified. Never present unverified claims as verified.

## Writing the brief
Describe the outcome, where it happens, and how to prove it:
- **Task text**: what must be true when done. When fixing something, include the exact error text or failing test.
- **`--file`**: the 1–5 files Claude should start from. Pointers beat pasted code.
- **`--done`**: acceptance criteria, one per flag.
- **`--verify`**: commands that must pass *in this environment*. Use the project's runner, e.g. `uv run pytest -q` or `npm test --silent`. cic runs these itself after Claude reports done.
- **`--constraint`**: real limits, such as "public API unchanged" or "no new dependencies".

Preview with `--dry-run`. It shows the route, permissions, contract, and final brief, and runs nothing.

## Model routing
Routing is automatic:
- **Haiku**: mechanical edits and lookups.
- **Sonnet**: ordinary features, fixes, tests, and refactors.
- **Opus**: architecture, concurrency, security, ambiguous root causes, and large multi-module changes.

Override only with a reason:
- `--tier fast|balanced|deep` or `--model haiku|sonnet|opus`; `--effort low|medium|high|xhigh|max` to tune.
- `--plan` for large or risky changes. Opus writes a read-only plan, then a fresh run executes it.
- `cic route "<brief>"` explains the decision.

Fable is never picked automatically. See [references/model-routing.md](references/model-routing.md).

## Permissions
- Write tasks run in Claude Code's `auto` mode, where a safety classifier approves routine commands. Haiku runs use an allowlist profile instead (`edit`).
- Questions run read-only.
- `git commit` and `git push` are denied unless you pass `--allow-git-write`.
- Use `--access full` only when the user explicitly accepts unrestricted execution.

## More
- Per-task flags and examples: [references/task-recipes.md](references/task-recipes.md)
- Several independent tasks at once: start one `cic run --background --worktree <name>` per task, then `cic wait` each job.
