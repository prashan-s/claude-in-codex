# Changelog

All notable changes to this project are documented here. The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and versions follow [Semantic Versioning](https://semver.org/) without a `v` prefix.

## [Unreleased]

## [2.0.0] - 2026-10-06

### Changed
- Replaced nine standalone skill entries with one `claude-in-codex` index and nine workflow references loaded on demand.
- Invoke `$claude-in-codex` followed by a workflow name or request; the `cic` CLI commands are unchanged.
- The installer links the indexed bundle and removes legacy skill symlinks owned by this checkout while preserving user-owned files and unrelated links.
- Plugin packages include the complete indexed bundle; the listing website is the GitHub repository.

### Migration
- Reinstall the plugin or run `install.sh`, then restart Codex.
- For copied skills.sh installations, remove the old standalone copies through the skills CLI after reviewing ownership, then install the indexed skill. Choose project or global scope explicitly.


## [1.1.0] - 2026-10-06

### Added
- `cic improve`: an automatic prompt engineer. It drafts two rewrites of a rough brief, scores them on a rubric, grounds the winner in the repository, and prints a ready-to-run `cic run` command.
- `--hint` (directional stimulus), `--example` (few-shot; literal text or `@file`), and `--image` (screenshots and diagrams, sent to Claude as image blocks) for `cic run`. `ask` gains `--hint` and `--image`, and `say` gains `--image`.
- Active-prompt pass: a "done" report with confidence below 0.7 gets one targeted turn to resolve the stated uncertainties.
- Same-model self-consistency in `cic council` (for example `--members claude:sonnet,claude:sonnet,claude:sonnet`).
- `cic setup`: writes the Codex exec-policy rule and runs `cic doctor`, for installs through skills.sh, pip, or uv.
- Codex plugin marketplace manifest (`.agents/plugins/marketplace.json`).
- OpenAI (ChatGPT / Codex) plugin package:
  - portable `plugin.json` (Agent Plugins 1.0) with the directory listing
  - icons designed in HTML/SVG (`assets/icon.html`), exported with `scripts/export-icon.sh`
  - `PRIVACY.md` and `TERMS.md`
  - a submission build that validates the package against the directory rules
- Commit, changelog, and PR-message chores automatically get the repository's recent commit subjects as style examples.
- `cic run --dry-run` lists the promptingguide.ai techniques each brief applies.
- Context profiles (`--profile standard|lean|minimal|full`). The default, `standard`, keeps Claude Code's system prompt cacheable across repos and skips MCP servers. In measurements, a second job pays about 3k new prompt tokens instead of about 10k (about 60% cheaper).
- Token accounting: every report shows prompt and output tokens and the cached share; `cic stats` totals usage by model with tips. Resumed sessions are billed per job, not as running totals.
- `cic result --full`. Default reports are length-capped (12 changes, 8 findings, about 6k characters of text) to save orchestrator tokens.
- Docs: `docs/how-it-works.md`, `docs/cli.md`, and `docs/prompt-audit.md` (per-template technique audit and its two improvement iterations).

### Changed
- Every task template was upgraded against promptingguide.ai:
  - generated-knowledge steps for implement and refactor
  - an explicit ReAct loop for debug
  - tree-of-thought viability ratings for plan
  - an evidence-then-answer chain and per-option trade-offs for research
  - word-budgeted answer formats with an example for explain and ask
  - run-what-you-document for docs
  - refute-before-reporting for reviews
- Repair messages (verification failures, continue, pair findings) now require a reflection: name the failing check, recall the approaches already tried, and don't repeat a failed one.
- The work contract defines calibrated confidence anchors.
- Council members state the strongest alternative they rejected. The moderator trusts a majority only when it is backed by cited evidence.
- The README was rewritten for users. Architecture and reference material moved to `docs/`.
- Failing-check output is focused (signal lines plus summary) before it goes back to Claude. Repair turns are capped at 6 KB of check output; council answers at 3.5 KB each; pair diffs at 40 KB.
- Skill descriptions, which Codex keeps in context in every session, were cut from 3.7k to 1.9k characters.
- `--lean` now means the `lean` profile (no user plugins or hooks) instead of safe mode; use `--profile minimal` for safe mode.

## [1.0.0] - 2026-10-06

### Added
- The `cic` CLI: routed delegation (Haiku, Sonnet, Opus) with a detached worker, a strict success check, independent `--verify` re-runs, repair turns on the same session, model escalation, steering, model switching, cancel, and reply.
- `review`, `ask`, named `session` and `say` conversations, `--plan` (Opus plans, then a fresh run executes), and `--worktree` isolation.
- Multi-agent modes: `pair` (driver and navigator; Claude↔Claude or Claude↔Codex), `council` (Claude, Codex, and Gemini with a moderator), the file-based message bus, and `serve` bus agents.
- Nine Codex skills, `install.sh` and `uninstall.sh`, the Codex exec-policy rule, and `cic doctor`.
- CI on Linux and macOS (Python 3.10–3.14), and a tag-based GitHub release workflow.

[Unreleased]: https://github.com/prashan-s/claude-in-codex/compare/2.0.0...HEAD
[2.0.0]: https://github.com/prashan-s/claude-in-codex/compare/1.1.0...2.0.0
[1.1.0]: https://github.com/prashan-s/claude-in-codex/compare/1.0.0...1.1.0
[1.0.0]: https://github.com/prashan-s/claude-in-codex/releases/tag/1.0.0
