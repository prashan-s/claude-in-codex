# Security policy

## Supported versions

Security fixes target the latest stable GitHub release. Older releases do not have a separate maintenance guarantee. Upgrade to the latest release when a fix is available.

## Report a vulnerability privately

Use [GitHub's private vulnerability reporting](https://github.com/prashan-s/claude-in-codex/security/advisories/new) to contact the maintainers. Do not open a public issue with exploit details, credentials, or private agent transcripts.

Include the affected version, platform, relevant configuration, expected and observed behavior, impact, and a minimal reproduction using synthetic data. Remove credentials, personal paths, and third-party confidential information. Do not test against other people's systems or accounts.

Maintainers will investigate and coordinate a fix and disclosure when appropriate. This project does not promise a response deadline or offer a bug bounty.

## Security boundaries

The CLI can invoke agents and execute verification commands with your local permissions. The default installer adds a Codex execution-policy rule. Review the [README's installation trade-offs](README.md#install) before enabling it; use `./install.sh --no-rules` if you want to install without that rule.

Treat repository content, prompts, agent output, and messages as untrusted input. Use the least access needed for a task and review commands before running them. Never put credentials in briefs, job reports, issue attachments, or committed files.

Reports about permission-profile bypasses, command construction, path handling, worktree boundaries, and unintended disclosure of local state are relevant. An agent's ability to perform an explicitly authorized command is expected behavior; reports should identify the boundary crossed and the conditions that make the behavior unintended.
