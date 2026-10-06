---
name: claude-council
description: "Ask Claude, Codex, and Gemini the same question in parallel; a moderator reconciles the answers with repository evidence. Use for high-stakes decisions, architecture or library choices, or multi-model opinions. Read-only."
metadata:
  short-description: Parallel multi-model panel with a moderator
---

# Multi-model council

```
cic council "<question>" --cwd <repo> --members claude:sonnet,codex,gemini --synth claude:opus
```
Call `cic` as a single plain command. Defaults come from config: members `claude:sonnet,codex,gemini`, moderator `claude:opus`.

## How it works
- Every member gets the same grounded prompt and answers independently, read-only, in the shape ANSWER / REASONS / RISKS / CONFIDENCE. This is self-consistency across model families.
- The moderator weighs evidence, not votes. It checks contested repository facts itself, then reports the final answer, the consensus, the disagreements with how each was resolved, its confidence, and the residual risk.
- Unavailable members are skipped and listed with the reason; the council still runs. A member can be unavailable because its CLI isn't installed or isn't logged in. For example, Gemini CLI's free Code Assist login is no longer accepted; setting `GEMINI_API_KEY` is the likely fix.
- Use `--synth none` to get the raw answers without a moderator.
- Same-model self-consistency: repeat a member, e.g. `--members claude:sonnet,claude:sonnet,claude:sonnet`. Each sample reasons independently, and the moderator only trusts agreement backed by cited evidence.

## Asking well
- Frame the question with explicit options and decision criteria, e.g. "Postgres LISTEN/NOTIFY vs Redis streams vs SQS for job fan-out; criteria: ops burden, ordering, at-least-once, cost at 50 msg/s".
- Give the relevant files with `--file` and key constraints with `--context`.
- Keep it to one question. Split compound questions into separate councils.

## Presenting the result
Lead with the moderator's recommendation, then the disagreements and how they were resolved, then the members that answered and any that were unavailable. Treat a split council with low confidence as a decision for the user, not a conclusion.

Exit 3 means it's still running: `cic wait <job> --timeout 300`. The full transcript is in `cic bus log council-<job>`.
