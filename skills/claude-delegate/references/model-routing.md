# Model routing

cic picks a model with a deterministic, explainable heuristic. `cic route "<brief>"` shows the decision and the reasons behind it. Override when you know better; otherwise trust the router and its escalation ladder.

## Tiers

| Tier | Claude Code alias | Price (in / out per MTok) | Use for |
|---|---|---|---|
| fast | `haiku` (Haiku 4.5) | $1 / $5 | lookups, "what does X do", summaries, typos, renames, formatting, commit messages, boilerplate |
| balanced (default) | `sonnet` (Sonnet 5.5) | $2 / $10 | features with clear scope, bug fixes, tests, refactors, normal reviews and research |
| deep | `opus` (Opus 5.5) | $4 / $20 | architecture and design, concurrency/races, security, ambiguous root causes, large multi-module work, anything that failed lower down |
| (explicit only) | `fable` (Fable 5.1) | $10 / $50 | never auto-selected; pass `--model fable` when the user asks for it |

cic uses aliases, so each tier follows the newest model in its line.

## How the router decides
1. **Kind** (inferred, or `--kind`): ask, explain, chore, docs, test, implement, fix, refactor, review, research, debug, plan.
2. **Score**: each kind has a base score.
   - Harder signals add to it: architecture, distributed, race condition, deadlock, security, auth, performance, migration, "across the codebase", flaky, production incident.
   - Easier signals subtract: typo, rename, simple, one-line, summarize, commit message.
   - Long briefs and many files in scope add a little.
3. **Tier**: below 2 is haiku, below 6 is sonnet, otherwise opus.
4. **Effort**: follows Claude Code's guidance.
   - Haiku gets no effort setting; it doesn't support one.
   - Sonnet uses `medium` for clear-scope work (features, tests, docs) and `high` for fixes, debugging, refactors, reviews, and plans.
   - Opus uses `high`, or `xhigh` for hands-on security and concurrency work. `max` is never chosen automatically.
5. **Fallback** when a model is overloaded or unavailable:
   - haiku falls back to sonnet. Haiku 4.5's retirement date is "not sooner than Oct 15, 2026", so this matters.
   - sonnet falls back to opus.
   - opus falls back to sonnet.
6. **Access**:
   - Questions are read-only.
   - Write work uses `auto` mode on Sonnet and Opus.
   - Write work on Haiku uses the `edit` allowlist, because Claude Code silently drops auto mode on Haiku.

## Escalation ladder (automatic, write tasks only)
- **Attempt 1:** the routed model does the work.
- **Attempt 2:** a check failed or the work is incomplete. The same model repairs it on the same session, so the prompt cache stays warm.
- **Attempt 3:** it failed again. cic switches the live session one tier up (haiku → sonnet → opus) and repairs once more.
- If Claude reports outright `failed`, cic escalates immediately.
- Escalation is off when you pinned `--model`. Re-enable it with `--escalate`.
- It never goes past opus unless you add `--allow-fable`.

## Cost rules of thumb
- Every model switch inside a session rebuilds the prompt cache once. Pick the model up front instead of switching back and forth.
- A run carries roughly 20–25k tokens of Claude Code context before your brief; prompt caching makes repeat turns cheap. `--lean` (safe mode: no plugins, hooks, or CLAUDE.md) trims about 20%, at the cost of project instructions.
- Cost figures in reports are Claude Code's client-side estimates at list price. Subscription plans bill differently.
- Use `--plan` for large changes. A short Opus planning pass plus a Sonnet execution pass is usually cheaper and better than Opus doing everything.

## When to override
- The user names a model: pass it.
- You already know the task is subtle (e.g. you just watched Sonnet fail at it): `--tier deep`.
- A trivial edit the router over-scored: `--tier fast`.
- Exploratory chat in `cic say`: Sonnet by default, Opus for design partners, Haiku for quick codebase lookups.
