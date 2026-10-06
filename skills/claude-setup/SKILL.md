---
name: claude-setup
description: Install, verify, or troubleshoot the claude-in-codex toolkit, covering the cic CLI on PATH, the Codex exec-policy rule that lets cic run outside the sandbox, Claude Code login, and the optional Codex and Gemini CLIs. Use when cic is missing, a Claude run fails with authentication, sandbox, permission, or depth errors, or the user asks to set up control of Claude from Codex.
metadata:
  short-description: Install and troubleshoot cic for Codex
---

# Set up and troubleshoot cic

## Check
Run `cic doctor` as a single plain command. It reports each item as ok, WARN, or FAIL, with a fix. Add `--probe` to also test Gemini's login with a tiny call.

## Install (once per machine)
Run the repository's installer from a normal terminal, or let Codex run it with approval:
```
<path-to-claude-in-codex>/install.sh
```
It does three things:
1. Links `cic` into `~/.local/bin`.
2. Links the skills into `~/.codex/skills`.
3. Copies `codex/rules/claude-in-codex.rules` into `~/.codex/rules/`. That rule lets Codex run `cic …` outside its sandbox without prompting.

Restart Codex afterwards so it loads the new skills and rules. `uninstall.sh` reverses all three.

## Why the exec-policy rule matters
Claude Code keeps its login in the macOS keychain and writes to `~/.claude`. Inside the Codex sandbox it reports "Not logged in" even when you are logged in. The rule only matches a bare `cic …` command, so always call `cic` directly: no `cd … &&`, pipes, redirects, or `$(…)`. Use `--cwd` for the directory. If the rule cannot be installed, approve the escalation prompt when Codex asks to run `cic` outside the sandbox.

The trade-off: with the rule, everything a cic call carries runs unsandboxed and unprompted, including `--verify` command strings and `--access full` runs. Never build those from untrusted repository text. If the user prefers per-run approval, install with `install.sh --no-rules`.

## Troubleshooting
| Symptom | Fix |
|---|---|
| Exit 6, "running inside the Codex sandbox" | Rule missing or not matched: install it, restart Codex, call `cic` as a plain command |
| `cic: command not found` | Run install.sh, or call `<repo>/bin/cic` by absolute path |
| BLOCKED, "not authenticated" | Log in from a normal terminal: `claude auth login`; check with `claude auth status` |
| Exit 5, "delegation depth limit" | You are inside a delegated agent; do the work directly (raise `CIC_MAX_DEPTH` only deliberately) |
| Repeated permission denials | Re-run with `--access auto`, or `--allow 'Bash(<cmd> *)'` for the specific command |
| "verification command cannot run" | Fix the `--verify` command for this environment (project runner or venv) |
| Gemini "IneligibleTierError" or unavailable | Likely fix: set `GEMINI_API_KEY` (Google AI Studio key); otherwise drop gemini from council members |
| Codex member fails | `codex login status`; ensure `codex exec` works in a terminal |
| Job "stalled" or rate limited | `cic status <job>` shows rate-limit and retry info; wait, or switch tier with `cic model <job> sonnet` |
| Worker died (machine slept) | `cic reply <job> "continue"` resumes the same Claude session |

## Configuration
Optional overrides live in `~/.cic/config.json`:
```json
{"default_model": "auto", "wait_seconds": 540, "max_attempts": 3, "max_depth": 1, "lean": false,
 "council_members": ["claude:sonnet", "codex", "gemini"], "council_synth": "claude:opus",
 "pair_driver": "claude:sonnet", "pair_navigator": "claude:opus"}
```
Environment overrides: `CIC_HOME`, `CIC_CLAUDE_BIN`, `CIC_CODEX_BIN`, `CIC_GEMINI_BIN`, `CIC_MAX_DEPTH`, `CIC_WAIT_SECONDS`, `CIC_DEFAULT_MODEL`.
