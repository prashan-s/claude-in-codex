# Publishing as a ChatGPT / Codex plugin

OpenAI plugins are shared by ChatGPT and Codex. Public plugins are submitted as a ZIP through OpenAI's plugin submission portal and reviewed before publication. This guide follows OpenAI's own submission guidance, from the Plugin Creator plugin's "prepare plugin submission" skill.

**Plugin type: skills-only.** It has 9 skills and no MCP server, so OpenAI requires no MCP test cases, demo recording, or reviewer credentials. Everything else applies: listing fields, the four public URLs, icons, release notes, the publisher's verified identity, countries, and attestations.

## What is ready

| Item | Status | Where |
|---|---|---|
| Portable manifest (Agent Plugins 1.0) | ready | `plugin.json` (listing under `extensions.com.openai.interface`) |
| Codex compatibility overlay | ready, kept in sync | `.codex-plugin/plugin.json` |
| Display name: "Claude in Codex" | ready (15/30 chars) | `displayName` |
| Subtitle: "Delegate coding to Claude Code" | ready (30/30 chars) | `shortDescription` |
| Long description, requirements, safety | ready (under 4,000 chars) | `longDescription` |
| Category, capabilities, 3 starter prompts | ready | `category: Developer Tools` |
| Icons | ready: 512×512 and 128×128 square PNGs | `assets/logo.png`, `assets/composer-icon.png` (designed in `assets/icon.html`; re-export with `scripts/export-icon.sh`) |
| Release notes | ready | `extensions.com.openai.publication.release_notes` |
| Privacy policy and terms | drafted from verified behavior (no data collected; local files only; third-party CLIs) | `PRIVACY.md`, `TERMS.md` |
| ZIP build and validation | passes | `python3 scripts/bundle.py` (local maintainer script, git-ignored) → `dist/claude-in-codex-<version>-openai-plugin.zip` |
| Codex marketplace install | tested locally (throwaway `CODEX_HOME`) | `.agents/plugins/marketplace.json` |

## What only you can do

1. **Review and adopt `PRIVACY.md` and `TERMS.md`.** They state facts about the software, but publishing them makes them your commitments. Edit anything you don't agree with.
2. **Publish them.** Commit and push. Then confirm all four listing URLs:
   ```bash
   python3 scripts/bundle.py --check-urls
   ```
   Today the website and support URLs load. The privacy and terms URLs return 404 until the files are pushed.
3. **Choose countries.** `publication.countries` is left out on purpose. Pick your markets, or explicitly choose all available countries in the portal.
4. **Verified developer identity.** Select your verified individual or business identity in the portal. The package uses "Prashan Samarathunge"; keep it consistent with the verified name.
5. **Commerce.** Declare "no purchases or payments": the plugin has none.
6. **Attestations and scans.** These are completed by you in the portal, including the declaration that the plugin is not directed at children under 13.

## Submit

1. Build the final ZIP:
   ```bash
   python3 scripts/bundle.py --check-urls
   ```
   It must print `package checks: PASS` with no URL problems.
2. In the OpenAI plugin submission portal, upload the ZIP. The upload creates a **draft**; submitting and publishing are separate steps.
3. Check the saved draft against the package: developer name, the 9 skills, listing text, icons, and release notes.
4. Fill in the review information pages (countries, then attestations) and submit for review.
5. After approval, publish the approved release and confirm country targeting.

## Updating later

- Bump the version in `pyproject.toml`, `src/cic/__init__.py`, `.codex-plugin/plugin.json`, and `plugin.json`. CI fails if they drift.
- Update `release_notes`, rebuild, and re-upload.
- Re-uploading replaces the whole bundle and resets attestations, so re-check the saved draft.

## Honest limits to keep in the listing

- The skills run local commands (`cic`, `claude`), so they only work in a Codex environment with shell access on macOS or Linux, with Claude Code installed and logged in. They do not work in a ChatGPT conversation without a local Codex environment. The long description says this.
- The `cic` CLI is installed separately (`uv tool install git+https://github.com/prashan-s/claude-in-codex`, then `cic setup`); the plugin ships only skills and assets.
- Approval is not guaranteed. A valid ZIP covers only the package checks; the portal steps above still apply.
