# Task recipes

Every command is one plain `cic` invocation. Add `--background` for anything that may take more than a few minutes, then use `cic wait <job> --timeout 300`.

## Bug fix with proof
```
cic run "Fix: POST /orders returns 500 when the cart is empty. Expected 400 with {error: 'empty_cart'}. Traceback: <paste the exact lines>" --cwd <repo> --file src/orders/api.py --verify "uv run pytest -q tests/test_orders.py" --done "Empty cart returns 400 with error empty_cart" --done "Regression test added"
```
The brief template makes Claude reproduce the bug first, state the root cause, fix it, and add a regression test.

## Feature
```
cic run "Add CSV export to the reports page: GET /reports/{id}.csv streams rows with the same columns as the JSON endpoint" --cwd <repo> --file src/reports/views.py --file src/reports/serializers.py --verify "npm test --silent" --constraint "No new dependencies"
```

## Large or risky change (plan first)
```
cic run "Migrate session storage from in-memory to Redis with a feature flag and zero-downtime rollout" --cwd <repo> --plan --verify "make test"
```
Opus explores read-only and returns a plan with options, steps, and risks. A fresh run then executes it with the routed model. The plan appears in the final report.

## Refactor
```
cic run "Refactor the payment client: extract retry/backoff into one helper used by charge() and refund(); behavior must not change" --cwd <repo> --kind refactor --verify "go test ./..."
```

## Tests only
```
cic run "Write unit tests for src/parser/tokenize.ts covering escapes, unicode, and unterminated strings" --cwd <repo> --kind test --verify "npx vitest run src/parser"
```

## Diagnose without editing
```
cic run "Why does the nightly export job hang after ~2h? Logs: <paste>" --cwd <repo> --kind debug --read-only
```
Claude runs a hypothesis loop, stops at a confirmed root cause, and describes the smallest fix without applying it.

## Quick question
```
cic ask "Where is the rate limiter configured and what are the limits?" --cwd <repo>
```

## Parallel independent tasks
```
cic run "<task A>" --cwd <repo> --worktree task-a --background
cic run "<task B>" --cwd <repo> --worktree task-b --background
cic wait <job-a> --timeout 300
cic wait <job-b> --timeout 300
```
Each job gets its own git worktree, `<repo>/.claude/worktrees/<name>`, on branch `worktree-<name>`. cic's `--verify` runs inside that worktree. Claude Code leaves the worktree locked, so after merging the branch, clean it up with:
```
git worktree unlock .claude/worktrees/<name>
git worktree remove .claude/worktrees/<name>
```

## Continue, correct, or redirect
- After it finishes: `cic reply <job> "Also handle the 404 case; keep the same tests passing"`. This resumes the same Claude session, so its context is preserved.
- While it runs: `cic steer <job> "Use the existing RetryPolicy class instead of writing a new one"`.
- Try a different approach from the same starting context: `cic reply <job> "<new direction>" --fork`.

## Permissions recipes
- Needs a package install inside the project: `--allow 'Bash(npm install *)'`
- Deterministic allowlist instead of the auto classifier: `--access edit`
- Must commit as part of the task (normally the orchestrator commits): `--allow-git-write`
- Unrestricted, only when the user explicitly accepts it: `--access full`
