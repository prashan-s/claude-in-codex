# Prompt audit: every cic task against promptingguide.ai

This document records how each prompt that `cic` sends applies the techniques catalogued at
[promptingguide.ai](https://www.promptingguide.ai/techniques). It covers the before/after of the improvement
pass and the iterations that produced it. Tests in `tests/test_cic.py::TechniqueTests` pin the markers, so
regressions fail CI. `cic run --dry-run` prints the techniques a given brief applies.

## Method

1. **Inventory.** We listed all 26 prompt surfaces: 3 contracts, 11 task-kind approaches, 3 output shapes,
   the brief blocks, 5 follow-up messages, review, 2 council prompts, 2 pair prompts, chat opening, bus
   addendum, and the improve prompt.
2. **Grounding.** We read the guide's pages on prompt elements, tips, few-shot, CoT, self-consistency,
   generated knowledge, prompt chaining, ToT, ReAct, Reflexion, PAL, active-prompt, DSP, APE, meta prompting,
   and multimodal CoT, and extracted the mechanism behind each technique (not just its name).
3. **Iteration 1** (gap analysis, then upgrades): each surface was scored against the techniques that fit its
   job, and the gaps were fixed. See the matrix below.
4. **Iteration 2** (APE on our own prompts): Claude Sonnet critiqued the upgraded templates against the same
   technique list, and the defensible suggestions were applied. See the end of this document.
5. **Verification.** Marker tests run for every kind, plus end-to-end tests with the fake Claude binary and
   live runs against real Claude Code.

## Prompt elements and tips (applied everywhere)

The guide's four elements are **instruction, context, input data, and output indicator**. Every brief now has
all four:

| Element | Where it comes from |
|---|---|
| Instruction | `<task>` (the orchestrator's outcome statement) + `<approach>` (per-kind method) |
| Context | `<context>`: cwd, date, git state, file pointers, `--context`, small inlined files |
| Input data | exact errors and logs in the task, `<examples>`, `<images>`, `<hints>` |
| Output indicator | JSON schema for structured kinds; `<output>` word-budgeted shape for free-text kinds (new) |

From the tips page:
- **Specificity:** word budgets and section lists replaced "concisely" (explain, ask, research).
- **Directive framing ("to do, not to don't"):** the contracts were rewritten from "Do not commit…" to
  "Leave changes uncommitted… commit only when the task asks". Prohibitions remain only where the positive
  form loses meaning.
- **Start simple:** zero-shot plus contract stays the default. Heavier techniques are opt-in or triggered.

## Matrix: task kinds

| Kind | Before | After (techniques) |
|---|---|---|
| implement | orient, plan, test, self-review | **generated knowledge** (list and confirm the 3–5 facts the change depends on), CoT plan, **ReAct** test loop, self-review |
| fix | reproduce first, root cause sentence | + **ToT-lite**: keep 2–3 candidate causes when the first doesn't hold |
| debug | observe/hypothesize/test | explicit **ReAct** loop (Observe, Hypothesize, Experiment, Conclude), **PAL** probe scripts, fact/inference split |
| refactor | safety net, small steps | + **generated knowledge**: write down invariants first |
| test | list behaviors, determinism | + "each test can fail for the right reason" (mutation-style **reflexion**) |
| docs | grounded, runnable examples | + default audience, read-before-describe |
| chore | exact change | + **few-shot from the repo**: recent commit subjects are auto-injected for commit, changelog, and PR text |
| research | breadth-first, facts vs inferences | **prompt chaining** in one prompt (Evidence step, then Answer step), fixed `<output>` sections |
| plan | 2–3 options, choose | **ToT** with viability rating (strong / possible / ruled out) and pruning |
| explain / ask | "answer concisely" | `<output>`: 1–3 sentence answer, ≤5 cited bullets, ≤250 words; **PAL** for counting and data |
| review | grounded findings, dig deeper | + **CoT trace** per finding (input → path → wrong outcome), dropping candidates that don't survive |

## Matrix: cross-cutting mechanisms

| Technique (promptingguide.ai) | Mechanism in the guide | How cic applies it |
|---|---|---|
| Meta prompting | structure-first, abstract templates | one XML schema for every brief; JSON schemas for reports |
| Reflexion | evaluator signal plus verbal self-reflection stored in memory for the next trial | `--verify` is the evaluator; failures return to the **same session** (memory) with a mandatory two-sentence reflection (**new**); the same applies to `continue` and pair findings |
| Active-prompt | spend effort where uncertainty is highest | **new:** a "done" report below confidence 0.5 triggers one targeted *uncertainty pass* (name the doubts, resolve each with tools) |
| Self-consistency | sample several reasoning paths and take the consistent answer | `cic council`. **New:** repeated members (`claude:sonnet,claude:sonnet,claude:sonnet`) give classic same-model sampling, and the moderator prefers convergence when the evidence is balanced |
| Tree of thoughts | generate, evaluate (sure/maybe/impossible), search | `plan` viability ratings and pruning; ranked hypotheses in `debug`/`fix`; council members must state the strongest **ALTERNATIVE** they rejected (**new**) |
| Prompt chaining | subtask outputs feed the next prompt | `--plan` (Opus plan → fresh execution run), pair loops, research Evidence → Answer; the linter now **suggests `--plan`** for large Opus-tier changes |
| Generated knowledge | generate facts first, then answer with them | implement and refactor "facts/invariants first"; `cic improve` inspects the repo before rewriting a brief |
| ReAct | thought → action → observation | Claude Code's tool loop, made explicit in `debug`/`fix`/`test` |
| PAL | the model writes code, the interpreter computes | contracts and read kinds: compute counts, dates, and data with scripts |
| Directional stimulus | hints steer the target model | **new `--hint`**: a `<hints>` block labeled "likely but unverified"; `cic steer` for mid-run hints |
| Few-shot | demos fix format and label space | **new `--example`** (text or `@file`), labeled "match format and style, not content"; automatic repo examples for message-writing chores |
| APE | an LLM generates and selects instructions | **new `cic improve`**: critiques a brief against these principles, grounds it in the repo, returns a rewritten brief plus a ready-to-run command |
| Multimodal CoT | rationale from image and text first, then the answer | **new `--image`** on run, ask, and say: images go as content blocks, with an instruction to first describe what matters, then act |

## Follow-up messages

| Message | Upgrade |
|---|---|
| `verification_failed` | evaluator output plus **reflection step** before repair |
| `continue` | remaining items plus **reflection step** |
| `uncertainty_check` (new) | active-prompt pass: list doubts, resolve them with tools, adjust confidence |
| `findings_for_driver` | navigator findings plus **reflection step** |
| `REPORT_MISSING`, `follow_up` | unchanged (already minimal and specific) |

## Iteration 2: APE on our own prompts

Claude Sonnet (high effort, read-only) was asked to critique `src/cic/prompts.py` against the same technique
list and return the highest-impact concrete improvements. The suggestions and how each was handled are
recorded below.

Run: `cic ask "<critique request>" --kind research --model sonnet --effort high` (job `cj-1006-214906-9cc0`,
39 s, about $0.18 estimated). Sonnet returned 8 suggestions. All 8 were judged defensible and applied:

| # | Surface | Suggestion (technique) | Applied as |
|---|---|---|---|
| 1 | `CONTRACT_WORK` | calibrate confidence so the active-prompt trigger is meaningful (active-prompt) | confidence anchors (0.9+ verified … below 0.5 partial); default threshold raised 0.5 → **0.7**, so "a criterion was inferred, not run" now triggers the uncertainty pass |
| 2 | `_REFLECT` | reflections were generic, so a retry could repeat a failed fix (Reflexion memory) | name the failing check and hypothesis; recall tried approaches and don't repeat a failed one; flag pre-existing failures |
| 3 | review method | findings were traced but never challenged (self-verification) | explicit refutation step: look for guards, callers, tests, or config before keeping a finding |
| 4 | council | an uncited majority could win (self-consistency) | majority wins ties only with ≥2 independent citations; members state the observation that would change their answer |
| 5 | `cic improve` | single rewrite with no selection (APE) and no example (few-shot) | two candidate rewrites scored on a 4-part rubric, the winner returned; one weak→strong example; inferred criteria marked "(proposed)" |
| 6 | `docs` approach | the only write kind with no execution check (PAL) | run every documented command and snippet; grep every named path and flag |
| 7 | `implement` approach | "plan briefly" was vague; no design fork (specificity, ToT) | at most a five-line plan naming files and how each is verified; one-sentence comparison of two designs when the choice is hard to reverse |
| 8 | `OUTPUT_SHAPE` | described a format but showed none (few-shot) | format example for explain and ask; research trade-offs as one bullet per option, uncited claims marked "(unverified)" |

The reviewer's open questions were resolved: the tests were updated together with the wording, `TECHNIQUES`
gained entries for items 5–8, and the config threshold matches the new anchors.

## Coverage after both iterations

Every task kind maps to at least two techniques (`TECHNIQUES`). All 16 techniques from the guide's list
that apply to coding delegation are used somewhere: zero-shot, few-shot, CoT, meta prompting,
self-consistency, generated knowledge, prompt chaining, ToT, RAG (file pointers and context files), ART
(tool allowlists), APE, active-prompt, DSP, PAL, ReAct, Reflexion, and multimodal CoT. Graph prompting is
the only one left out: coding delegation has no graph-structured input.
