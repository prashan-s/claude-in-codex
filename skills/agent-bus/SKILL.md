---
name: agent-bus
description: Exchange messages between agent processes (Codex, Claude Code sessions, Gemini CLI, scripts) over the cic file-based message bus, covering send, receive, ask-and-wait, thread transcripts, and long-running bus agents started with cic serve. Use when building a custom multi-agent pipeline or when agents must message each other asynchronously (Claude-Claude, Claude-Codex, Claude-Gemini-Codex). For the standard patterns prefer claude-pair or claude-council.
metadata:
  short-description: Message bus and bus agents for multi-agent IPC
---

# Agent message bus

The bus is a set of Maildir-style inboxes on disk (`~/.cic/bus`). Any process that can run `cic` can take part, with no daemon required:
- Sends are atomic.
- Each message is claimed by exactly one reader.
- Every exchange is appended to a thread transcript.

Call `cic` as a single plain command.

## Addresses
Agents are plain names: `codex`, `user`, `claude:architect`, `reviewer`, `gemini`. Threads group a conversation, for example `t-design-auth`.

## Core commands
| Action | Command |
|---|---|
| Send (no wait) | `cic bus send --from codex --to reviewer --thread t1 "<message>"` |
| Send to several | `--to claude:architect,gemini` |
| Receive (claims) | `cic bus recv --as codex --thread t1 --wait 120` (exit 3 if nothing arrived) |
| Peek without claiming | `cic bus recv --as codex --peek` |
| Ask and wait for the reply | `cic bus ask --from codex --to reviewer "<question>" --wait 600` |
| Read a conversation | `cic bus log t1` (`--brief` trims bodies) |
| Overview | `cic bus threads` · `cic bus agents` |

`--json` gives the raw envelopes. [references/protocol.md](references/protocol.md) has the envelope schema and delivery semantics.

## Bus agents: make Claude, Codex, or Gemini addressable
```
cic serve start reviewer --agent claude:opus --cwd <repo> --role "Strict reviewer: reply with concrete defects only."
cic serve start architect --agent claude:sonnet --cwd <repo> --access read
cic serve start codex-peer --agent codex --cwd <repo>
cic serve list
cic serve stop reviewer
```
- A served agent answers every message sent to its name, and each thread keeps its own persistent session (a Claude session id or a Codex thread id).
- Served Claude agents are told their bus name and may message peers with `cic bus send`, so Claude agents can talk to each other directly.
- Access defaults to read-only. Use `--access auto` only for agents that should edit files.

## Topologies
- **Codex ↔ Claude:** `cic bus ask --from codex --to reviewer "<diff summary + question>" --wait 600`.
- **Claude ↔ Claude:** serve `architect` and `implementer`, then send the task to `architect` with "coordinate with implementer". They exchange messages on the thread, and you read the outcome with `cic bus log <thread>`.
- **Claude ↔ Gemini ↔ Codex:** serve all three (`--agent gemini`, `--agent codex`, `--agent claude:sonnet`) and route questions by strength. For a one-shot fan-out with synthesis, `$claude-council` is simpler.
- **Human in the loop:** agents can `cic bus send --to user …`, and you relay the reply with `cic bus send --from user …`.

## Rules of thumb
- Keep messages self-contained: one request, the needed context, and the expected reply shape.
- Always pass `--thread` for multi-step exchanges, so sessions and transcripts line up.
- Bound every wait (`--wait`) and handle exit 3 (no reply yet) by checking `cic serve list` and the agent's log in `~/.cic/serve/<name>.log`.
- Stop agents you started when the pipeline finishes: `cic serve stop <name>`.
- Delegated agents cannot spawn further agents (depth limit), but they can always use `cic bus`.
