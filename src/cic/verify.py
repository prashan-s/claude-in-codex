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
            "output_tail": tail(output.strip(), 3500),
        })
    return results
