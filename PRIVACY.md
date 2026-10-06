# Privacy Policy: Claude in Codex

Effective date: 2026-10-06

Claude in Codex (the `cic` CLI, its Codex skills, and the `claude-in-codex` plugin) is open-source software that runs entirely on your own computer. This policy explains what it does with data.

## What the project collects

Nothing. The project operates no servers, collects no telemetry or analytics, and receives none of your code, prompts, results, or personal information.

## What stays on your computer

`cic` keeps working files locally in `~/.cic`, or in `$CIC_HOME` if you set it:
- job records and logs
- the prompts it composed and the reports it received
- session metadata
- message-bus transcripts

You control these files. Delete them any time with `./uninstall.sh --purge` or by removing the folder.

## What goes to third parties

`cic` starts command-line tools you have already installed and signed in to: Claude Code (Anthropic), and optionally Codex CLI (OpenAI) and Gemini CLI (Google). Those tools send your prompts and the code context they read to their providers, exactly as when you run them yourself. Their own terms and privacy policies govern that data:

- Anthropic: https://www.anthropic.com/legal/privacy
- OpenAI: https://openai.com/policies/privacy-policy/
- Google: https://policies.google.com/privacy

The only change `cic` makes to that flow is composing the task prompts it sends through those tools.

## Installers

If you install the skills with the third-party `skills` CLI (skills.sh), that tool collects anonymous usage data under its own policy. You can opt out with `DISABLE_TELEMETRY=1`.

## Children

Claude in Codex is a developer tool. It is not directed at children under 13.

## Changes and contact

Changes to this policy are published in this file, and its history is in the repository. Questions: open an issue at https://github.com/prashan-s/claude-in-codex/issues. For security reports, see [SECURITY.md](SECURITY.md).
