"""Job store: every delegation is a job directory under ``$CIC_HOME/jobs``.

Layout of ``jobs/<id>/``:
  job.json      state (written only by the job's worker once it starts)
  brief.md      the user message sent to Claude
  system.md     the appended system-prompt contract
  events.jsonl  raw Claude Code stream-json events
  log.txt       human-readable progress log
  final.md      rendered final report
  control/new/  inbox for steer / model / cancel requests from other processes
"""

from __future__ import annotations

import os
import shutil
import signal
import subprocess
import sys
import time
import uuid
from pathlib import Path
from typing import Any

from . import config
from .util import (CicError, atomic_write_json, atomic_write_text, depth, iso_to_epoch, new_id,
                   now_iso, oneline, pid_alive, read_json)

TERMINAL = {"done", "partial", "needs_input", "blocked", "failed", "cancelled"}
ACTIVE = {"queued", "running"}


def job_dir(job_id: str) -> Path:
    return config.jobs_dir() / job_id


def load(job_id: str) -> dict:
    data = read_json(job_dir(job_id) / "job.json")
    if not isinstance(data, dict):
        raise CicError(f"job {job_id} not found")
    return data


def save(job: dict) -> None:
    job["updated_at"] = now_iso()
    atomic_write_json(job_dir(job["id"]) / "job.json", job)


def create(kind: str, *, cwd: str, title: str, params: dict[str, Any], session_id: str | None = None,
           parent: str | None = None, session_name: str | None = None, prefix: str = "cj") -> dict:
    job_id = new_id(prefix)
    directory = job_dir(job_id)
    (directory / "control" / "new").mkdir(parents=True)
    (directory / "control" / "cur").mkdir(parents=True)
    job = {
        "id": job_id,
        "kind": kind,
        "title": oneline(title, 100),
        "cwd": cwd,
        "created_at": now_iso(),
        "created_ts": time.time(),  # sub-second ordering: ids and created_at only resolve to seconds
        "status": "queued",
        "phase": "queued",
        "session_id": session_id or str(uuid.uuid4()),
        "parent": parent,
        "session_name": session_name,
        "depth": depth() + 1,
        "params": params,
    }
    save(job)
    prune()
    return job


def write_file(job: dict, name: str, text: str) -> Path:
    path = job_dir(job["id"]) / name
    atomic_write_text(path, text)
    return path


def read_final(job_id: str) -> str:
    try:
        return (job_dir(job_id) / "final.md").read_text(encoding="utf-8")
    except OSError:
        return ""


def spawn(job: dict) -> int:
    """Start the job's worker as a detached process that outlives the caller."""
    src_dir = str(Path(__file__).resolve().parents[1])
    env = dict(os.environ)
    env["PYTHONPATH"] = src_dir + (os.pathsep + env["PYTHONPATH"] if env.get("PYTHONPATH") else "")
    directory = job_dir(job["id"])
    with open(directory / "worker.log", "ab") as log:
        proc = subprocess.Popen(
            [sys.executable, "-m", "cic", "_worker", job["id"]],
            cwd=str(directory),  # never the user's repo: keeps its files off sys.path
            env=env,
            stdin=subprocess.DEVNULL,
            stdout=log,
            stderr=subprocess.STDOUT,
            start_new_session=True,
        )
    return proc.pid


# ----------------------------------------------------------------- queries

def all_ids() -> list[str]:
    root = config.jobs_dir()
    return sorted((p.name for p in root.iterdir() if (p / "job.json").exists()), reverse=True)


def list_jobs(cwd: str | None = None, limit: int = 20, kinds: set[str] | None = None) -> list[dict]:
    found = []
    for job_id in all_ids():
        data = read_json(job_dir(job_id) / "job.json")
        if not isinstance(data, dict):
            continue
        if cwd and data.get("cwd") != cwd:
            continue
        if kinds and data.get("kind") not in kinds:
            continue
        found.append(refresh(data))
    found.sort(key=_created_key, reverse=True)
    return found[:limit]


def _created_key(job: dict) -> tuple[float, str]:
    stamp = job.get("created_ts") or iso_to_epoch(job.get("created_at")) or 0.0
    return float(stamp), job.get("id", "")


def resolve(ref: str | None, cwd: str | None = None) -> dict:
    """Find a job by id, unique id prefix/suffix, or 'last' (newest in cwd, else newest anywhere)."""
    if not ref or ref in ("last", "latest"):
        jobs = list_jobs(cwd=cwd, limit=1) or list_jobs(limit=1)
        if not jobs:
            raise CicError("no jobs yet")
        return jobs[0]
    if (job_dir(ref) / "job.json").exists():
        return refresh(load(ref))
    matches = [j for j in all_ids() if j.startswith(ref) or j.endswith(ref)]
    if len(matches) == 1:
        return refresh(load(matches[0]))
    if not matches:
        raise CicError(f"no job matches {ref!r}")
    raise CicError(f"{ref!r} is ambiguous: " + ", ".join(matches[:6]))


def refresh(job: dict) -> dict:
    """Add derived fields; mark jobs whose worker died as failed (without rewriting the file)."""
    status = job.get("status")
    if status in ACTIVE:
        pid = job.get("worker_pid")
        created = iso_to_epoch(job.get("created_at")) or time.time()
        if (pid and not pid_alive(pid)) or (not pid and time.time() - created > 60):
            job = dict(job)
            job["status"] = "failed"
            job["stale"] = True
            job["reason"] = "worker exited unexpectedly; see worker.log"
    start = iso_to_epoch(job.get("started_at") or job.get("created_at"))
    end = iso_to_epoch(job.get("finished_at")) or time.time()
    if start:
        job["elapsed"] = max(0.0, end - start)
    return job


def wait(job_id: str, timeout: float) -> dict:
    deadline = time.time() + max(0.0, timeout)
    delay = 0.5
    while True:
        job = refresh(load(job_id))
        if job.get("status") in TERMINAL:
            return job
        remaining = deadline - time.time()
        if remaining <= 0:
            return job
        time.sleep(min(delay, remaining))
        delay = min(delay * 1.5, 3.0)


# ----------------------------------------------------------------- control

def send_control(job_id: str, payload: dict) -> None:
    directory = job_dir(job_id) / "control"
    name = f"{time.time():.6f}-{uuid.uuid4().hex[:6]}.json"
    atomic_write_json(directory / "tmp" / name, payload)
    (directory / "new").mkdir(parents=True, exist_ok=True)
    os.replace(directory / "tmp" / name, directory / "new" / name)


def take_controls(job_id: str) -> list[dict]:
    directory = job_dir(job_id) / "control"
    new = directory / "new"
    taken = []
    try:
        names = sorted(os.listdir(new))
    except FileNotFoundError:
        return []
    for name in names:
        src = new / name
        dst = directory / "cur" / name
        try:
            os.replace(src, dst)
        except FileNotFoundError:
            continue
        data = read_json(dst)
        if isinstance(data, dict):
            taken.append(data)
    return taken


def controls_pending(job_id: str) -> bool:
    try:
        return bool(os.listdir(job_dir(job_id) / "control" / "new"))
    except FileNotFoundError:
        return False


def cancel(job_id: str, grace: float = 25) -> dict:
    job = refresh(load(job_id))
    if job.get("status") in TERMINAL:
        return job
    send_control(job_id, {"type": "cancel"})
    job = wait(job_id, grace)
    if job.get("status") in TERMINAL and not job.get("stale"):
        return job
    # The worker did not wind down in time: stop the whole process group.
    for pid in (job.get("worker_pid"), job.get("claude_pid")):
        if pid and pid_alive(pid):
            try:
                os.killpg(os.getpgid(pid), signal.SIGTERM)
            except (OSError, ProcessLookupError):
                pass
    stored = load(job_id)
    stored.update(status="cancelled", phase="finished", finished_at=now_iso(), reason="cancelled (forced stop)")
    save(stored)
    return refresh(stored)


# ----------------------------------------------------------------- housekeeping

def prune() -> None:
    keep = int(config.get("keep_jobs"))
    ids = all_ids()
    if len(ids) <= keep:
        return
    for job_id in ids[keep:]:
        data = read_json(job_dir(job_id) / "job.json") or {}
        if data.get("status") in TERMINAL:
            shutil.rmtree(job_dir(job_id), ignore_errors=True)


def guard_depth() -> None:
    limit = int(config.get("max_depth"))
    if depth() >= limit:
        raise CicError(
            f"delegation depth limit reached (CIC_DEPTH={depth()}, max {limit}). "
            "This process is already a delegated agent: do the work yourself instead of delegating again.",
            code=5,
        )


def guard_sandbox() -> None:
    if os.environ.get("CODEX_SANDBOX"):
        raise CicError(
            "cic is running inside the Codex sandbox (CODEX_SANDBOX is set), where Claude Code cannot read its login "
            "or write ~/.claude. Install the exec-policy rule (run install.sh, or copy codex/rules/claude-in-codex.rules "
            "to ~/.codex/rules/), then invoke cic as a single plain command (no cd/&&/pipes) so the rule matches. "
            "Alternatively re-run this command with escalated permissions.",
            code=6,
        )
