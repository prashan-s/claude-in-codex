# cic CLI reference

`cic --help` and `cic <command> --help` list every flag. This page groups the commands by job. Call `cic` as a single plain command, and use `--cwd` instead of `cd … &&`, so the Codex exec-policy rule matches.

## Delegate work

```bash
cic run "Fix: empty cart returns 500; expected 400 empty_cart" --cwd ~/app \
        --file src/orders/api.py --verify "uv run pytest -q" --done "regression test added"
cic run "Migrate sessions to Redis behind a flag" --plan --background    # opus plans, a fresh run executes
cic run "Fix the settings page layout" --image shot.png --hint "flex container lost min-width"
cic run "Write the release notes" --example @docs/release-notes-style.md
cic improve "fix the bug in the duration thing" --cwd ~/app               # rewrite a vague brief first
cic run "<brief>" --dry-run                                              # route, techniques, argv, contract, brief
cic route "<brief>"                                                      # explain the model decision
```

| Flag | Purpose |
|---|---|
| `--kind` | implement, fix, debug, refactor, test, docs, chore, research, plan, explain, ask, or review (default: inferred) |
| `--model` / `--tier` / `--effort` | override routing: `haiku`, `sonnet`, `opus`, `fable`, or a full ID; `fast`, `balanced`, `deep`; `low` to `max` |
| `--access` | `read`, `edit` (allowlist), `auto` (classifier), or `full` (explicit opt-in) |
| `--file`, `--context`, `--context-file` | context: file pointers, background text, small inlined files |
| `--done`, `--verify`, `--constraint` | acceptance criteria, ground-truth checks that cic re-runs, real limits |
| `--hint`, `--example`, `--image` | directional hints, few-shot style samples, screenshots or diagrams |
| `--plan`, `--worktree`, `--max-attempts`, `--no-escalate` | plan-first chaining, isolated git worktree, repair budget, pin the model |
| `--profile` | context Claude loads: `standard` (default, cache-friendly, no MCP), `lean`, `minimal`, `full` |
| `--background` / `--wait N` | return immediately, or block up to N seconds (default 540) |

## Ask, review, converse

```bash
cic ask "Where is rate limiting configured?"                  # read-only, usually haiku
cic review --adversarial                                       # read-only, severity-ranked findings
cic review --base origin/main "auth and session handling"
cic session new design --model opus --role "skeptical staff engineer"
cic say design "Should pagination be cursor-based here?"      # persistent conversation
```

## Monitor and control

```bash
cic status [job]          cic jobs [--all]          cic wait <job> --timeout 300
cic result <job> [--full] cic logs <job> --tail 40
cic stats [--days 7] [--all]                           # token and cost usage by model, with tips
cic steer <job> "use the existing RetryPolicy"         # seen at Claude's next step
cic model <job> opus                                    # switch model mid-run
cic cancel <job>                                        # graceful interrupt, then forced
cic reply <job> "also handle 404"                       # continue on the same session
```

## Multi-agent

```bash
cic pair "Add idempotency keys to POST /payments" --navigator codex --verify "make test"
cic council "LISTEN/NOTIFY vs Redis streams vs SQS for job fan-out?"
cic council "Is this migration safe?" --members claude:sonnet,claude:sonnet,claude:sonnet   # self-consistency
cic serve start reviewer --agent claude:opus --role "Strict reviewer"
cic bus ask --from codex --to reviewer "Review the retry logic in client.py" --wait 600
cic bus log <thread>      cic bus threads      cic serve list      cic serve stop reviewer
```

## Setup

```bash
cic doctor [--probe]      # checks claude/codex/gemini, login, sandbox rule, skills
cic setup                 # writes the Codex exec-policy rule (for pip/uv/skills.sh installs) and runs doctor
```

## Exit codes

| Code | Meaning |
|---:|---|
| 0 | done |
| 1 | failed or cancelled |
| 2 | usage error |
| 3 | still running (the wait timed out) |
| 4 | needs attention: partial, needs_input, or blocked |
| 5 | delegation depth limit |
| 6 | running inside the Codex sandbox |

## Configuration

Optional `~/.cic/config.json`:

```json
{"default_model": "auto", "profile": "standard", "wait_seconds": 540, "max_attempts": 3, "low_confidence": 0.7,
 "max_depth": 1, "council_members": ["claude:sonnet", "codex", "gemini"], "council_synth": "claude:opus",
 "pair_driver": "claude:sonnet", "pair_navigator": "claude:opus"}
```

Environment variables: `CIC_HOME`, `CIC_CLAUDE_BIN`, `CIC_CODEX_BIN`, `CIC_GEMINI_BIN`, `CIC_MAX_DEPTH`, `CIC_WAIT_SECONDS`, `CIC_DEFAULT_MODEL`.
