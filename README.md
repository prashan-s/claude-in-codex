# Claude in Codex

[![CI](https://github.com/prashan-s/claude-in-codex/actions/workflows/ci.yml/badge.svg)](https://github.com/prashan-s/claude-in-codex/actions/workflows/ci.yml)

Connect OpenAI Codex and Anthropic Claude Code for AI coding, code review, pair programming, and agent collaboration. The command is `cic`; the Python package and plugin retain the name `claude-in-codex`.

Control Claude Code from Codex. One stdlib-only Python CLI (`cic`) plus nine Codex skills let Codex:
- delegate coding work to headless Claude Code, with model routing and independently verified results
- hold multi-turn conversations with Claude
- steer or cancel running jobs
- run Claude↔Claude and Claude↔Codex pair loops and Claude/Codex/Gemini councils
- wire agents together over a file-based message bus

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
                  ▼
           compact report: status, changes, ground-truth checks, open questions
```

## Install

Requirements: macOS or Linux, Python 3.10+, and [Claude Code](https://code.claude.com/docs) logged in (`claude auth status`). Codex CLI is needed for the Codex integration. Gemini CLI is optional.

```bash
git clone https://github.com/prashan-s/claude-in-codex.git
cd claude-in-codex
./install.sh            # cic → ~/.local/bin, skills → ~/.codex/skills, exec-policy rule → ~/.codex/rules
cic doctor              # everything should say ok
```
Restart Codex afterwards. `./uninstall.sh` reverses the install; add `--purge` to also delete `~/.cic`.

**Why an exec-policy rule?** Inside the Codex sandbox, Claude Code can't read its keychain login, so it reports "Not logged in". The rule `prefix_rule(pattern=["cic"], decision="allow")` lets Codex run a bare `cic …` command outside the sandbox without asking.

The trade-off: with the rule installed, everything a `cic` invocation carries runs unsandboxed and unprompted. That includes any `--verify "<command>"` string, `--access full` runs, and whatever Claude does under its `auto` mode classifier. Text that Codex picked up from an untrusted repository can therefore reach your machine through these flags. If you want Codex to ask before each run, install with `./install.sh --no-rules` instead.

## Skills (Codex)

| Skill | Use it to |
|---|---|
| `$claude-delegate` | hand a coding task to Claude and get a verified result |
| `$claude-review` | get a read-only, severity-ranked Claude review of local changes |
| `$claude-session` | talk back and forth with a persistent, named Claude session |
| `$claude-jobs` | watch, wait on, steer, re-model, cancel, or continue jobs |
| `$claude-prompting` | write strong briefs (prompt and context engineering, technique picker) |
| `$claude-pair` | run a driver/navigator loop: Claude↔Claude or Claude↔Codex until approved |
| `$claude-council` | ask Claude, Codex, and Gemini in parallel, with an Opus moderator |
| `$agent-bus` | message between agents, and run Claude/Codex/Gemini as bus agents |
| `$claude-setup` | install, diagnose, and troubleshoot |

The repository is also a Codex plugin (`.codex-plugin/plugin.json`). Even when installed as a plugin, `cic` and the rule still come from `install.sh`.

## CLI at a glance

```bash
cic run "Fix: empty cart returns 500; expected 400 empty_cart" --cwd ~/app \
        --file src/orders/api.py --verify "uv run pytest -q" --done "regression test added"
cic run "Migrate sessions to Redis behind a flag" --plan --background   # opus plans, fresh run executes
cic ask "Where is rate limiting configured?"                            # read-only, usually haiku
cic review --adversarial                                                 # read-only findings
cic say design "Should pagination be cursor-based here?"                # persistent conversation
cic status | wait <job> --timeout 300 | result <job> | logs <job>
cic steer <job> "use the existing RetryPolicy" | model <job> opus | cancel <job>
cic reply <job> "also handle 404"                                      # same Claude session
cic pair "Add idempotency keys to POST /payments" --navigator codex --verify "make test"
cic council "LISTEN/NOTIFY vs Redis streams vs SQS for job fan-out?"
cic serve start reviewer --agent claude:opus && cic bus ask --from codex --to reviewer "…" --wait 600
cic route "<brief>"     # explain the model decision
cic run "<brief>" --dry-run   # show route, argv, contract, and brief; run nothing
```
Exit codes: 0 done · 1 failed/cancelled · 3 still running · 4 needs attention (partial / needs_input / blocked) · 5 depth limit · 6 sandboxed.

## Model routing
| Tier | When | Effort |
|---|---|---|
| `haiku` | lookups, explanations, typos, renames, formatting, commit messages | none (not supported) |
| `sonnet` (default) | features, fixes, tests, refactors, reviews, research | medium for clear scope, high for fixes, debugging, refactors, and reviews |
| `opus` | architecture, concurrency, security, ambiguous root causes, large multi-module work, failures from lower tiers | high, or xhigh for hands-on security and concurrency work |

- **Aliases.** Routing uses Claude Code aliases, so each tier tracks the newest model in its line.
- **Fallbacks.** haiku→sonnet, sonnet→opus, opus→sonnet. The haiku fallback also covers Haiku 4.5's announced retirement window.
- **Escalation.** It happens only after repeated failure, because switching models rebuilds the prompt cache.
- **Fable.** It is never selected automatically.

`cic route` explains each decision.

## How the "done means done" guarantee works
1. **Contract.** Claude gets a delegation contract appended to its system prompt: investigate first, minimal diffs, root causes, honest verification, no commits, side effects confined to the repo, and status semantics. It also gets an XML brief whose technique block depends on the task kind: reproduce-first fixes, hypothesis-loop debugging, characterization-tested refactors, and tree-of-thought plans.
2. **Structured report.** Output is enforced by `--json-schema`.
3. **Strict success check.** A result counts as success only with `is_error == false`, a completed terminal reason, and an acceptable report. Claude Code reports auth failures as `subtype: success`, and cic catches them.
4. **Ground-truth checks.** Your `--verify` commands are re-run by cic, never Claude's self-reported ones. Failures go back to the same session.
5. **Escalation and blocking.** Repeated failures escalate the model. Unrunnable checks, permission denials, and needs-input stop with a precise reason instead of looping.

## Communication pipeline
- **Claude↔Codex:** Codex orchestrates through `cic`, and `cic pair --navigator codex` or `--driver codex` puts Codex on either side of a review loop.
- **Claude↔Claude:** pair loops (Sonnet driver, Opus navigator), or two `cic serve` Claude agents messaging each other with `cic bus send`.
- **Claude↔Gemini↔Codex:** `cic council` fan-out with moderation, or serve all three as bus agents.
- **Transport:** Maildir-style inboxes in `~/.cic/bus` with atomic delivery, exactly-once claiming, and durable thread transcripts. Any process can join (see `skills/agent-bus/references/protocol.md`).
- **Recursion guard:** each hop increments `CIC_DEPTH`. Delegated agents can message on the bus but cannot spawn further agents (default `max_depth` is 1).

## Development
```bash
python3 -m unittest discover -s tests -v   # 36 tests; end-to-end via tests/fake_claude.py (no tokens)
```

GitHub Actions runs the suite on Linux and macOS with Python 3.10–3.14 for pushes to `main`, pull requests, and manual runs. It also checks shell syntax, installs and removes the CLI in temporary directories, builds the wheel/source distribution, and checks the installed wheel outside the checkout. No Claude, Codex, or Gemini login is needed. Dependabot checks GitHub Actions updates weekly.

Releases use semantic versions without a `v` prefix, starting at `1.0.0`: increment MAJOR for incompatible changes, MINOR for compatible features, and PATCH for compatible fixes. To create a release, update the version in `pyproject.toml`, `src/cic/__init__.py`, and `.codex-plugin/plugin.json`, then push a matching `MAJOR.MINOR.PATCH` tag. The release workflow runs CI, checks those versions against the tag, and publishes a GitHub release with the wheel and source distribution. GitHub's automatic source archives include the installer and skills. It does not publish to PyPI.

After committing and pushing the version changes:

```bash
git tag -a 1.0.0 -m "Release 1.0.0"
git push origin 1.0.0
```
The fake binary speaks the same stream-json protocol, including replays, `set_model`, interrupts, and structured output. The protocol was confirmed live against Claude Code 2.1.291 and Codex CLI 0.160.0.

**Verified live:**
- a Codex `codex exec` run that triggered `$claude-delegate`, polled a background job, and got a verified result
- the repair loop with escalation to Opus
- `ask`, two-turn `say` sessions, and `review`
- a council of Claude and Codex
- the Codex→Claude and Claude↔Claude bus
- a Claude-driver, Codex-navigator `pair` loop
- `steer`, `cancel`, and `--worktree`

**Tested only against the fake binary:**
- `--plan`
- `cic reply`
- `pair --driver codex`

## Known limits
- **Gemini.** Only the failure path has been exercised. On the development machine, Gemini CLI 0.46.0's Code Assist login fails with `IneligibleTierError`. Council and bus runs that include Gemini report it as unavailable and continue without it. Setting `GEMINI_API_KEY` is the likely fix, but it is untested, and so is the parsing of a successful Gemini response.
- **Cost figures.** They are Claude Code's client-side estimates at list price. Subscription billing differs.
- **Auth.** `--bare` is not used because it requires an API key. `--lean` (safe mode) is the opt-in low-overhead profile.
