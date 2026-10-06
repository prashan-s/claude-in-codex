---
name: claude-pair
description: Run an implement-and-review loop between two agents, where a driver (default Claude Sonnet) makes the change and a navigator (default Claude Opus, or Codex or Gemini) reviews the real diff, repeating until the navigator approves or the rounds run out. Use when the user wants pair programming, a built-in reviewer, or a cross-checked implementation of a risky change, including Claude-to-Claude and Claude-to-Codex pairing.
metadata:
  short-description: Driver/navigator loop between two agents
---

# Pair programming between agents

```
cic pair "<task>" --cwd <repo> --verify "<check>" --done "<criterion>" --driver claude:sonnet --navigator claude:opus --rounds 3
```
Call `cic` as a single plain command.

## What happens
1. The driver implements the task with the full delegation contract. Its `--verify` checks are re-run by cic, with up to 2 repair attempts per round.
2. cic collects the actual working-tree diff, not the driver's description of it.
3. The navigator reviews the diff against the task and acceptance criteria, read-only, and returns a structured verdict with findings.
4. If the verdict is `needs-attention`, the findings go back to the driver on the same session, and the next round starts. If it is `approve`, the loop stops.
5. Each agent keeps its own session across rounds. The navigator checks whether its previous findings were resolved.

## Choosing the pair
| Pairing | Flags | When |
|---|---|---|
| Claude ↔ Claude (default) | `--driver claude:sonnet --navigator claude:opus` | Most risky changes; Opus catches what Sonnet misses |
| Claude implements, Codex reviews | `--navigator codex` | Independent model family as reviewer (cross-vendor check) |
| Codex implements, Claude reviews | `--driver codex --navigator claude:opus` | Codex writes in a workspace-write sandbox; Claude Opus reviews |
| Cheap loop | `--driver claude:haiku --navigator claude:sonnet` | Mechanical changes that still deserve a second look |

Gemini can be the navigator (`--navigator gemini`) when its CLI is logged in. If it is unavailable, the loop stops and reports why.

## Reading the result
- Status `DONE` means the navigator approved and the driver's last report was done. `PARTIAL` means rounds ran out with open findings, which are listed in the last review.
- The rounds table links each driver and navigator job. Use `cic result <job>` for any of them.
- The full transcript is in `cic bus log pair-<job>`.
- Exit 3 means it's still running: `cic wait <job> --timeout 300`.

## Cost and when not to use it
Each round costs a full implementation run plus a review. For routine work, `$claude-delegate` with `--verify` is enough. Use pairing for risky, subtle, or security-relevant changes, or when the user asks for a second agent's eyes.
