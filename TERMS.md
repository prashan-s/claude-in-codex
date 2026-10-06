# Terms of Use: Claude in Codex

Effective date: 2026-10-06

## License

Claude in Codex (the `cic` CLI, its skills, and the `claude-in-codex` plugin) is free, open-source software under the [MIT License](LICENSE). Your use, copying, modification, and distribution are governed by that license.

## No warranty

The software is provided "as is", without warranty of any kind, as stated in the MIT License. The authors are not liable for any claim, damages, or other liability arising from its use.

## Your responsibilities

- **AI-generated changes.** You are responsible for reviewing code, commands, and other changes produced by AI agents before you commit, deploy, or rely on them, including when cic reports a result as verified.
- **Third-party terms.** cic runs Claude Code, Codex CLI, and Gemini CLI on your behalf. Your use of those tools and their models remains subject to the terms of Anthropic, OpenAI, and Google.
- **Execution settings.** You decide which commands run. With the optional Codex exec-policy rule installed, `cic` commands, including any `--verify` commands you pass, run outside the Codex sandbox without a prompt. Install with `--no-rules` if you prefer to approve each run.

## Trademarks and affiliation

Claude in Codex is an independent project. It is not affiliated with, endorsed by, or sponsored by Anthropic, OpenAI, or Google. Claude, Codex, and Gemini are trademarks of their respective owners and are used only to describe compatibility.

## Changes and contact

Changes to these terms are published in this file. Questions: https://github.com/prashan-s/claude-in-codex/issues.
