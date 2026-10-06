# How to Use Claude Code Inside OpenAI Codex, and Get Verified Results

*An open-source toolkit that lets Codex delegate to Claude Code, pick the right Claude model for each task, and run Claude, Codex, and Gemini together.*

**Suggested Medium tags:** Claude, OpenAI, AI Agents, Software Development, Developer Tools
**Canonical link:** https://github.com/prashan-s/claude-in-codex
**Hero image:** the repository social preview (1280×640)

---

If you write software with AI agents, there's a good chance you have two of them open: OpenAI's Codex and Anthropic's Claude Code. Both are strong, and they are better at different things. But they don't know about each other. You copy context from one window to the other, paste a diff, and re-explain the bug. Then you get the most dangerous sentence in AI-assisted coding: *"That should fix it."*

**Claude in Codex** connects them. From inside Codex you can hand a task to Claude Code and get back a result that was independently verified. You can also ask Claude to review Codex's work, run the two agents as a pair, or put a hard question to a panel of Claude, Codex, and Gemini.

This article covers three things: how to set it up, how to use it day to day, and what the design achieves.

## What it is

Claude in Codex is two things:

1. **Nine Codex skills**, such as `$claude-delegate`, `$claude-review`, `$claude-pair`, and `$claude-council`. They teach Codex when and how to work with Claude.
2. **`cic`**, a small command-line tool written in standard-library Python. It runs Claude Code headless, tracks the job, re-checks the work, and returns a compact report that Codex can act on.

You don't have to learn `cic` to use it. You talk to Codex the way you normally do, and the skills handle the rest.

## Setup in two minutes

You need macOS or Linux, Python 3.10 or newer, Claude Code logged in, and Codex.

```bash
git clone https://github.com/prashan-s/claude-in-codex.git
cd claude-in-codex
./install.sh
cic doctor
```

Restart Codex, and you're done.

One detail is worth understanding. Codex runs commands in a sandbox, and inside that sandbox Claude Code can't read its own login. It reports "Not logged in" even when you are. The installer adds a small Codex rule that lets bare `cic …` commands run outside the sandbox. That's a deliberate trade-off. If you'd rather approve each run, install with `--no-rules`.

## Five ways to use it

### 1. Delegate a fix, and get proof

In Codex:

> Use $claude-delegate to fix the failing test in this repo. Verify with `python3 -m unittest -q`.

Here is what happened when I ran exactly this against a small repository where `add()` subtracted:

- Codex read the skill, reproduced the failure itself, and wrote a precise brief that included the exact assertion error.
- It started a background Claude job and polled it.
- Claude (routed to Sonnet) found the bug, fixed it, and reported what it ran.
- **cic re-ran the tests itself**, and they passed.

```
## DONE ✓ verified · fix · cj-1006-212632-5cc2
model sonnet/high · attempt 1/3 · 11s · ~$0.10 est.
add() in calc.py used `a - b`; changed it to `a + b`. The full unittest suite now passes (2 tests)…
### Checks re-run by cic (ground truth)
- [PASS] `python3 -m unittest -q`
```

That last section is the point. If the checks fail, the failure output goes back to *the same* Claude session. Claude has to reflect first: what went wrong, and what it already tried. Then it repairs. If it fails again, cic moves it up one model tier and tries again. You get a verified result, or a precise explanation of why there isn't one.

### 2. Plan first for big changes

For risky work, add `--plan`:

> Use $claude-delegate with --plan to move session storage to Redis behind a feature flag.

Claude Opus explores the code read-only and produces a plan: options it considered, the one it chose, ordered steps, and risks. Then a *fresh* run executes that plan on the routed model. The executor gets the distilled plan, not a long exploration transcript. This is prompt chaining, and it is usually both cheaper and better than one giant run.

### 3. Second-opinion code reviews

> Use $claude-review to review my uncommitted changes adversarially.

You get severity-ranked findings with file and line references. Before reporting a finding, the reviewer must trace it step by step and then *try to refute it*: look for a guard, a caller check, or a test that prevents it. Fewer false alarms reach you.

### 4. Pair programming between agents

> Use $claude-pair: Claude implements idempotency keys, Codex reviews until it approves.

Claude writes the change, and cic re-runs your checks. Codex then reviews the *actual diff*, not Claude's description of it. In my test, the Codex navigator re-ran all seven tests on its own and approved in round one. When the reviewer requests changes, the findings go back to the driver's session for the next round.

### 5. A council for hard decisions

> Use $claude-council to choose between Redis streams and SQS for our job queue.

Claude, Codex, and Gemini answer the same question independently. A moderator (Claude Opus by default) then reconciles the answers. It checks disputed facts against your repository and trusts a majority only when the majority cites evidence. If a member is unavailable, the council says so and carries on. On my machine, Gemini CLI's free login tier no longer works, and the report said exactly that.

## The right model for each task

Not every task needs the biggest model. cic routes automatically:

| Model | Gets |
|---|---|
| Haiku | "where is X", summaries, typos, renames, commit messages |
| Sonnet | everyday features, fixes, tests, refactors, reviews |
| Opus | architecture, race conditions, security, ambiguous root causes, or anything that already failed twice |

Effort levels follow the same logic. You can always override the choice, and `cic route "<task>"` explains each decision. One practical note: switching models mid-conversation rebuilds the prompt cache, so cic picks the model up front and escalates only after repeated failure.

## Prompt engineering you don't have to write

Most delegation failures are prompt failures: a vague goal, no definition of done, no way to check. So every task type in cic applies a technique from the [Prompt Engineering Guide](https://www.promptingguide.ai/):

- **ReAct** for debugging: observe, hypothesize, run the cheapest experiment, conclude.
- **Reflexion** for failures: check output plus a mandatory reflection, in the same session.
- **Tree of thoughts** for plans: two or three options, each rated strong, possible, or ruled out.
- **Generated knowledge** for implementation: list and confirm the facts the change depends on.
- **Self-consistency** for decisions: councils, including several samples from the same model.
- **Active-prompt** for doubt: a "done" report with low confidence gets one targeted pass to resolve it.

There's also an **automatic prompt engineer**. Give `cic improve` a lazy request like "fix the bug in the duration thing", and it inspects the repo and drafts two rewrites. It scores both and returns the winner, ready to run. In my test it located the exact faulty line, `_UNITS["h" if unit == "m" else unit]`, and stated the expected values ("1h30m" should be 5400, not 7200). It also proposed the right test command and marked the criteria it had inferred as "(proposed)". Running that improved brief produced a verified fix in 13 seconds. Claude even confirmed that its new tests failed on the old code.

## Agents talking to agents

Under the hood there's a simple message bus: inboxes on disk with atomic delivery. Any agent can join. You can turn Claude, Codex, or Gemini into a long-running agent that answers messages:

```bash
cic serve start architect --agent claude:haiku --role "Consult the implementer before answering."
cic serve start implementer --agent claude:haiku
cic bus ask --from codex --to architect "Ask the implementer which operator add() uses." --wait 240
```

In my test I sent the question from the command line, posting as the `codex` address. The transcript shows the architect asking the implementer and the answer coming back up the chain. That's two Claude agents coordinating on their own over the bus. A Codex agent can send the same message itself, and the same mechanism connects Claude and Codex, or all three vendors.

## What you can achieve

- **Ship fixes with proof attached.** Every delegated change comes with checks that cic re-ran itself, not just Claude's say-so.
- **Spend less.** Most work runs on Haiku and Sonnet, and Opus is reserved for the hard parts.
- **Catch more bugs before merge.** Cross-vendor reviews and pair loops put a second model family on every risky change.
- **Babysit less.** Background jobs, mid-task steering, and resumable sessions let you keep working while Claude works.
- **Run parallel work safely.** `--worktree` gives each job its own git worktree.
- **Get better results from rough requests.** Built-in prompt engineering and `cic improve` do the briefing for you.

## Safety and honest limits

- Questions and reviews run read-only.
- Commits and pushes are blocked unless you allow them.
- Delegated agents keep side effects inside the repository and can't delegate in a loop.
- The sandbox rule is a real trade-off, explained above.
- Cost figures are Claude Code's own estimates.
- The Gemini integration has only been exercised on its failure path so far, because I couldn't log in with Gemini CLI's free tier.

## Try it

The project is MIT-licensed:

**github.com/prashan-s/claude-in-codex**

If you use both Claude Code and Codex, try one delegation with a `--verify` check and tell me what happened. Issues, ideas, and stars are all welcome.
