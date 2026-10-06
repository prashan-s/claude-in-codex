---
name: claude-session
description: Hold a multi-turn conversation with a named, persistent Claude Code session for design discussions, codebase questions, brainstorming, or getting Claude's opinion turn by turn, with context kept between turns. Use when the user wants to talk with Claude back and forth or relay a discussion, rather than hand off one task. Not for one-shot delegated work (claude-delegate) or controlling a running job (claude-jobs).
metadata:
  short-description: Talk back and forth with a persistent Claude session
---

# Converse with Claude

A session pins a Claude Code session id up front. Every `cic say` is one turn that resumes the same conversation, so Claude keeps its context and the prompt cache stays warm between turns.

## Start (optional)
```
cic session new <name> --cwd <repo> --model sonnet --access read --role "<persona and ground rules>"
```
`cic say` auto-creates a read-only Sonnet session when the name is new. Create one explicitly when you need a different model, write access, or a role.

## Talk
```
cic say <name> "<message>"
```
- The output is Claude's reply. Call `cic` as a single plain command.
- Make each message self-contained: what you need, in what form, plus any new facts since the last turn.
- Stay on one model per session. `--model` on a later turn works, but it rebuilds the prompt cache once.
- A session edits files only if it was created with `--access edit|auto` and the message explicitly asks for edits.
- For a long answer, use `cic say <name> "…" --background`, then `cic wait <job>`.

## Good uses
- **Design partner:** `--model opus --role "Skeptical staff engineer: challenge weak assumptions, prefer simple designs."`
- **Codebase guide:** `--model haiku` for fast where-is and what-does questions.
- **Relay for the user:** quote the user's words verbatim, then add the context Claude lacks.
- **Hand-off:** once the discussion settles on a concrete change, delegate the change with `$claude-delegate`, passing the agreed design as `--context`.

## Manage
`cic session list` · `cic session show <name>` · `cic session rm <name>`

To reopen a conversation interactively, run `claude --resume <session_id>` (the id is in `cic session show`).
