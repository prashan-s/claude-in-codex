---
name: claude-in-codex
description: "Use Claude Code from Codex: delegate coding with verified results, review code, hold persistent sessions, steer jobs, engineer prompts, pair program, run multi-model councils, exchange agent messages, and set up cic. Select the relevant workflow and load it on demand."
---

# Claude in Codex

Use this index to select the workflow for the user's request. Read only the selected
workflow and the supporting references it requires; do not load every file at startup.
All paths below are relative to this skill directory, regardless of the working repository.

| User intent | Read |
|---|---|
| Implement, fix, debug, refactor, test, or document with Claude | [Delegate](references/delegate.md) |
| Get a read-only code review or second opinion | [Review](references/review.md) |
| Talk with Claude across multiple turns | [Session](references/session.md) |
| Check progress, wait, steer, switch models, cancel, or resume a job | [Jobs](references/jobs.md) |
| Improve a brief or choose prompting techniques | [Prompting](references/prompting.md) |
| Implement with a driver and independent reviewer | [Pair](references/pair.md) |
| Ask several models and reconcile their answers | [Council](references/council.md) |
| Exchange messages or run agents on the local bus | [Agent bus](references/agent-bus.md) |
| Install cic or diagnose auth, PATH, rules, or permission failures | [Setup](references/setup.md) |

Explicit workflow names select the matching row, for example `$claude-in-codex review`
or `$claude-in-codex delegate`. For a plain-language request, infer the matching workflow.
If a task crosses workflows, load the additional reference when that step is needed.
The former `$claude-delegate`, `$claude-review`, and other standalone entries are now
workflow names under this single skill. The `cic` CLI commands remain the same.

## Shared execution rules

- Requires macOS or Linux, Python 3.10+, the `cic` CLI, and a logged-in Claude Code.
  Installing this skill alone does not install the CLI; use the setup workflow when needed.
- Call `cic` as a single plain command. Use `--cwd` to select a repository, without
  shell chains, pipes, redirects, or command substitution.
- Reviews and questions are read-only. Follow the user's authorized scope for changes.
  Git commits and pushes remain blocked in delegated jobs unless explicitly allowed.
- Treat provider completion reports as claims. Report independent verification and
  unresolved failures accurately; do not claim checks that were not run.
- For skills CLI installation, ask the user whether to install into the current project
  or globally before running it. Project scope omits `-g`; global scope includes `-g`.
  Do not infer the user's choice from a non-interactive default.

## Supporting references

Load these only when a selected workflow needs them:
[Model routing](references/model-routing.md),
[Task recipes](references/task-recipes.md),
[Prompt techniques](references/techniques.md),
[Context engineering](references/context-engineering.md),
[Brief blocks](references/brief-blocks.md),
[Prompt antipatterns](references/antipatterns.md),
[Bus protocol](references/protocol.md).
