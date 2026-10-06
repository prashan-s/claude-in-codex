"""Claude Code headless driver.

* ``access_profile`` maps cic access levels to Claude Code permission flags.
* ``build_argv`` produces a ``claude -p`` command in bidirectional stream-json
  mode, so one process can take follow-ups, mid-task steering, model switches,
  and interrupts.
* ``ClaudeProcess`` wraps that live process.
* ``Progress`` folds stream events into a status snapshot.
* ``classify`` turns the final ``result`` event into an outcome. It is strict:
  ``subtype == "success"`` alone is not trusted, because Claude Code reports
  auth failures as success with ``is_error: true``.
"""

from __future__ import annotations

import collections
import json
import os
import queue
import re
import shlex
import signal
import subprocess
import threading
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from . import config
from .router import tier_of
from .util import oneline

READ_TOOLS = ["Read", "Grep", "Glob", "WebSearch", "WebFetch"]
GIT_READ = [
    "Bash(git status *)", "Bash(git status)", "Bash(git diff *)", "Bash(git diff)", "Bash(git log *)",
    "Bash(git show *)", "Bash(git blame *)", "Bash(git branch *)", "Bash(git rev-parse *)", "Bash(git ls-files *)",
]
SHELL_READ = ["Bash(ls *)", "Bash(ls)", "Bash(rg *)", "Bash(wc *)", "Bash(head *)", "Bash(tail *)", "Bash(cat *)", "Bash(pwd)"]
GIT_WRITE_DENY = ["Bash(git push *)", "Bash(git push)", "Bash(git commit *)", "Bash(git commit)"]

_PY = [
    "Bash(pytest *)", "Bash(pytest)", "Bash(python -m pytest *)", "Bash(python3 -m pytest *)", "Bash(uv run pytest *)",
    "Bash(python -m unittest *)", "Bash(python3 -m unittest *)", "Bash(ruff check *)", "Bash(ruff format *)", "Bash(mypy *)",
]
_JS = [
    "Bash(npm test *)", "Bash(npm test)", "Bash(npm run *)", "Bash(pnpm test *)", "Bash(pnpm test)", "Bash(pnpm run *)",
    "Bash(yarn test *)", "Bash(yarn test)", "Bash(yarn run *)", "Bash(npx tsc *)", "Bash(npx vitest *)", "Bash(npx jest *)",
    "Bash(npx eslint *)", "Bash(npx prettier *)",
]
_PROJECT_RULES: list[tuple[str, list[str]]] = [
    ("package.json", _JS),
    ("pyproject.toml", _PY), ("setup.py", _PY), ("setup.cfg", _PY), ("pytest.ini", _PY), ("tox.ini", _PY),
    ("requirements.txt", _PY),
    ("go.mod", ["Bash(go test *)", "Bash(go build *)", "Bash(go vet *)"]),
    ("Cargo.toml", ["Bash(cargo test *)", "Bash(cargo test)", "Bash(cargo build *)", "Bash(cargo build)",
                    "Bash(cargo check *)", "Bash(cargo check)", "Bash(cargo clippy *)", "Bash(cargo fmt *)"]),
    ("Package.swift", ["Bash(swift build *)", "Bash(swift build)", "Bash(swift test *)", "Bash(swift test)"]),
    ("Makefile", ["Bash(make test *)", "Bash(make test)", "Bash(make check *)", "Bash(make check)",
                  "Bash(make lint *)", "Bash(make lint)", "Bash(make build *)", "Bash(make build)"]),
    ("Gemfile", ["Bash(bundle exec rspec *)", "Bash(bundle exec rake *)"]),
    ("build.gradle", ["Bash(./gradlew test *)", "Bash(./gradlew build *)"]),
    ("build.gradle.kts", ["Bash(./gradlew test *)", "Bash(./gradlew build *)"]),
    ("pom.xml", ["Bash(mvn test *)", "Bash(mvn -q test *)"]),
]

_SPLIT_SHELL = re.compile(r"\s*(?:&&|\|\||;|\|)\s*")


def project_rules(cwd: str) -> list[str]:
    rules: list[str] = []
    base = Path(cwd)
    for marker, marker_rules in _PROJECT_RULES:
        if (base / marker).exists():
            rules.extend(marker_rules)
    try:
        if any(p.suffix in (".xcodeproj", ".xcworkspace") for p in base.iterdir()):
            rules.append("Bash(xcodebuild *)")
    except OSError:
        pass
    return rules


def verify_rules(commands: list[str]) -> list[str]:
    """Allow Claude to run exactly the caller's verification commands (plus extra args)."""
    rules = []
    for command in commands:
        for segment in _SPLIT_SHELL.split(command.strip()):
            segment = segment.strip()
            if segment and "(" not in segment and ")" not in segment:
                rules.extend([f"Bash({segment})", f"Bash({segment} *)"])
    return rules


def _dedupe(items: list[str]) -> list[str]:
    return list(dict.fromkeys(i for i in items if i))


def access_profile(access: str, *, cwd: str, allow: list[str], deny: list[str], verify: list[str],
                   allow_git_write: bool) -> tuple[str, list[str], list[str]]:
    """Return (permission_mode, allowed_tools, disallowed_tools) for an access level."""
    allowed: list[str] = []
    disallowed: list[str] = []
    if access == "read":
        mode = "dontAsk"
        allowed = READ_TOOLS + GIT_READ + SHELL_READ
        disallowed = ["Edit", "Write", "NotebookEdit"]
    elif access == "edit":
        mode = "acceptEdits"
        allowed = READ_TOOLS + GIT_READ + SHELL_READ + project_rules(cwd)
    elif access == "auto":
        mode = "auto"
    elif access == "full":
        mode = "bypassPermissions"
    else:
        raise ValueError(f"unknown access level {access!r}")
    if access != "read":
        allowed += verify_rules(verify)
    allowed += allow
    if not allow_git_write:
        disallowed += GIT_WRITE_DENY
    disallowed += deny
    return mode, _dedupe(allowed), _dedupe(disallowed)


@dataclass
class ClaudeSpec:
    model: str
    cwd: str
    access: str = "read"
    effort: str | None = None
    fallback: list[str] = field(default_factory=list)
    session_id: str | None = None
    resume: str | None = None
    fork: bool = False
    schema: dict | None = None
    system_file: str | None = None
    allow: list[str] = field(default_factory=list)
    deny: list[str] = field(default_factory=list)
    verify: list[str] = field(default_factory=list)
    allow_git_write: bool = False
    max_turns: int | None = None
    budget_usd: float | None = None
    worktree: str | None = None
    add_dirs: list[str] = field(default_factory=list)
    lean: bool = False
    name: str | None = None


def build_argv(spec: ClaudeSpec) -> list[str]:
    mode, allowed, disallowed = access_profile(
        spec.access, cwd=spec.cwd, allow=spec.allow, deny=spec.deny, verify=spec.verify,
        allow_git_write=spec.allow_git_write,
    )
    argv = [
        config.get("claude_bin"), "-p",
        "--input-format", "stream-json", "--output-format", "stream-json", "--verbose",
        "--replay-user-messages",
        "--model", spec.model,
        "--permission-mode", mode,
        "--permission-prompts", "none",
    ]
    if spec.effort and tier_of(spec.model) != "haiku":
        argv += ["--effort", spec.effort]
    fallback = [f for f in spec.fallback if f and tier_of(f) != tier_of(spec.model)]
    if fallback:
        argv += ["--fallback-model", ",".join(fallback)]
    if spec.resume:
        argv += ["--resume", spec.resume]
        if spec.fork:
            argv.append("--fork-session")
    elif spec.session_id:
        argv += ["--session-id", spec.session_id]
    if allowed:
        argv += ["--allowedTools", ",".join(allowed)]
    if disallowed:
        argv += ["--disallowedTools", ",".join(disallowed)]
    if spec.system_file:
        argv += ["--append-system-prompt-file", spec.system_file]
    if spec.schema:
        argv += ["--json-schema", json.dumps(spec.schema, separators=(",", ":"))]
    if spec.max_turns:
        argv += ["--max-turns", str(spec.max_turns)]
    if spec.budget_usd:
        argv += ["--max-budget-usd", f"{spec.budget_usd:.2f}"]
    if spec.worktree:
        argv += ["--worktree", spec.worktree]
    for directory in spec.add_dirs:
        argv += ["--add-dir", directory]
    if spec.lean:
        argv.append("--safe-mode")
    if spec.name:
        argv += ["--name", spec.name]
    return argv


def printable_argv(argv: list[str]) -> str:
    shown = []
    for index, arg in enumerate(argv):
        if index > 0 and argv[index - 1] == "--json-schema" and len(arg) > 80:
            arg = arg[:77] + "..."
        shown.append(shlex.quote(arg))
    return " ".join(shown)


# ----------------------------------------------------------------- live process

EOF = object()


class ClaudeProcess:
    """One ``claude -p`` process speaking stream-json on stdin and stdout."""

    def __init__(self, argv: list[str], *, cwd: str, env: dict[str, str], raw_log: Path):
        self.argv = argv
        self.events: queue.Queue = queue.Queue()
        self.stderr_lines: collections.deque[str] = collections.deque(maxlen=200)
        self.pending_replays = 0
        self._req = 0
        self._raw = open(raw_log, "a", encoding="utf-8")
        self._lock = threading.Lock()
        self.proc = subprocess.Popen(
            argv,
            cwd=cwd,
            env=env,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            encoding="utf-8",
            errors="replace",
            bufsize=1,
        )
        threading.Thread(target=self._read_stdout, daemon=True).start()
        threading.Thread(target=self._read_stderr, daemon=True).start()

    @property
    def pid(self) -> int:
        return self.proc.pid

    def _read_stdout(self) -> None:
        assert self.proc.stdout is not None
        for line in self.proc.stdout:
            if not line.strip():
                continue
            self._raw.write(line if line.endswith("\n") else line + "\n")
            self._raw.flush()
            try:
                event = json.loads(line)
            except ValueError:
                self.stderr_lines.append(line.rstrip())
                continue
            if isinstance(event, dict):
                self.events.put(event)
        self.events.put(EOF)

    def _read_stderr(self) -> None:
        assert self.proc.stderr is not None
        for line in self.proc.stderr:
            self.stderr_lines.append(line.rstrip())

    def _write(self, obj: dict) -> bool:
        with self._lock:
            try:
                assert self.proc.stdin is not None
                self.proc.stdin.write(json.dumps(obj, ensure_ascii=False) + "\n")
                self.proc.stdin.flush()
                return True
            except (BrokenPipeError, OSError, ValueError, AssertionError):
                return False

    def send_user(self, text: str) -> bool:
        ok = self._write({
            "type": "user",
            "message": {"role": "user", "content": text},
            "parent_tool_use_id": None,
        })
        if ok:
            self.pending_replays += 1
        return ok

    def control(self, subtype: str, **fields: Any) -> str:
        self._req += 1
        request_id = f"cic_{self._req}"
        self._write({"type": "control_request", "request_id": request_id, "request": {"subtype": subtype, **fields}})
        return request_id

    def next_event(self, timeout: float) -> Any:
        try:
            return self.events.get(timeout=timeout)
        except queue.Empty:
            return None

    def alive(self) -> bool:
        return self.proc.poll() is None

    def close_input(self) -> None:
        with self._lock:
            try:
                if self.proc.stdin:
                    self.proc.stdin.close()
            except OSError:
                pass

    def finish(self, grace: float = 30) -> int | None:
        """Close stdin and let Claude Code exit; escalate SIGINT -> SIGTERM -> SIGKILL if it lingers."""
        self.close_input()
        for sig, wait in ((None, grace), (signal.SIGINT, 5), (signal.SIGTERM, 5), (signal.SIGKILL, 5)):
            if sig is not None and self.alive():
                try:
                    self.proc.send_signal(sig)
                except OSError:
                    pass
            try:
                code = self.proc.wait(timeout=wait)
                self._raw.close()
                return code
            except subprocess.TimeoutExpired:
                continue
        self._raw.close()
        return None

    def stderr_tail(self, lines: int = 15) -> str:
        return "\n".join(list(self.stderr_lines)[-lines:])


# ----------------------------------------------------------------- progress

_EDIT_TOOLS = {"Edit", "Write", "MultiEdit", "NotebookEdit"}


def describe_tool(name: str, data: dict) -> str:
    data = data or {}
    if name == "Bash":
        return f"Bash: {oneline(data.get('command'), 90)}"
    if name in _EDIT_TOOLS or name == "Read":
        return f"{name}: {data.get('file_path') or data.get('notebook_path') or '?'}"
    if name in ("Grep", "Glob"):
        return f"{name}: {oneline(data.get('pattern'), 60)}"
    if name == "WebFetch":
        return f"WebFetch: {oneline(data.get('url'), 80)}"
    if name == "WebSearch":
        return f"WebSearch: {oneline(data.get('query'), 80)}"
    if name in ("Agent", "Task"):
        return f"{name}: {oneline(data.get('description') or data.get('subagent_type'), 60)}"
    if name == "StructuredOutput":
        return "writing final report"
    return name


@dataclass
class Progress:
    model: str | None = None
    permission_mode: str | None = None
    session_id: str | None = None
    session_cwd: str | None = None
    tool_uses: int = 0
    tool_errors: int = 0
    last_tool: str | None = None
    last_text: str | None = None
    files: list[str] = field(default_factory=list)
    denials: list[dict] = field(default_factory=list)
    api_retries: int = 0
    last_error: str | None = None
    rate_limit: str | None = None
    subagent_events: int = 0
    results: int = 0
    cost_usd: float = 0.0
    models_used: list[str] = field(default_factory=list)
    last_event_at: float = field(default_factory=time.time)

    def to_dict(self) -> dict:
        return asdict(self)

    def apply(self, event: dict) -> str | None:
        """Update state from one stream event; return a human log line when useful."""
        self.last_event_at = time.time()
        etype = event.get("type")
        subtype = event.get("subtype")
        if etype == "system":
            if subtype == "init":
                self.model = event.get("model")
                self.permission_mode = event.get("permissionMode")
                self.session_id = event.get("session_id") or self.session_id
                self.session_cwd = event.get("cwd") or self.session_cwd
                return f"session {self.session_id} · model {self.model} · permissions {self.permission_mode}"
            if subtype == "api_retry":
                self.api_retries += 1
                self.last_error = f"{event.get('error')} (HTTP {event.get('error_status')}), retry {event.get('attempt')}/{event.get('max_retries')}"
                return f"API retry: {self.last_error}"
            if subtype == "permission_denied":
                denial = {"tool": event.get("tool_name"), "message": oneline(event.get("message"), 160)}
                self.denials.append(denial)
                return f"permission denied: {denial['tool']}"
            if subtype == "compact_boundary":
                return "context compacted"
            return None
        if etype == "rate_limit_event":
            info = event.get("rate_limit_info") or {}
            status = info.get("status") if isinstance(info, dict) else None
            if status and status != "allowed":
                self.rate_limit = f"{status} (resets {info.get('resetsAt', '?')})"
                return f"rate limit: {self.rate_limit}"
            return None
        if etype == "assistant":
            sub = bool(event.get("parent_tool_use_id"))
            if sub:
                self.subagent_events += 1
            line = None
            for block in (event.get("message") or {}).get("content") or []:
                kind = block.get("type")
                if kind == "tool_use":
                    name = block.get("name") or "?"
                    data = block.get("input") or {}
                    self.tool_uses += 1
                    self.last_tool = describe_tool(name, data)
                    if name in _EDIT_TOOLS:
                        path = data.get("file_path") or data.get("notebook_path")
                        if path and path not in self.files:
                            self.files.append(path)
                    line = ("[subagent] " if sub else "") + self.last_tool
                elif kind == "text" and block.get("text", "").strip() and not sub:
                    self.last_text = oneline(block["text"], 240)
                    line = f"says: {oneline(block['text'], 160)}"
            return line
        if etype == "user":
            for block in (event.get("message") or {}).get("content") or []:
                if isinstance(block, dict) and block.get("type") == "tool_result" and block.get("is_error"):
                    self.tool_errors += 1
            return None
        if etype == "result":
            self.results += 1
            self.cost_usd = float(event.get("total_cost_usd") or 0.0)
            self.models_used = list((event.get("modelUsage") or {}).keys())
            return f"turn finished: {event.get('subtype')} ({event.get('terminal_reason')}), {event.get('num_turns')} turns"
        if etype == "control_response":
            response = event.get("response") or {}
            if response.get("subtype") != "success":
                return f"control request failed: {oneline(json.dumps(response), 160)}"
        return None


# ----------------------------------------------------------------- outcomes

_AUTH = re.compile(r"not logged in|/login|invalid api key|authentication|unauthori[sz]ed|oauth token", re.I)


@dataclass
class TurnOutcome:
    error: str | None
    message: str
    report: dict | None
    text: str
    denials: list[dict]
    cost_usd: float
    num_turns: int | None = None

    @property
    def ok(self) -> bool:
        return self.error is None


def classify(result: dict | None, *, expect_report: bool, interrupted: bool = False, stderr_tail: str = "") -> TurnOutcome:
    if result is None:
        hint = f"\n{stderr_tail}" if stderr_tail else ""
        return TurnOutcome("crash", "Claude Code exited without a result." + hint, None, "", [], 0.0)
    subtype = result.get("subtype")
    terminal = result.get("terminal_reason")
    is_error = bool(result.get("is_error"))
    raw = result.get("result")
    text = raw if isinstance(raw, str) else (json.dumps(raw) if raw is not None else "")
    report = None
    if expect_report:
        candidate = result.get("structured_output")
        if candidate is None and text.strip().startswith("{"):
            try:
                candidate = json.loads(text)
            except ValueError:
                candidate = None
        report = candidate if isinstance(candidate, dict) else None
    denials = [
        {"tool": d.get("tool_name"), "input": oneline(json.dumps(d.get("tool_input")), 160)}
        for d in (result.get("permission_denials") or [])
        if isinstance(d, dict)
    ]
    cost = float(result.get("total_cost_usd") or 0.0)
    error: str | None = None
    if interrupted or (subtype == "error_during_execution" and terminal in ("aborted_streaming", "aborted", "interrupted")):
        error = "interrupted"
    elif subtype == "error_max_turns":
        error = "max_turns"
    elif subtype == "error_max_budget_usd":
        error = "budget"
    elif subtype == "error_max_structured_output_retries":
        error = "structured_output"
    elif is_error:
        error = "auth" if (_AUTH.search(text) or result.get("api_error_status") in (401, 403)) else "api"
    elif terminal not in (None, "completed"):
        error = str(terminal)
    messages = {
        None: "completed",
        "interrupted": "turn interrupted",
        "max_turns": "hit the --max-turns limit",
        "budget": "hit the --budget limit",
        "structured_output": "could not produce a valid structured report",
        "auth": "Claude Code is not authenticated in this environment: " + oneline(text, 160),
        "api": "API error: " + oneline(text or terminal or "unknown", 200),
    }
    return TurnOutcome(
        error=error,
        message=messages.get(error, f"ended with {error}"),
        report=report,
        text=text,
        denials=denials,
        cost_usd=cost,
        num_turns=result.get("num_turns"),
    )


def auth_status() -> dict:
    """``claude auth status`` as a dict; ``{"loggedIn": False, "error": ...}`` on failure."""
    from .util import run

    code, out, err = run([config.get("claude_bin"), "auth", "status"], timeout=20)
    try:
        data = json.loads(out)
        if isinstance(data, dict):
            return data
    except ValueError:
        pass
    return {"loggedIn": False, "error": oneline(err or out or f"exit {code}", 200)}


def version() -> str | None:
    from .util import run

    code, out, _ = run([config.get("claude_bin"), "--version"], timeout=20)
    if code != 0:
        return None
    match = re.search(r"(\d+\.\d+\.\d+)", out)
    return match.group(1) if match else out.strip() or None


def sandboxed() -> bool:
    return bool(os.environ.get("CODEX_SANDBOX"))
