"""Named, resumable Claude conversations (``cic session`` / ``cic say``).

A session pins a Claude Code session id up front (``--session-id``), so every
later turn resumes the same transcript with ``--resume`` even if a previous
process crashed.
"""

from __future__ import annotations

import re
import uuid

from . import config
from .util import CicError, atomic_write_json, now_iso, read_json

_NAME = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$")


def _path(name: str):
    if not _NAME.match(name):
        raise CicError(f"invalid session name {name!r} (letters, digits, . _ -)")
    return config.sessions_dir() / f"{name}.json"


def load(name: str) -> dict | None:
    data = read_json(_path(name))
    return data if isinstance(data, dict) else None


def save(record: dict) -> None:
    record["updated_at"] = now_iso()
    atomic_write_json(_path(record["name"]), record)


def create(name: str, *, cwd: str, model: str, effort: str | None, access: str, role: str | None) -> dict:
    if load(name):
        raise CicError(f"session {name!r} already exists (cic session rm {name} to start over)")
    record = {
        "name": name,
        "session_id": str(uuid.uuid4()),
        "cwd": cwd,
        "model": model,
        "effort": effort,
        "access": access,
        "role": role,
        "created_at": now_iso(),
        "started": False,
        "turns": 0,
        "last_job": None,
        "cost_usd": 0.0,
    }
    save(record)
    return record


def list_all() -> list[dict]:
    records = []
    for path in sorted(config.sessions_dir().glob("*.json")):
        data = read_json(path)
        if isinstance(data, dict):
            records.append(data)
    records.sort(key=lambda r: r.get("updated_at", ""), reverse=True)
    return records


def remove(name: str) -> bool:
    path = _path(name)
    if path.exists():
        path.unlink()
        return True
    return False


def record_turn(name: str, *, job_id: str, started: bool, cost_usd: float, model: str | None) -> None:
    record = load(name)
    if not record:
        return
    record["last_job"] = job_id
    if started:
        record["started"] = True
        record["turns"] = int(record.get("turns", 0)) + 1
    if cost_usd:
        record["cost_usd"] = cost_usd  # Claude Code reports the running session total
    if model:
        record["last_model"] = model
    save(record)
