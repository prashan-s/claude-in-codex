"""Independent verification: run the caller's checks after Claude reports done.

Only commands supplied by the orchestrator (``--verify``) are executed here.
Commands that Claude mentions in its own report are treated as claims and are
never run by cic, so a model cannot pick what runs outside its permission system.

A check that cannot run at all (missing command, test runner not installed) is
flagged as an environment error: repairing code cannot fix it, so the worker
stops and reports it instead of spending repair attempts.
"""

from __future__ import annotations

import re
import subprocess
import time

from .util import oneline, tail

_SIGNAL = re.compile(
    r"(FAIL|ERROR|Error|Exception|Traceback|assert|Assertion|expected|panic|✗|×|not ok|failed|error:|E\s{2,})"
)


def focus_output(text: str, limit: int = 3500) -> str:
    """Keep what explains a failure: signal lines with a little context, plus the tail.

    Raw test output is mostly noise (progress dots, passing tests). Sending only the
    failing lines and the summary keeps repair turns small without losing the evidence.
    """
    text = (text or "").strip()
    if len(text) <= limit:
        return text
    lines = text.splitlines()
    keep: set[int] = set()
    for index, line in enumerate(lines):
        if _SIGNAL.search(line):
            keep.update(range(max(0, index - 2), min(len(lines), index + 3)))
    keep.update(range(max(0, len(lines) - 25), len(lines)))  # summary lines usually come last
    chosen = []
    previous = -2
    for index in sorted(keep):
        if index != previous + 1:
            chosen.append("…")
        chosen.append(lines[index])
        previous = index
    focused = "\n".join(chosen)
    return focused if len(focused) <= limit else tail(focused, limit)


_NOT_FOUND = re.compile(r"(?:command not found|not found|No such file or directory)", re.I)
_NO_MODULE = re.compile(r"No module named '?([A-Za-z0-9_.]+)'?")
_RUNNER = re.compile(r"(?:^|\s)-m\s+([A-Za-z0-9_.]+)")


def environment_error(command: str, code: int, output: str) -> str | None:
    """Describe why a check could not run at all, or return None for an ordinary failure."""
    if code in (126, 127):
        line = next((l for l in output.splitlines() if _NOT_FOUND.search(l)), "")
        return oneline(line or f"`{command.split()[0]}` could not be executed (exit {code})", 200)
    match = _NO_MODULE.search(output)
    runner = _RUNNER.search(command)
    if code != 0 and match and runner and match.group(1).split(".")[0] == runner.group(1).split(".")[0]:
        return f"`{runner.group(1)}` is not installed for this interpreter"
    return None


def run_checks(commands: list[str], cwd: str, timeout: float) -> list[dict]:
    results = []
    for command in commands:
        started = time.time()
        try:
            proc = subprocess.run(
                command,
                shell=True,
                cwd=cwd,
                stdin=subprocess.DEVNULL,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                errors="replace",
                timeout=timeout,
            )
            code, output = proc.returncode, proc.stdout or ""
        except subprocess.TimeoutExpired as exc:
            raw = exc.stdout
            output = (raw.decode(errors="replace") if isinstance(raw, bytes) else raw or "") + f"\n[timed out after {timeout}s]"
            code = 124
        results.append({
            "command": command,
            "exit_code": code,
            "ok": code == 0,
            "env_error": None if code == 0 else environment_error(command, code, output),
            "seconds": round(time.time() - started, 1),
            "output_tail": focus_output(output, 3500),
        })
    return results
