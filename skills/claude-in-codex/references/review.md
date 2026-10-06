# Claude code review

## Run
Call `cic` as a single plain command, with `--cwd` instead of `cd`:
- Uncommitted changes: `cic review --cwd <repo>`
- Branch against its base: `cic review --cwd <repo> --base origin/main`
- With a focus: `cic review "auth and session handling" --cwd <repo>`
- Adversarial (tries to break confidence; routes to Opus): `cic review --adversarial --cwd <repo>`

Scope `auto` reviews the working tree when it has changes; otherwise it reviews the branch against the detected base. Diffs over about 60 KB are not inlined: Claude reads them with git itself. Reviews run read-only on Sonnet at high effort. Large diffs (over 1500 changed lines) and adversarial reviews go to Opus.

If it returns exit 3 (still running), poll with `cic wait <job> --timeout 300`.

## Present the result
- Keep the verdict, then the findings in severity order, with file:line exactly as reported.
- Keep the distinction between confirmed problems and inferences, and the confidence values.
- If there are no findings, say so and mention residual risk in one line.
- After presenting findings, stop. Do not fix anything until the user chooses which findings to address. Then fix them yourself, or delegate each one with `$claude-in-codex delegate`, using the finding text as the brief plus a `--verify` check.

## Follow-ups
- Dig into one finding: `cic reply <job> "Go deeper on finding 2: is the race reachable from the public API?"`
- Re-review after fixes: run `cic review` again. A fresh review avoids anchoring on the old one.
- Cross-vendor review loop (Claude implements, Codex reviews, or the other way round): `$claude-in-codex pair`.
