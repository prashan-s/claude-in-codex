"""Small shared helpers: atomic files, ids, text trimming, processes, git."""

from __future__ import annotations

import datetime as _dt
import fcntl
import json
import os
import secrets
import shutil
import subprocess
import tempfile
import time
from pathlib import Path
from typing import Any


class CicError(Exception):
    """User-facing failure; the CLI prints the message and exits non-zero."""

    def __init__(self, message: str, code: int = 1):
        super().__init__(message)
        self.code = code


# ---------------------------------------------------------------- time / ids

def now() -> float:
    return time.time()


def now_iso() -> str:
    return _dt.datetime.now().astimezone().isoformat(timespec="seconds")


def today() -> str:
    return _dt.date.today().isoformat()


def new_id(prefix: str) -> str:
    stamp = _dt.datetime.now().strftime("%m%d-%H%M%S")
    return f"{prefix}-{stamp}-{secrets.token_hex(2)}"


# ---------------------------------------------------------------- files

def atomic_write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=str(path.parent), prefix=".tmp-", suffix=path.suffix)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(text)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(tmp, path)
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


def atomic_write_json(path: Path, obj: Any) -> None:
    atomic_write_text(path, json.dumps(obj, indent=2, ensure_ascii=False) + "\n")


def read_json(path: Path, default: Any = None) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return default


def append_line(path: Path, line: str) -> None:
    """Append one line under an exclusive lock so concurrent writers never interleave."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "a", encoding="utf-8") as handle:
        fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
        try:
            handle.write(line.rstrip("\n") + "\n")
        finally:
            fcntl.flock(handle.fileno(), fcntl.LOCK_UN)


def append_jsonl(path: Path, obj: Any) -> None:
    append_line(path, json.dumps(obj, ensure_ascii=False))


def read_text(path: Path, limit: int | None = None) -> str:
    try:
        data = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return ""
    return data if limit is None else data[:limit]


# ---------------------------------------------------------------- text

def oneline(text: Any, limit: int = 100) -> str:
    flat = " ".join(str(text or "").split())
    return flat if len(flat) <= limit else flat[: limit - 1] + "…"


def tail(text: str, limit: int) -> str:
    text = text or ""
    if len(text) <= limit:
        return text
    return "…[truncated]…\n" + text[-limit:]


def fmt_duration(seconds: float | None) -> str:
    if seconds is None:
        return "?"
    seconds = int(seconds)
    if seconds < 60:
        return f"{seconds}s"
    minutes, sec = divmod(seconds, 60)
    if minutes < 60:
        return f"{minutes}m{sec:02d}s"
    hours, minutes = divmod(minutes, 60)
    return f"{hours}h{minutes:02d}m"


def fmt_cost(usd: float | None) -> str:
    if not usd:
        return "$0.00"
    return f"${usd:.2f}" if usd >= 0.01 else f"${usd:.4f}"


def iso_to_epoch(value: str | None) -> float | None:
    if not value:
        return None
    try:
        return _dt.datetime.fromisoformat(value).timestamp()
    except ValueError:
        return None


# ---------------------------------------------------------------- processes

def which(binary: str) -> str | None:
    if os.sep in binary:
        return binary if os.access(binary, os.X_OK) else None
    return shutil.which(binary)


def pid_alive(pid: int | None) -> bool:
    if not pid:
        return False
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


def run(argv: list[str], cwd: str | None = None, timeout: float = 30, env: dict | None = None) -> tuple[int, str, str]:
    try:
        proc = subprocess.run(
            argv,
            cwd=cwd,
            env=env,
            stdin=subprocess.DEVNULL,
            capture_output=True,
            text=True,
            timeout=timeout,
        )
        return proc.returncode, proc.stdout, proc.stderr
    except FileNotFoundError:
        return 127, "", f"{argv[0]}: not found"
    except subprocess.TimeoutExpired as exc:
        out = exc.stdout.decode() if isinstance(exc.stdout, bytes) else (exc.stdout or "")
        return 124, out, f"timed out after {timeout}s"


def depth() -> int:
    try:
        return int(os.environ.get("CIC_DEPTH", "0"))
    except ValueError:
        return 0


def child_env(extra: dict[str, str] | None = None) -> dict[str, str]:
    """Environment for spawned agents: one level deeper, never marked as sandboxed."""
    env = dict(os.environ)
    env["CIC_DEPTH"] = str(depth() + 1)
    env.pop("CLAUDECODE", None)  # let nested Claude Code start cleanly
    if extra:
        env.update(extra)
    return env


# ---------------------------------------------------------------- git

def git_info(cwd: str) -> dict[str, Any]:
    code, root, _ = run(["git", "rev-parse", "--show-toplevel"], cwd=cwd, timeout=10)
    if code != 0:
        return {"is_repo": False}
    _, branch, _ = run(["git", "rev-parse", "--abbrev-ref", "HEAD"], cwd=cwd, timeout=10)
    _, status, _ = run(["git", "status", "--porcelain=v1", "--untracked-files=all"], cwd=cwd, timeout=20)
    lines = [line for line in status.splitlines() if line.strip()]
    return {
        "is_repo": True,
        "root": root.strip(),
        "branch": branch.strip() or "?",
        "changed": len(lines),
        "status_lines": lines[:20],
    }
