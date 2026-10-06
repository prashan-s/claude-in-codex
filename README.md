<p align="center">
  <img src="assets/logo.png" width="96" height="96" alt="Claude in Codex logo: one bold C flowing from Codex blue into Claude terracotta on a soft matching background with a faint construction grid">
</p>

<h1 align="center">Claude in Codex: use Claude Code from OpenAI Codex</h1>

<p align="center">
  <strong>Delegate coding tasks from Codex to Claude Code and get back results that were checked, not just claimed.</strong><br>
  Claude code reviews, Claude + Codex pair programming, and Claude / Codex / Gemini panels, routed to Haiku, Sonnet, or Opus per task.
</p>

<p align="center">
  <a href="https://github.com/prashan-s/claude-in-codex/actions/workflows/ci.yml"><img src="https://github.com/prashan-s/claude-in-codex/actions/workflows/ci.yml/badge.svg" alt="CI status"></a>
  <a href="LICENSE"><img src="https://img.shields.io/badge/license-MIT-blue.svg" alt="License: MIT"></a>
  <a href="pyproject.toml"><img src="https://img.shields.io/badge/python-3.10%2B-blue.svg" alt="Python 3.10 or newer"></a>
  <a href="#faq"><img src="https://img.shields.io/badge/works%20with-Codex%20%C2%B7%20Claude%20Code%20%C2%B7%20Gemini%20CLI-D97757.svg" alt="Works with Codex, Claude Code, and Gemini CLI"></a>
</p>

<p align="center">
  <a href="#install-in-2-minutes">Install</a> ·
  <a href="#try-it-in-codex">Try it</a> ·
  <a href="#whats-included">What's included</a> ·
  <a href="#how-it-works">How it works</a> ·
  <a href="#faq">FAQ</a> ·
  <a href="#documentation">Docs</a>
</p>

```bash
git clone https://github.com/prashan-s/claude-in-codex.git && cd claude-in-codex && ./install.sh
```

---

Claude in Codex is an open-source toolkit that makes [Claude Code](https://code.claude.com/docs) a teammate your [OpenAI Codex](https://developers.openai.com/codex) agent can delegate to, talk with, and cross-check. It ships one indexed Codex skill with nine workflows and `cic`, a small Python CLI with no dependencies. `cic` runs Claude Code headless, re-checks its work, and reports back in a format Codex can act on. The Python package and the Codex/ChatGPT plugin are both named `claude-in-codex`.

> **You:** "Use $claude-in-codex delegate to fix the failing checkout test and verify it with pytest."
> **Codex** hands the task to Claude. **Claude** finds the root cause, fixes it, and adds a regression test. **cic** re-runs `pytest` itself. **Codex** gets back `DONE ✓ verified` and a summary of the diff.

## Why use it

| Without Claude in Codex | With Claude in Codex |
|---|---|
| Copy context between two agent windows | Codex hands Claude the task, the files, and the checks |
| "That should fix it" | `DONE ✓ verified`: your test command re-run by cic, not just claimed |
| The biggest model for everything | Haiku, Sonnet, or Opus, whichever fits the task |
| One model's opinion | Claude reviews Codex's work, Codex reviews Claude's, or three models weigh in |
| A vague prompt gets a vague result | Built-in prompt engineering, plus `cic improve` to sharpen rough requests |
| Waiting and hoping | Live progress, mid-task steering, model switching, and cancel |

- **Verified results.** cic re-runs your checks itself. Failures go back to the same Claude session with the exact output, and Claude keeps going until the checks pass or it can say precisely why it can't.
- **The right model for each task.** Haiku handles lookups and small edits. Sonnet does everyday engineering. Opus is reserved for architecture, concurrency, security, or repeated failures.
- **Lower token use.** The default cache-friendly context profile keeps Claude Code's system prompt reusable across repos.
  - In a live test, the same question in a second repo read 93% of its prompt from cache and cost about a third less ($0.02 vs $0.03).
  - In a raw-flag benchmark, a second job wrote about 3k new prompt tokens instead of about 10k.
  - Failure output is trimmed to the lines that matter before it goes back to Claude, and reports are capped before Codex reads them.
- **Agents that talk to each other.** Claude↔Claude, Claude↔Codex, and Claude, Codex, and Gemini together, over a local message bus.

## Install in 2 minutes

**You need:** macOS or Linux, Python 3.10+, [Claude Code](https://code.claude.com/docs) logged in (`claude auth status`), and the Codex CLI or app.

```bash
git clone https://github.com/prashan-s/claude-in-codex.git
cd claude-in-codex
./install.sh     # skills → ~/.codex/skills · cic → ~/.local/bin · Codex permission rule → ~/.codex/rules
cic doctor       # every line should say ok
```

Restart Codex, then try your first delegation below.

<details>
<summary><strong>Other ways to install:</strong> skills.sh, Codex plugin marketplace, pip/uv</summary>

**skills.sh (npx skills):**
```bash
# Choose one scope:
npx skills add prashan-s/claude-in-codex -a codex      # current project
npx skills add prashan-s/claude-in-codex -a codex -g   # global
uv tool install git+https://github.com/prashan-s/claude-in-codex   # or: pipx install git+https://…
cic setup                                                          # Codex permission rule + health check
```

**Codex plugin marketplace:**
```bash
codex plugin marketplace add prashan-s/claude-in-codex
codex plugin add claude-in-codex@claude-in-codex
uv tool install git+https://github.com/prashan-s/claude-in-codex && cic setup
```

**Uninstall:** `./uninstall.sh` (add `--purge` to also delete local job history in `~/.cic`).
</details>

## Try it in Codex

Say these to Codex in plain language:

| You want | Say to Codex |
|---|---|
| A bug fixed, with proof | "Use $claude-in-codex delegate to fix the failing test in tests/test_orders.py and verify with `pytest -q`." |
| A large change done safely | "Use $claude-in-codex delegate with `--plan` to move session storage to Redis behind a feature flag." |
| A review before you merge | "Use $claude-in-codex review to review my uncommitted changes adversarially." |
| A design discussion | "Use $claude-in-codex session to talk through the caching design with Claude Opus." |
| Pair programming | "Use $claude-in-codex pair: Claude implements idempotency keys, Codex reviews until it approves." |
| Several expert opinions | "Use $claude-in-codex council to choose between Redis streams and SQS for our job queue." |
| To check on Claude | "Use $claude-in-codex jobs to show what Claude is doing and tell it to reuse RetryPolicy." |
| A sharper request | "Use $claude-in-codex prompting to turn this request into a strong brief before delegating." |

## What's included

| Workflow | What it does |
|---|---|
| `$claude-in-codex delegate` | Hand a coding task (implement, fix, debug, refactor, tests, docs) to Claude and get a verified result |
| `$claude-in-codex review` | Get a read-only, severity-ranked review of local changes or a branch |
| `$claude-in-codex session` | Talk back and forth with a persistent, named Claude session |
| `$claude-in-codex jobs` | Watch progress, steer mid-task, switch models, cancel, see token usage |
| `$claude-in-codex prompting` | Write strong briefs: prompt and context engineering, with a technique picker |
| `$claude-in-codex pair` | Driver/navigator loop (Claude↔Claude or Claude↔Codex) until the reviewer approves |
| `$claude-in-codex council` | A panel of Claude, Codex, and Gemini, plus a moderator that checks the facts |
| `$claude-in-codex agent-bus` | Agents message each other; run Claude, Codex, or Gemini as long-lived agents |
| `$claude-in-codex setup` | Install, diagnose, and fix problems |

The single installed folder contains `SKILL.md`, `agents/openai.yaml`, and all workflow references. Earlier standalone skill invocations now route through `$claude-in-codex`; reinstall and restart Codex to migrate. The `cic` CLI behind the workflows works from any shell or agent. See the [CLI reference](docs/cli.md).

## How it works

```
Codex ── skill ──▶ cic run "<task>" --verify "<check>"
                     │ picks haiku / sonnet / opus, starts Claude Code headless
                     ▼
              Claude works ◀── steer · switch model · cancel
                     │ structured report
                     ▼
              cic re-runs your checks ── fail ──▶ same Claude session gets the output (repeat, then escalate)
                     │ pass
                     ▼
              short report back to Codex: status, changes, checks, open questions, tokens
```

More detail: [how it works](docs/how-it-works.md) · [prompt audit](docs/prompt-audit.md) (how every task applies [promptingguide.ai](https://www.promptingguide.ai/) techniques).

## Picks the right Claude model

| Model | Typical tasks | Why |
|---|---|---|
| **Haiku** | "where is X", summaries, typos, renames, commit messages | fastest and cheapest |
| **Sonnet** (default) | features, bug fixes, tests, refactors, reviews | best balance of speed and quality |
| **Opus** | architecture, race conditions, security, ambiguous root causes, big multi-module changes | deepest reasoning, used only when needed |

- **Override** with `--model` or `--tier`.
- **See why** a task got its model with `cic route "<task>"`.
- **Fable** is never chosen automatically.

## Safe by default

- **Read-only questions and reviews.** Nothing changes unless the task asks for edits.
- **No commits or pushes.** Blocked unless you pass `--allow-git-write`.
- **Changes stay in the repo.** A missing tool is reported, never installed globally.
- **No delegation loops.** Each hop is depth-limited.
- **Your choice on sandboxing.** Codex's sandbox hides Claude Code's login, so `install.sh` adds a Codex permission rule that runs bare `cic …` commands outside the sandbox. Anything passed to `cic`, including `--verify` commands, then runs without a prompt. To approve each run instead, install with `./install.sh --no-rules`.

## If something goes wrong

| What you see | What to do |
|---|---|
| Claude says "Not logged in" when run from Codex | Re-run `./install.sh` (or `cic setup`), call `cic` as a plain command (not `cd … && cic …`), and restart Codex |
| `cic: command not found` | Run `./install.sh`, or call `bin/cic` from the cloned folder |
| Report says BLOCKED by permission denials | Re-run with `--access auto`, or allow one command: `--allow 'Bash(npm install *)'` |
| "verification command cannot run" | Fix the `--verify` command for your environment, for example the project's own test runner |

Run `cic doctor` for a full health check. Every other case is covered in [`$claude-in-codex setup`](skills/claude-in-codex/references/setup.md).

## FAQ

### How do I use Claude Code inside OpenAI Codex?
Install this toolkit, restart Codex, and ask in plain language: "Use $claude-in-codex delegate to …". Codex calls `cic`, `cic` runs Claude Code headless, and the verified result comes back into your Codex conversation.

### Can Codex delegate tasks to Claude Code automatically?
Yes. The `$claude-in-codex` index routes your request to the relevant workflow and loads its instructions on demand. Add a workflow name, such as `review` or `delegate`, to select it explicitly.

### Which Claude model does it use: Opus, Sonnet, or Haiku?
The smallest model that fits each task: Haiku for simple work, Sonnet by default, Opus for hard problems. If the work fails twice, it moves up one model. Pin a model any time with `--model`.

### Does it work with a Claude Pro or Max subscription?
Yes. It uses your existing Claude Code login, subscription or API key. No extra keys are needed.

### Does it work with Gemini CLI?
Yes, as a panel member or a bus agent. If Gemini CLI isn't installed or logged in, cic reports it as unavailable and continues without it. Gemini CLI's free Code Assist login is no longer accepted; `GEMINI_API_KEY` is the likely fix.

### Can I use it from Claude Code, Cursor, or other agents?
`cic` is a plain CLI, so any agent with a shell can call it. For example, Claude Code can run `cic pair --driver codex` or `cic council`. The skills use the open SKILL.md format and are written for Codex as the orchestrator.

### Is it available as a ChatGPT or Codex plugin?
The package is ready for OpenAI's plugin directory and installs today from the Codex plugin marketplace (see [Install](#install-in-2-minutes)). The skills run local commands, so they need Codex with a shell on your machine.

### How much does it cost, and how do I track tokens?
It runs on your existing Claude and Codex plans. Every report shows its token use and the share read from cache. `cic stats` totals usage by model and suggests concrete ways to spend less.

### Does my code go anywhere new?
No. `cic` runs locally, collects nothing, and only starts the CLIs you already use. Each of those talks to its own provider exactly as when you run it yourself. See [PRIVACY.md](PRIVACY.md).

## Documentation

- [How it works](docs/how-it-works.md): architecture, the verification guarantee, the token budget, the message bus, safety
- [CLI reference](docs/cli.md): every command, flag, and exit code
- [Prompt audit](docs/prompt-audit.md): how each task type applies promptingguide.ai techniques
- [Model routing](skills/claude-in-codex/references/model-routing.md) · [Task recipes](skills/claude-in-codex/references/task-recipes.md) · [Agent bus protocol](skills/claude-in-codex/references/protocol.md)
- Publishing: [ChatGPT / Codex plugin](docs/launch/chatgpt-plugin-submission.md) · [Distribution plan](docs/launch/distribution-plan.md) · [Privacy](PRIVACY.md) · [Terms](TERMS.md) · [Changelog](CHANGELOG.md)

## Contributing

Bug reports, task recipes, and router tuning are all welcome. See [CONTRIBUTING.md](CONTRIBUTING.md) for setup, pull requests, and releases. Participation follows our [Code of Conduct](CODE_OF_CONDUCT.md). Report vulnerabilities privately as described in [SECURITY.md](SECURITY.md).

```bash
python3 -m unittest discover -s tests -v   # end-to-end through a fake Claude binary; no login or tokens needed
```

If Claude in Codex saves you a round-trip, **star the repo**. That helps other Codex and Claude Code users find it.

## License

[MIT](LICENSE) © 2026 Prashan Samarathunge
