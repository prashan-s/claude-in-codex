# GitHub launch checklist

Groundwork already in the repository:
- CI: Linux and macOS, Python 3.10–3.14, installer check, wheel build
- tag-based release workflow
- Dependabot
- issue and PR templates, CONTRIBUTING, CODE_OF_CONDUCT, SECURITY, LICENSE (MIT), CHANGELOG
- user-facing README, plus the Codex plugin and marketplace manifests

Nothing below has been run yet. Each step changes something public, so run them yourself when ready.

## 1. Repository and push (status on 2026-10-06)

- The repository already exists and is public: `prashan-s/claude-in-codex`, with `main` pushed at `56143cf`.
- Newer work in the working tree is **not yet committed**: prompt upgrades, token profiles, ChatGPT plugin package, docs, CHANGELOG, PRIVACY, TERMS, and the marketplace manifest.
- Commit it with your usual conventions (no co-author lines), then push:

```bash
cd ~/Developer/claude-in-codex
git status
git push origin main
```

Pushing also publishes `PRIVACY.md` and `TERMS.md`, which the ChatGPT plugin listing links to.

## 2. Repository metadata (search and discovery)

The GitHub description and topics feed GitHub search, topic pages, and Google's snippet for the repo.
- **Current description:** "Connect Claude Code and OpenAI Codex for AI coding, code review, pair programming, and multi-agent workflows. Zero-dependency Python CLI."
- **Current topics:** 7: ai-coding, claude-code, cli, code-review, codex, multi-agent, python.

The commands below raise the topics to 20 and add the homepage. Optionally, also use a more search-friendly description:

```bash
gh repo edit prashan-s/claude-in-codex --description "Use Claude Code from OpenAI Codex: delegate tasks with verified results, Claude reviews, Claude↔Codex pair programming, and Claude/Codex/Gemini councils with Haiku/Sonnet/Opus model routing."
```

```bash
gh repo edit prashan-s/claude-in-codex \
  --homepage "https://github.com/prashan-s/claude-in-codex#readme" \
  --add-topic claude-code --add-topic codex --add-topic openai-codex --add-topic anthropic \
  --add-topic claude --add-topic ai-agents --add-topic coding-agent --add-topic multi-agent \
  --add-topic agent-skills --add-topic codex-skills --add-topic llm --add-topic code-review \
  --add-topic pair-programming --add-topic developer-tools --add-topic cli --add-topic gemini-cli \
  --add-topic prompt-engineering --add-topic model-routing --add-topic automation --add-topic python
gh repo edit prashan-s/claude-in-codex --enable-discussions --enable-issues --enable-wiki=false
```

GitHub allows at most 20 topics; the list above is exactly 20.

- **Social preview.** In Settings → Social preview, upload a 1280×640 PNG with the title, the one-line value proposition, and the Claude, Codex, and Gemini names. This image appears on X, LinkedIn, Slack, and Medium link cards.
- **Pin the repo** on your GitHub profile.

## 3. Protect `main`

```bash
gh api -X PUT repos/prashan-s/claude-in-codex/branches/main/protection \
  -F required_status_checks.strict=true \
  -f 'required_status_checks.contexts[]=Build and check package' \
  -F enforce_admins=false -F required_pull_request_reviews=null -F restrictions=null
```

Add the test-matrix check names once the first CI run shows them.

## 4. Releases

Versions 1.0.0 and 1.1.0 are published. Version 2.0.0 introduces the indexed skill bundle.
Follow [CONTRIBUTING → Versions and releases](../../CONTRIBUTING.md#versions-and-releases):
update all four version files and the release notes together, push `main`, confirm CI,
then push an annotated version tag. The workflow publishes the Python wheel and source archive.
OpenAI plugin archives are built locally and submitted separately.

## 5. Verify the public install paths (after push)

Run each install path in a clean environment, for example a throwaway `CODEX_HOME`:

```bash
npx skills add prashan-s/claude-in-codex --list                 # one indexed skill discovered; workflow references ship inside it
codex plugin marketplace add prashan-s/claude-in-codex && codex plugin add claude-in-codex@claude-in-codex
uv tool install git+https://github.com/prashan-s/claude-in-codex && cic doctor
```

## 6. Community setup

- **Discussions:** create the categories "Show and tell" (users share delegations and workflows), "Q&A", and "Ideas".
- **Pinned issue:** a "Roadmap" issue covering a PyPI release, the Gemini API-key path, Windows support, and a skills.sh badge.
- **Good first issues:** label 3–5, such as a new task recipe, docs examples, or router keyword tuning.

## 7. Later

- **PyPI:** reserve the `claude-in-codex` name now. Publishing enables `pipx install claude-in-codex` and `uvx --from claude-in-codex cic` and widens discovery. It needs a trusted-publisher setup in the release workflow.
- **Demo GIF:** record `docs/assets/demo.gif` (60–90 s, see the X launch plan storyboard) and embed it at the top of the README with descriptive alt text.
