# Prompting techniques for delegated Claude work

A mapping of the techniques catalogued at https://www.promptingguide.ai/techniques onto cic workflows. Each entry covers what the technique is, when it pays off for coding delegation, and how to apply it.

## Zero-shot prompting
**What:** a direct instruction with no examples.
**When:** well-specified, low-ambiguity tasks; most Haiku-tier work.
**How:** `cic run "<outcome>" --done … --verify …`. The contract plus clear criteria is enough. Adding examples here only spends tokens.

## Few-shot prompting
**What:** show 1–5 input/output examples so the model infers the pattern.
**When:** the output format or style must match exactly: commit message conventions, a codegen pattern, a test naming scheme, a migration template.
**How:** put the examples in a file and pass `--context-file examples.md`. State which aspects to copy (structure, naming) and which to ignore (specific values). Claude imitates details faithfully, so every example must be correct.

## Chain-of-thought (CoT)
**What:** elicit intermediate reasoning before the answer.
**When:** multi-step logic, root-cause analysis, tricky algorithms.
**How:** current Claude models think adaptively, so raise `--effort` (high or xhigh) or the tier rather than writing "think step by step". Ask for a visible checkpoint where it matters: "state the root cause in one sentence before editing". The `fix` and `debug` templates do this.

## Meta prompting
**What:** structure-first prompts that describe the shape of the task and answer.
**When:** always. This is what cic's XML brief is (`<task>`, `<context>`, `<acceptance_criteria>`, `<verification>`, `<constraints>`, `<approach>`), together with the enforced JSON report schema.

## Self-consistency
**What:** sample several independent answers and take the consensus.
**When:** high-stakes or ambiguous answers: architecture choices, "is this safe", diagnosis of a rare failure.
**How:** `cic council "<question>"` asks Claude, Codex, and Gemini independently, then a moderator reconciles them by checking evidence rather than counting votes. A cheaper option is two `cic ask` runs on different tiers, accepting only what they agree on.

## Generated knowledge
**What:** have the model first generate the relevant facts, then answer using them.
**When:** unfamiliar or large codebases where the change depends on how things are wired.
**How:** start with `cic ask "Map how auth tokens flow from login to API middleware; cite files"` (Haiku or Sonnet, read-only). Then delegate the change with the answer passed as `--context`. The built-in "orient first" step does a light version of this.

## Prompt chaining
**What:** split a task into sequential prompts, each consuming the previous step's distilled output.
**When:** large or risky changes, and multi-stage workflows (plan → implement → review).
**How:** `cic run --plan` (Opus plan → fresh execution run with the plan), or chain manually: `cic ask` → `cic run` → `cic review`. Pass distilled outputs (plans, findings) between steps, never whole transcripts.

## Tree of thoughts (ToT)
**What:** explore several solution branches, evaluate them, and keep the best.
**When:** design decisions with real trade-offs.
**How:** `--kind plan` asks for 2–3 materially different approaches evaluated against the acceptance criteria. Use `cic council` when you want the branches to come from different model families.

## Retrieval-augmented generation (RAG)
**What:** retrieve relevant documents into the context.
**When:** the task depends on specs, API docs, or decisions that live outside the code.
**How:** use `--context-file spec.md` for small documents. For large ones, point to them (`--add-dir ../docs`, or name the files) so Claude reads only what it needs. Prefer primary sources.

## Automatic reasoning and tool use (ART)
**What:** the model picks and calls tools as part of reasoning.
**When:** built in. Claude Code chooses its own tools.
**How:** make sure the tools it needs are allowed. Write tasks use `auto` mode; add `--allow 'Bash(<cmd> *)'` for anything a classifier or allowlist would block. Permission denials show up in the report.

## Automatic prompt engineer (APE)
**What:** use a model to generate and select better instructions.
**When:** a recurring delegation keeps underperforming.
**How:** `cic ask "Here is a brief and the bad result it produced. Diagnose the brief's failure modes and rewrite it."` Keep the improved brief as a reusable template (e.g. in your repo's AGENTS.md).

## Active-prompt
**What:** spend extra effort where the model is uncertain.
**When:** the report's `confidence` is low, or `assumptions` contains guesses about important behavior.
**How:** below about 0.6, get a review (`cic review` or a council) before accepting. Alternatively, answer the open questions via `cic reply`.

## Directional stimulus prompting
**What:** add a hint that steers the model toward the right region of the solution space.
**When:** you already suspect the cause or the right approach.
**How:** `--context "Hint: the bug appeared after the switch to UTC timestamps"`, or mid-run with `cic steer <job> "Check the retry loop in client.py first"`. Hints are cheap and powerful, but label them as hints so they don't become hard constraints.

## Program-aided language models (PAL)
**What:** have the model write and execute code for computation instead of reasoning in text.
**When:** counting, data transformation, numeric checks, bulk analysis.
**How:** say "write and run a script to compute X; report the script's output". Claude Code can run it.

## ReAct
**What:** interleave reasoning with actions and observations.
**When:** debugging and investigation.
**How:** `--kind debug` is a ReAct template. Observations come first, then ranked hypotheses, then the cheapest discriminating experiment, then a conclusion grounded in evidence. Add `--read-only` to stop at a diagnosis.

## Reflexion
**What:** feed failure feedback back to the agent so it can self-correct.
**When:** every write task with a checkable outcome.
**How:** this is automatic with `--verify`. Failing check output goes back to the same session as a repair turn, and the model escalates after repeated failure. Manually, `cic reply <job> "<review findings>"` does the same. `$claude-in-codex pair` automates it with a reviewer agent.

## Multimodal CoT
**What:** reasoning over images plus text.
**When:** UI bugs and visual regressions.
**How:** save screenshots in the repo or a temp folder and name their paths in the brief. Claude Code can Read image files.

## Graph prompting
**What:** prompting over graph-structured data.
**When:** rarely needed for coding delegation. For dependency questions, ask Claude to compute the graph with a script (PAL) rather than describe it.
