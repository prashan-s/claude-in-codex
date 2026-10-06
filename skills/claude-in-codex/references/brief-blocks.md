# Brief blocks

cic builds `cic run` briefs automatically. Use these blocks when you write free-form prompts for `cic say`, `cic bus` messages, `cic council` questions, or `cic run --task-file`. Wrap each one in the XML tag shown, and use only the blocks the task needs.

## task
```xml
<task>
The concrete outcome and where it applies. Include exact error text or failing test names.
</task>
```

## context
```xml
<context>
Facts the agent cannot discover itself: product decisions, constraints from other teams, versions, prior attempts and why they failed.
</context>
```

## acceptance_criteria
```xml
<acceptance_criteria>
- Observable condition 1
- Observable condition 2
</acceptance_criteria>
```

## verification
```xml
<verification>
These commands must pass: `uv run pytest -q tests/test_x.py`
</verification>
```

## constraints
State each constraint together with its reason:
```xml
<constraints>
- Keep the public API of client.py unchanged: three services import it.
</constraints>
```

## output_shape
For free-text answers such as sessions, councils, and asks:
```xml
<output_shape>
Lead with the answer in one or two sentences, then up to five bullets of evidence with file:line references. Under 250 words.
</output_shape>
```

## grounding
For reviews, research, and diagnosis:
```xml
<grounding>
Base every claim on code you read or commands you ran, citing file:line. Label inferences as inferences. Say what remains unknown.
</grounding>
```

## options
Tree-of-thought style, for design questions:
```xml
<options>
Propose two or three materially different approaches. Evaluate each against: correctness, migration risk, effort, reversibility. Recommend one and say what would change your mind.
</options>
```

## follow_up
For `cic reply` and `cic say`, send only what changed:
```xml
<follow_up>
The orchestrator ran the tests: test_refund_partial fails with "AssertionError: 50 != 45". Fix the rounding, keep the other tests green.
</follow_up>
```

## Assembly checklist
1. Start with `<task>`.
2. Add `<context>` only for facts the agent can't discover.
3. Use `<acceptance_criteria>` plus `<verification>` for anything that writes code.
4. Add `<constraints>` with reasons, and only the real ones.
5. Use `<output_shape>` for free text, and `<grounding>` for analysis.
6. Re-read the prompt and delete anything that doesn't change the result.
