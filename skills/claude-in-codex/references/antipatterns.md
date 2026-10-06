# Delegation anti-patterns and fixes

| Anti-pattern | What you see | Fix |
|---|---|---|
| Vague outcome ("look at this and fix it") | It fixes something, maybe not the thing you meant | State the observable outcome; add `--done` |
| Paraphrased symptoms | Plausible fix for the wrong bug | Paste exact error text, failing test name, reproduction |
| No proof | "DONE (not independently verified)" | Add `--verify` with a command that runs in this environment |
| Unrunnable check | BLOCKED: "verification command cannot run" | Use the project's runner (`uv run pytest`, `npm test`, `make test`) or a venv path |
| Mixed asks ("fix X, update docs, and refactor Y") | Partial results, blurry report | One job per outcome; run them in parallel with `--worktree` |
| Pasted whole files | Slow, expensive, worse focus | `--file` pointers; inline only decisive excerpts |
| ALL-CAPS MUST and NEVER | Over-cautious or brittle behavior | State the rule calmly, with its reason |
| "Think harder" | More tokens, same mistakes | Better contract plus `--effort high`, or `--tier deep` |
| Opus for everything | High cost, no quality gain on routine work | Let routing pick; escalation handles failures |
| Switching models every turn | Cache rebuilds, inconsistent voice | One model per session; switch only to escalate |
| Re-sending the full brief on follow-ups | Duplicated context, drift | `cic reply <job> "<delta only>"` |
| Relaying Claude's claims as facts | Unverified "tests pass" in your report | Quote only the "Checks re-run by cic" section as verified |
| Answering permission denials by guessing | Same denial loop | Re-run with `--access auto` or a precise `--allow 'Bash(<cmd> *)'` |
| Long session for unrelated work | Old assumptions leak into new task | New job or session; `--fork` for alternatives |
| Delegating from a delegated agent | Exit 5, depth limit | Do the work directly; only the top-level orchestrator delegates |

## Repair loop for a bad result
1. Classify the failure: wrong target, incomplete, unverified, blocked, or low quality.
2. Find the missing ingredient: outcome, evidence, pointers, criteria, proof, permissions, or tier.
3. Send the smallest correction: `cic reply <job> "<what is wrong and what done looks like>"`.
4. If the same brief fails twice, rewrite it (APE): `cic ask "Critique and rewrite this brief: …"`.
