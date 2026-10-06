# Context engineering for delegation

Context engineering decides what information reaches the model, in what form, and when. For delegated agents it decides quality more than wording does.

## What cic already injects
- **System contract** (appended to Claude Code's prompt): the working agreement covers investigate-first, minimal diffs, root-cause fixes, honest verification, no commits, side effects confined to the repo, and status semantics. It is static text, so it stays cached across jobs, and Claude Code records it on the first request so it survives `--resume`.
- **Context block:** working directory, today's date (temporal grounding), git branch and dirty files, `--file` pointers, `--context` lines, and small `--context-file` contents.
- **Technique block per kind** (`<approach>`), plus default acceptance criteria when you give none.
- **Output contract:** a JSON schema enforced by Claude Code, so reports are always parseable.

Don't repeat these in your brief. Spend your words on facts only you have.

## Principles
1. **Minimal sufficient context.** Include what changes the decision; omit what doesn't. Exact error text, the failing test name, and the 1–5 relevant paths usually beat pages of background.
2. **Point, don't paste.** Claude Code reads files and runs searches itself. Inline only small, decisive excerpts. Inlining is capped at about 20 KB per file and 60 KB total, and larger files become pointers automatically.
3. **One task, one context.** Mixing unrelated work makes the model split attention and blurs "done". Give each job one outcome.
4. **Isolate threads of work.** A fresh job gets a fresh session. Reuse a session (`cic reply`, `cic say`) only to continue the same work. Use `--fork` to explore an alternative from the same starting point without polluting the original.
5. **Distill at boundaries.** Between phases (plan → implement → review), pass the distilled artifact: the plan, the findings, the decision. Never pass the raw transcript. `--plan` does this automatically.
6. **Stable prefix, variable suffix.** Prompt caching rewards identical leading text. Keep personas and roles fixed per session, and put per-turn specifics in the message. Avoid switching models mid-session, which rebuilds the cache.
7. **Make state explicit.** Job ids, session names, and bus threads are the durable state. Refer to them rather than restating history.
8. **Ground in time and environment.** Dates, versions, and OS matter for dependency and API questions. cic adds the date and git state. Add versions in `--context` when relevant.

## Failure modes and remedies
| Symptom | Likely cause | Remedy |
|---|---|---|
| Keeps repeating an early wrong assumption | context poisoning | new session with the corrected fact stated up front (`cic run`, or `cic reply --fork`) |
| Ignores the key file, wanders | distraction: too much or irrelevant context | trim `--context`; add `--file` pointers to the right place |
| Contradictory behavior | context confusion: conflicting instructions | keep one source of truth; remove stale constraints |
| Follows old instructions in a long session | context clash across turns | start a new session for the new direction |
| "Done" but wrong thing | outcome never stated | add `--done` criteria and `--verify` |
| Long run, little progress | task too big for one context | `--plan`, or split into sequential jobs |

## Sizing guide
- **Haiku jobs:** one or two sentences plus `--file`. Keep them tight; Haiku has a 200K context.
- **Sonnet and Opus jobs:** a paragraph of outcome plus evidence plus criteria. They have 1M context, but more context is not better context.
- **Council questions:** state the options and decision criteria explicitly so the answers are comparable.
