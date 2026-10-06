# How Claude in Codex works

This page covers the architecture behind `cic`: the delegation loop, model routing, the "done means done" guarantee, the multi-agent communication pipeline, and the safety model. For day-to-day use, see the [README](../README.md) and the [CLI reference](cli.md).

## The delegation loop

```
Codex ──skill──▶ cic run "fix X" --verify "pytest -q"
                  │  route: haiku | sonnet | opus (+effort, fallback)
                  │  claude -p --input-format stream-json --output-format stream-json
                  │        --json-schema <report> --append-system-prompt-file <contract>
                  ▼
           detached worker ── steer / model / cancel ◀── cic steer|model|cancel
                  │  result → strict classification (is_error, terminal_reason, denials)
                  │  status done → cic re-runs --verify itself
                  │     fail → failure output back to the SAME session (reflexion)
                  │     fail again → escalate one tier (set_model), retry
                  │  low confidence → one targeted uncertainty pass (active-prompt)
                  ▼
           compact report: status, changes, ground-truth checks, open questions
```

1. **Detached worker.** Every `cic run` starts a worker process that outlives the caller, so a long task survives a tool timeout in Codex. Codex polls with `cic wait <job> --timeout 300`.
2. **One live Claude process per job.** It runs headless in bidirectional `stream-json` mode, which lets cic:
   - send follow-ups without restarting
   - inject mid-task steering, which Claude reads at its next tool step
   - switch models with a `set_model` control request
   - interrupt cleanly
3. **Pre-assigned session id.** `--session-id` is fixed up front, so `cic reply`, `cic say`, and crash recovery always resume the same transcript.
4. **Prompt layers:**
   - The *contract* is appended to Claude Code's system prompt. It is static, so it stays cached across jobs and survives `--resume`.
   - The *brief* is the user message: task, context, acceptance criteria, verification, hints, examples, and a technique block per task kind.

## Model routing

| Tier | When | Effort |
|---|---|---|
| `haiku` | lookups, explanations, typos, renames, formatting, commit messages | none (not supported) |
| `sonnet` (default) | features, fixes, tests, refactors, reviews, research | medium for clear scope, high for fixes, debugging, refactors, and reviews |
| `opus` | architecture, concurrency, security, ambiguous root causes, large multi-module work, failures from lower tiers | high, or xhigh for hands-on security and concurrency work |

- **Aliases:** routing uses Claude Code aliases, so each tier tracks the newest model in its line.
- **Fallbacks:** haiku→sonnet, sonnet→opus, opus→sonnet.
- **Escalation:** happens only after repeated failure, because switching models rebuilds the prompt cache.
- **Fable:** never selected automatically.
- **Explaining a decision:** `cic route "<brief>"`.

Full rules: [skills/claude-delegate/references/model-routing.md](../skills/claude-delegate/references/model-routing.md).

## The "done means done" guarantee

1. **Contract and technique blocks.** Claude works under a delegation contract: investigate first, minimal diffs, root causes, honest verification, no commits, side effects confined to the repo, calibrated confidence, and status semantics. The brief applies promptingguide.ai techniques chosen per task kind (see [prompt-audit.md](prompt-audit.md)).
2. **Structured report.** The output shape is enforced with `--json-schema`.
3. **Strict success check.** A result counts as success only with `is_error == false`, a completed terminal reason, and an acceptable report. Claude Code reports auth failures as `subtype: success`; cic catches them.
4. **Ground-truth checks.** cic re-runs your `--verify` commands itself; it never runs commands Claude names in its report. Failures go back to the same session with a reflection step: name the failing check, recall the approaches already tried, don't repeat a failed one.
5. **Escalation and blocking.** Repeated failures escalate the model. Unrunnable checks, permission denials, and needs-input stop with a precise reason instead of looping.
6. **Active-prompt.** A "done" report with confidence below 0.7 gets one targeted uncertainty pass before acceptance.

## Context engineering and token budget

cic treats tokens as a budget on both sides of the delegation.

### What Claude loads (delegated side)

Claude Code carries about 20–24k tokens of its own context (system prompt, tools, settings) before your brief. Most of that cannot be avoided, but how much of it is *re-sent uncached* can. Context profiles choose what each run loads:

| Profile | Flags | Use when |
|---|---|---|
| `standard` (default) | `--exclude-dynamic-system-prompt-sections --strict-mcp-config` | always, unless a task needs MCP servers |
| `lean` | standard + `--setting-sources project,local` | you want no user plugins or hooks in delegated runs (and auth doesn't depend on user settings) |
| `minimal` | `--safe-mode` | throwaway questions where project conventions don't matter |
| `full` | none | the task needs your MCP servers or user-level setup |

What `standard` changes:
- It moves per-machine details (cwd, git status, memory paths) out of the system prompt and into the first message. The system prompt, including cic's static contract, then becomes identical across repos and jobs, so it stays cached.
- It also skips MCP servers: faster start, fewer tool tokens, and no side effects.

Measured on Claude Code 2.1.291 with a trivial prompt:

| Variant | Prompt tokens | Same job in another repo: cached / new | Cost of that 2nd run |
|---|---:|---:|---:|
| no flags (old behavior) | 23.7k | 14.5k / 9.8k | $0.021 |
| no MCP servers only | 23.0k | 18.6k / 4.4k | $0.011 |
| `lean` | 19.8k | 16.4k / 3.3k | $0.0085 |
| `minimal` (safe mode) | 19.4k | 15.7k / 3.7k | $0.0093 |

Through cic, the same question in a second repo cost $0.02 at 93% cached with `standard`, against $0.03 at 86% cached with `full`.

Other levers on the delegated side:
- **Pointers over pastes.** Briefs name files; Claude reads only what it needs. Inlined context files are capped at 20 KB each and 60 KB total.
- **Focused failure output.** Repair turns carry the failing lines with ±2 lines of context plus the summary tail, never whole logs: at most 3.5 KB per check and 6 KB per turn.
- **One session per thread of work.** Repairs, replies, and `say` turns resume the same session, so earlier context is a cache read rather than a re-send.
- **Distilled hand-offs.** `--plan` passes the plan, not the planning transcript. Council moderators get answers capped at 3.5 KB each. Pair navigators get at most 40 KB of diff and read the rest with git.
- **Cheap models first.** Haiku costs a quarter of Opus; routing escalates only after repeated failure, and never back and forth (each switch rebuilds the cache).
- **Better first attempts.** `cic improve` and the brief linter cut repair turns, the most expensive tokens of all.

### What Codex reads (orchestrator side)

Everything cic prints lands in the orchestrator's context.
- **Capped reports.** Final reports keep the 12 most relevant changes, the 8 most severe findings, 6 claims, and about 6k characters of answer text. `cic result <job> --full` has everything.
- **Small status updates.** Status snapshots are a few lines; progress lives in `cic logs`, not in the report.
- **Lean skill descriptions.** Codex keeps every skill's description in context all the time. They were cut from 3.7k to 1.9k characters (about 450 tokens per session); the full instructions load only when a skill is used.

### Seeing the usage

- **Per job:** every report shows `tokens 71.9k in (93% cached) · 308 out`. The input figure counts the prompt of every model call in the job, mostly cache reads billed at 10% of the input price.
- **Across jobs:** `cic stats [--days 7] [--all]` totals usage by model and suggests concrete fixes. Examples: low cache reuse, Opus dominating cost, or too many jobs needing attention.

## Communication pipeline

- **Claude↔Codex:** Codex orchestrates through `cic`. `cic pair --navigator codex` or `--driver codex` puts Codex on either side of a review loop.
- **Claude↔Claude:** pair loops (Sonnet driver, Opus navigator), or two `cic serve` Claude agents messaging each other with `cic bus ask`.
- **Claude↔Gemini↔Codex:** `cic council` fan-out with a moderator, or serve all three as bus agents.
- **Transport:** Maildir-style inboxes in `~/.cic/bus`. Delivery is atomic, each message is claimed exactly once, and thread transcripts are durable. Any process can join; the protocol is in [skills/agent-bus/references/protocol.md](../skills/agent-bus/references/protocol.md).
- **Recursion guard:** each hop increments `CIC_DEPTH`. Delegated agents can message on the bus but cannot spawn further agents (default `max_depth` is 1).

## Safety model

| Concern | Default |
|---|---|
| Questions, reviews, research, plans | read-only (`dontAsk` plus a read allowlist; Edit and Write removed) |
| Write tasks | Claude Code `auto` mode (classifier); Haiku uses an explicit allowlist because auto mode is unavailable there |
| Git | `git commit` and `git push` denied unless `--allow-git-write` |
| Side effects | the contract keeps installs and changes inside the repo; global installs are reported as blocked instead |
| Recursion | `CIC_DEPTH` guard (exit 5) |
| Codex sandbox | `cic` must run outside it (Claude needs its keychain login); the exec-policy rule allows bare `cic …` commands. With the rule installed, `--verify` strings and `--access full` runs execute unsandboxed and unprompted. Install with `--no-rules` to approve each run instead. |

## Verified live

Verified live against Claude Code 2.1.291 and Codex CLI 0.160.0:
- a Codex `codex exec` run that triggered `$claude-delegate`, polled a background job, and got a verified result
- a repair loop that escalated to Opus
- `ask` (including `--image`), two-turn `say` sessions, `review`, and `improve`
- a council of Claude and Codex
- the Codex→Claude and Claude↔Claude bus
- a Claude-driver, Codex-navigator `pair` loop
- `steer`, `cancel`, and `--worktree`
- installing the Codex plugin from the local marketplace

Tested only against the fake binary: `--plan`, `cic reply`, and `pair --driver codex`.

Gemini: only the failure path has been exercised. On the development machine, Gemini CLI 0.46.0's Code Assist login fails with `IneligibleTierError`. Setting `GEMINI_API_KEY` is the likely fix, but it is untested.
