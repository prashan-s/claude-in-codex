"""Paths, defaults, and user overrides.

Overrides come from ``$CIC_HOME/config.json`` and a few environment variables.
Everything cic stores lives under ``$CIC_HOME`` (default ``~/.cic``).
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

DEFAULTS: dict[str, Any] = {
    # Routing. "auto" lets the router pick haiku/sonnet/opus per task.
    "default_model": "auto",
    # Fable is never chosen automatically; an explicit --model fable still works.
    "allow_fable_escalation": False,
    # How many delegation hops are allowed below the top-level orchestrator.
    "max_depth": 1,
    # How long `cic run` blocks before handing back a job id (keep under the
    # caller's tool timeout; Codex commonly allows ~10 minutes).
    "wait_seconds": 540,
    # Total turns a write task may spend (first try + repair attempts).
    "max_attempts": 3,
    "verify_timeout": 900,
    # Hard wall-clock cap per job, and the no-output window treated as a hang.
    "job_timeout": 5400,
    "stall_timeout": 900,
    # Multi-agent defaults.
    "council_members": ["claude:sonnet", "codex", "gemini"],
    "council_synth": "claude:opus",
    "pair_driver": "claude:sonnet",
    "pair_navigator": "claude:opus",
    "pair_rounds": 3,
    # Run Claude with --safe-mode (no plugins/hooks/CLAUDE.md) unless overridden per call.
    "lean": False,
    "claude_bin": "claude",
    "codex_bin": "codex",
    "gemini_bin": "gemini",
    "keep_jobs": 200,
}

_ENV_OVERRIDES = {
    "CIC_CLAUDE_BIN": ("claude_bin", str),
    "CIC_CODEX_BIN": ("codex_bin", str),
    "CIC_GEMINI_BIN": ("gemini_bin", str),
    "CIC_MAX_DEPTH": ("max_depth", int),
    "CIC_WAIT_SECONDS": ("wait_seconds", int),
    "CIC_DEFAULT_MODEL": ("default_model", str),
}

_cache: dict[str, Any] | None = None


def home() -> Path:
    root = os.environ.get("CIC_HOME") or os.path.join(os.path.expanduser("~"), ".cic")
    path = Path(root)
    path.mkdir(parents=True, exist_ok=True)
    return path


def sub(name: str) -> Path:
    path = home() / name
    path.mkdir(parents=True, exist_ok=True)
    return path


def jobs_dir() -> Path:
    return sub("jobs")


def sessions_dir() -> Path:
    return sub("sessions")


def bus_dir() -> Path:
    return sub("bus")


def serve_dir() -> Path:
    return sub("serve")


def load() -> dict[str, Any]:
    global _cache
    if _cache is not None:
        return _cache
    cfg = dict(DEFAULTS)
    path = home() / "config.json"
    if path.exists():
        try:
            user = json.loads(path.read_text(encoding="utf-8"))
            if isinstance(user, dict):
                cfg.update({k: v for k, v in user.items() if k in DEFAULTS})
        except (OSError, ValueError):
            pass
    for env, (key, cast) in _ENV_OVERRIDES.items():
        raw = os.environ.get(env)
        if raw:
            try:
                cfg[key] = cast(raw)
            except ValueError:
                pass
    _cache = cfg
    return cfg


def get(key: str) -> Any:
    return load()[key]


def reset_cache() -> None:
    global _cache
    _cache = None
