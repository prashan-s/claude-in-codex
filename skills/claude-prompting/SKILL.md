---
name: claude-prompting
description: Write or repair delegation briefs for Claude Code (cic run, say, pair, council) using Claude-specific prompt and context engineering, covering outcome framing, acceptance criteria, verification, context packing, and choosing a technique such as plan-then-act, prompt chaining, ReAct-style debugging, reflexion, self-consistency, or tree-of-thought. Use before delegating non-trivial work or when a Claude job came back wrong, vague, or incomplete.
metadata:
  short-description: Prompt and context engineering for Claude briefs
---

# Briefing Claude well

cic already wraps every task in a delegation contract (system prompt) and an XML brief with a technique block chosen per task kind. Your job is to supply what only you know: the outcome, the evidence, the scope, and the proof. Preview the assembled prompt with `cic run "…" --dry-run`.

## The five things every write brief needs
1. **Outcome, not steps.** Say what must be true when done ("empty cart returns 400 with error empty_cart"), not a procedure. Claude 5 models plan well. Prescribe steps only where order matters for safety.
2. **Evidence.** Include exact error text, the failing test name, logs, and the reproduction. Paraphrased symptoms produce paraphrased fixes.
3. **Where.** `--file` pointers to the 1–5 places to start. Pointers beat pasted code: Claude reads files itself, and the prompt stays small and cacheable.
4. **Done criteria.** `--done` once per criterion. Without them Claude invents its own finish line.
5. **Proof.** `--verify` commands that run in this environment. cic re-runs them and loops failures back (reflexion), so this is the single biggest quality lever.

Add `--constraint` only for real limits, such as "public API unchanged" or "no new deps".

## Claude-specific style
- **Be direct and specific.** Ask for exactly the action you want: "implement" gets code; "suggest" gets suggestions.
- **Give the reason behind each constraint.** "Don't add dependencies; this library ships to air-gapped sites" generalizes better than a bare rule.
- **Write calmly.** Modern Claude follows instructions closely. ALL-CAPS MUST and NEVER cause over-correction.
- **Say what to do rather than what not to do.** "Return plain JSON" beats "don't use markdown".
- **Order long context first, ask last.** Inline documents go first and the question or instructions at the end. cic's block order already does this.
- **Match examples to the target exactly.** Claude copies details from examples, including the bad ones. Label which aspects to imitate.
- **Control reasoning with effort, not text.** Use `--effort high|xhigh` or a higher tier instead of "think step by step". For debugging, ask for a one-sentence root cause before any edit.
- **Ground it in investigation.** "Read the code before answering; never guess about files you haven't opened" is cheap insurance (the contract includes it).

## Pick a technique
| Situation | Technique | How with cic |
|---|---|---|
| Simple, well-specified edit | Zero-shot plus a clear contract | Plain `cic run` with `--done` and `--verify`; routes to Haiku |
| Output must match a format exactly | Few-shot | `--context-file examples.md` with 1–3 examples; say what to copy |
| Bug with symptoms | ReAct hypothesis loop | `--kind debug` (observe → hypothesize → cheapest test → confirm) |
| Large or risky change | Prompt chaining, plan then act | `--plan`: Opus plans read-only, then a fresh run executes the distilled plan |
| Design choice | Tree of thoughts | `--kind plan` (2–3 options, evaluated, one chosen) or `$claude-council` |
| High-stakes answer | Self-consistency | `$claude-council` (cross-vendor) or two `cic ask` runs on different tiers |
| Unfamiliar codebase | Generated knowledge, then act | `cic ask` to map the area first, then pass the answer as `--context` |
| Failed verification or review | Reflexion | Automatic via `--verify`; manual via `cic reply <job> "<findings>"` |
| Numbers, data, transforms | Program-aided (PAL) | Ask Claude to write and run a script rather than reason in prose |
| You know the likely answer | Directional stimulus | `--context "Hint: the cache key ignores locale"` or `cic steer` mid-run |
| Low-confidence report | Active prompting | Confidence below 0.6: review with `$claude-review` or re-ask before accepting |
| Same brief keeps failing | Automatic prompt engineering (APE) | `cic ask "Critique this brief and rewrite it: …"`, then keep the winner as a template |

Full technique notes, with sources, are in [references/techniques.md](references/techniques.md).

## Context engineering checklist
- **One task per job.** Unrelated asks go in separate jobs.
- **Fresh session for new work.** Use `cic reply`, `say`, or `--fork` only to continue the same thread of work. Stale context poisons new tasks.
- **Distill between phases.** Pass plans and summaries, not transcripts.
- **Keep big references in files.** Inline at most about 20 KB; point to the rest.
- **Don't repeat the contract.** cic adds date, git state, the working agreement, and the output schema automatically.

Details: [references/context-engineering.md](references/context-engineering.md). XML block library for custom prompts (sessions, bus messages, council questions): [references/brief-blocks.md](references/brief-blocks.md).

## When a job came back wrong
Diagnose before retrying. [references/antipatterns.md](references/antipatterns.md) lists the usual causes and fixes: a vague outcome, missing evidence, no verify, mixed asks, a wrong tier, an over-stuffed context, and an unrunnable check. Then use `cic reply <job> "<the specific correction>"`. It keeps context, so send only the delta.
