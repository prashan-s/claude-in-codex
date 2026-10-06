# X (Twitter) launch plan

**Goal:** stars, real installs (the skills.sh ranking depends on them), and feedback from people who use both Claude Code and Codex.

**Positioning in one line:** "Codex delegates to Claude Code, and the result comes back verified."

**Audience:**
- developers using Codex or Claude Code daily
- AI-tooling and agent builders
- devrel and indie-hacker circles that share dev tools

## Assets to prepare first

| Asset | Spec | Notes |
|---|---|---|
| Demo GIF or video | 45–75 s, 1280×720, captions burned in | Storyboard: (1) Codex prompt "Use $claude-in-codex delegate to fix the failing test…" → (2) `cic: job … started · fix · sonnet/high` → (3) `cic steer …` mid-run → (4) `DONE ✓ verified` with "Checks re-run by cic: PASS" → (5) `git diff` |
| Council screenshot | terminal, dark theme, cropped | Synthesis plus "gemini: unavailable" line; shows honest degradation |
| Bus transcript screenshot | `cic bus log t-cc --brief` | Codex → architect (Claude) → implementer (Claude) → back |
| Routing card | simple 3-row table image | Haiku / Sonnet / Opus with example tasks |
| Social preview | 1280×640 | Same image as the GitHub social preview |

## Launch thread

Every post is under 280 characters (checked with `len()`). Post 1 carries the link and the GIF.

1. I made OpenAI Codex delegate coding tasks to Claude Code, and verify the result. Not "I think it's fixed": cic re-runs your tests itself and sends failures back to Claude until they pass. Open source, MIT. github.com/prashan-s/claude-in-codex 🧵
2. In Codex, say: "Use $claude-in-codex delegate to fix the failing test and verify with pytest." Codex hands it off, Claude finds the root cause and adds a regression test, cic re-runs pytest, and Codex gets back DONE ✓ verified.
3. It picks the model per task instead of maxing out: Haiku for lookups and renames, Sonnet for everyday work, Opus only for architecture, security, race conditions, or after two failed attempts.
4. Second opinions in one command. Claude reviews Codex's diff. Codex reviews Claude's in a pair loop until it approves. Or ask a council: Claude, Codex, and Gemini answer in parallel and Opus moderates, checking disputed facts against your repo.
5. You stay in control while it works: `cic status`, `cic steer <job> "reuse RetryPolicy"`, `cic model <job> opus`, `cic cancel`. Steering lands at Claude's next tool step, with no restart.
6. Agents can talk to each other over a message bus. In testing, one message to an "architect" Claude made it consult an "implementer" Claude over the bus and report back on its own. Claude↔Claude and Claude↔Codex, from the CLI.
7. Prompting is built in. Every task type applies promptingguide.ai techniques: ReAct for debugging, Reflexion on failed checks, tree of thoughts for plans, councils for self-consistency. `cic improve` turns a vague ask into a precise brief.
8. Install in about 2 minutes: git clone, then ./install.sh. Or: npx skills add prashan-s/claude-in-codex. Python standard library only. Works with your existing Claude Code login.
9. If you use both Claude Code and Codex, I'd love your feedback. What should it delegate next? ⭐ if it's useful: github.com/prashan-s/claude-in-codex

## Schedule

| When | Post |
|---|---|
| T−3 days | Teaser: 15 s clip of `cic steer` changing Claude's plan mid-task. "Shipping something for Codex + Claude Code users this week." |
| Launch day, Tue or Wed, 9–11am US Pacific | Thread above; pin it. Reply to every comment in the first 2 hours. Quote-post the GIF from your main account. |
| Day +1 | Mini-thread on how routing picks Haiku, Sonnet, or Opus, with the routing card. |
| Day +2 | Council demo: one hard question, three agents, one moderated answer, plus the screenshot. |
| Day +3 | Medium article link: "How to use Claude Code inside OpenAI Codex". |
| Day +5 | Technical insight post: "Headless Claude Code reports some auth failures as subtype=success with is_error=true. Here's how cic classifies results strictly." Good for builder engagement. |
| Day +7 | Recap: stars, installs, top feedback, next roadmap item. |

## Engagement rules

- Lead with the demo, not the architecture. Put details in replies.
- Tag sparingly and only where relevant (e.g. replying in threads about Claude Code or Codex workflows). Don't spam official accounts.
- Hashtags: at most 1–2 per post (#ClaudeCode, #Codex). X favors plain text plus media.
- Answer "why not just use X?" with specifics: verification re-runs, routing, steering, the council.
- Reply to issues and DMs within a day during launch week; turn good questions into FAQ entries.

## Metrics

| Metric | Week-1 target |
|---|---|
| Thread impressions / link clicks | 20k / 400 |
| GitHub stars | 100 |
| skills.sh installs | 50 |
| Issues or discussions opened by users | 10 |
| Medium reads | 500 |

Review on Day +7. Double down on whichever post type drove the most clicks.
