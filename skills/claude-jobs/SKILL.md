---
name: claude-jobs
description: Monitor and control Claude Code jobs started with cic, including list, live progress, bounded wait, final result, step log, mid-task steering, model switch, cancel, and follow-up on a finished job. Use when the user asks what Claude is doing, whether it finished, to see its result, or to redirect or stop it.
metadata:
  short-description: Progress, steering, and control of Claude jobs
---

# Monitor and control Claude jobs

Every `cic run`, `ask`, `review`, `say`, `pair`, and `council` call is a job that keeps running even if your command returns. In every command, `<job>` accepts a full id, a unique prefix or suffix, or `last`. Call `cic` as a single plain command.

| Need | Command |
|---|---|
| Active jobs and recent jobs here | `cic status` |
| List jobs | `cic jobs` (add `--all` for every directory, `--json` for structured output) |
| Progress of one job | `cic status <job>` |
| Block until done, bounded | `cic wait <job> --timeout 300` |
| Final report | `cic result <job>` (`--json` for the structured report) |
| Step-by-step log | `cic logs <job> --tail 40` (`--raw` for stream events) |
| Redirect while running | `cic steer <job> "<instruction>"` |
| Change model while running | `cic model <job> opus` |
| Stop | `cic cancel <job>` |
| Continue after it finished | `cic reply <job> "<follow-up>"` |

## How to use them well
- **Waiting.** `cic wait --timeout 300` returns exit 3 while the job is still running; call it again. This beats rapid `status` polling. Between waits, give the user a one-line update: phase, last action, elapsed time.
- **Steering vs replying.** Steering works only while the job runs. Claude sees the message at its next tool step and folds it into the current work, with no restart. After the job finishes, use `cic reply`, which resumes the same Claude session with full context.
- **Model switches.** They take effect on the next request and rebuild the prompt cache once. Use them sparingly, e.g. move to `opus` when the log shows Claude going in circles.
- **Cancelling.** cic interrupts the current turn first so the session stays resumable, then forces a stop if needed. Partial edits stay in the working tree; check `git status`.
- **Reading status.** `progress` shows tool calls, files edited, denials, API retries, and rate limits. Repeated denials mean the job needs wider access: reply with a re-run using `--access auto` or `--allow`.
- **Dead workers.** A job marked failed with "worker exited unexpectedly" (e.g. the machine slept or the process was killed) can still continue: `cic reply <job> "continue"` resumes its Claude session.
- **Opening a job interactively.** `claude --resume <session_id>`; the session id is shown in every report.
