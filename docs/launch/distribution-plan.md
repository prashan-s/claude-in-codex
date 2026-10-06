# Distribution plan: skills.sh and other directories

Goal: be the first result for "Claude Code in Codex", "Codex delegate to Claude", and "Claude Code Codex skills". Each channel below says how listing works, what is already prepared, and the steps left. Facts were checked on 2026-10-06.

## 1. skills.sh (Vercel Labs' open agent skills directory)

**How listing works.** There is no submission form. A public GitHub repo appears on skills.sh once people install it with the `skills` CLI. Ranking uses anonymous install telemetry (all-time installs, trending over 24 hours, "hot"). The CLI only reports repo and skill identifiers for public GitHub repos.

**Prepared:**
- Skills live in `skills/<name>/SKILL.md`, a path the CLI searches. It looks at the repo root, `skills/`, `skills/.curated/`, `skills/.experimental/`, and agent folders, up to 3 levels deep.
- Valid frontmatter: `name` and `description`, both checked by Codex's validator.
- The CLI installs Codex skills to `~/.codex/skills/` with `-g`, or to `.agents/skills/` per project. That matches our layout.

**Steps (the repo is public as of 2026-10-06):**
1. `npx skills add prashan-s/claude-in-codex --list` discovers the single `claude-in-codex` skill. Its installed folder includes all nine workflow references; listing discovery does not prove marketplace indexing.
2. Seed real installs:
   - Your own machines: `npx skills add prashan-s/claude-in-codex -a codex -g`.
   - Collaborators.
   - The README quick start, so every reader who installs counts.
3. Add the badge to the README once the listing exists. Until then, the badge URL returns nothing.
   ```markdown
   [![skills.sh](https://skills.sh/b/prashan-s/claude-in-codex)](https://skills.sh/prashan-s/claude-in-codex)
   ```
4. Keep each skill `description` keyword-rich. Directories and agents both match on it, so mention Claude Code, Codex, delegate, review, Opus, Sonnet, Haiku, and Gemini where it is natural.

**Caveat to communicate.** `npx skills add` copies skill folders only. Users still need the CLI: `uv tool install git+https://github.com/prashan-s/claude-in-codex && cic setup`. The `$claude-in-codex setup` skill and the README both say so.

## 2. Codex plugin marketplace (GitHub-hosted)

**How it works.** Any GitHub repo with `.agents/plugins/marketplace.json` can be added as a marketplace:
```bash
codex plugin marketplace add prashan-s/claude-in-codex
codex plugin add claude-in-codex@claude-in-codex
```

**Prepared and tested locally.** `.agents/plugins/marketplace.json` uses `"source": "local", "path": "./"` and points at the repo root, which holds `.codex-plugin/plugin.json`. On 2026-10-06, an install into a throwaway `CODEX_HOME` produced `claude-in-codex@1.0.0` with nine standalone skills. Version 2.0.0 replaces those with one indexed bundle; re-test the new package after publishing.

**Steps:**
- After pushing, test the remote form above in a throwaway `CODEX_HOME`.
- To reach OpenAI's curated catalog, watch the openai/plugins repository (the Codex docs reference it) for a contribution process. Don't assume one exists until it is documented.

## 2b. OpenAI plugin directory (ChatGPT and Codex)

The same package can go to OpenAI's public plugin directory: ZIP upload, review, then publish. The manifest, icons, policies, and validated ZIP builder are ready. Follow [chatgpt-plugin-submission.md](chatgpt-plugin-submission.md) for the publisher-only steps: adopt and publish the policies, choose countries, verify your identity, and complete the attestations.

## 3. Claude Code side (optional, widens reach)

Claude Code users can call `cic` too (for example `cic pair --driver codex`, `cic council`), but the skills are written for Codex as the orchestrator.

- **Option A:** document `cic` usage from Claude Code in a short `docs/claude-code.md`.
- **Option B:** a separate Claude-oriented skill set (e.g. `codex-council`) and a `.claude-plugin/marketplace.json`.

Do this only after the Codex launch shows traction.

## 4. Curated lists and communities

Submit after the repo is public and has a demo GIF. Each list has its own contribution rules; read them first.

| Channel | Action |
|---|---|
| "awesome" lists for Claude Code, Codex, AI agents, and agent skills | Open a PR with a one-line entry: "Claude in Codex: use Claude Code from Codex with verified results, model routing, and multi-agent pairing." |
| Hacker News | "Show HN: Claude in Codex – Codex delegates to Claude Code and verifies the result" (weekday, 8–10am US Eastern) |
| Reddit | r/ClaudeAI, r/OpenAI, r/ChatGPTCoding, r/LocalLLaMA (multi-agent angle). Lead with a demo and follow each subreddit's self-promotion rules. |
| Product Hunt | Optional, after the first 100 stars; needs a gallery (GIF plus 3 screenshots) |
| dev.to and Hashnode | Cross-post the Medium article with a canonical URL pointing to Medium or the README |

## 5. Search engine optimization checklist

- **Repo description and topics:** see `github-setup.md`. They feed GitHub search and Google's snippet.
- **README:**
  - The H1 and first paragraph contain "Claude Code", "OpenAI Codex", "delegate", and "verified".
  - The FAQ headings are phrased as searchable questions.
  - Descriptive anchor links point to official docs.
- **Social preview image:** for click-through on X, LinkedIn, and Medium cards.
- **Backlinks:** the Medium article, the dev.to cross-post, awesome-list entries, and the HN or Reddit threads all link to the repo with descriptive anchor text, such as "Claude Code in Codex toolkit" rather than "here".
- **Release notes:** each GitHub release (generated notes plus CHANGELOG highlights) is a new indexable page. Keep titles descriptive.
- **PyPI (later):** a project page with the same keywords is a second high-authority result.
