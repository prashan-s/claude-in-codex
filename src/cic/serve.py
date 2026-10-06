"""Long-running bus agents: put Claude, Codex, or Gemini on the message bus.

``cic serve start reviewer --agent claude:opus`` turns a CLI agent into an
addressable peer. Each bus thread maps to its own persistent conversation
(Claude session id or Codex thread id), so every peer keeps context per thread.
"""

from __future__ import annotations

import os
import signal
import subprocess
import sys
import time
from pathlib import Path

from . import agents, bus, config, prompts
from .util import CicError, atomic_write_json, now_iso, oneline, pid_alive, read_json


def _state_path(name: str) -> Path:
    return config.serve_dir() / f"{name.replace(':', '__')}.json"


def status_all() -> list[dict]:
    rows = []
    for path in sorted(config.serve_dir().glob("*.json")):
        state = read_json(path)
        if isinstance(state, dict):
            state["alive"] = pid_alive(state.get("pid")) and state.get("status") == "running"
            rows.append(state)
    return rows


def _transcript_context(thread: str, limit: int = 8) -> str:
    recent = bus.transcript(thread)[-limit:]
    if not recent:
        return ""
    lines = [f"[{m.get('from')} -> {', '.join(m.get('to', []))}] {oneline(m.get('body'), 600)}" for m in recent]
    return "<recent_thread>\n" + "\n".join(lines) + "\n</recent_thread>\n\n"


def serve_forever(name: str, agent: str, *, cwd: str, access: str, role: str | None, poll: float = 30.0,
                  idle_exit: float = 0.0) -> int:
    vendor, _ = agents.parse_spec(agent)
    path = _state_path(name)
    state = read_json(path) or {}
    state.update(name=name, agent=agent, cwd=cwd, access=access, pid=os.getpid(), status="running",
                 started_at=now_iso(), handled=state.get("handled", 0))
    state.setdefault("threads", {})
    atomic_write_json(path, state)

    def _stop(signum, frame):
        raise SystemExit(0)

    signal.signal(signal.SIGTERM, _stop)
    last = time.time()
    try:
        while True:
            messages = bus.recv(name, wait=poll, limit=1)
            if not messages:
                if idle_exit and time.time() - last > idle_exit:
                    break
                continue
            message = messages[0]
            last = time.time()
            if message.get("kind") == "control" and message.get("body", "").strip().lower() in ("stop", "shutdown"):
                break
            thread = message["thread"]
            resume = state["threads"].get(thread)
            prompt = (f'<message from="{message["from"]}" id="{message["id"]}" thread="{thread}">\n'
                      f'{message.get("body", "")}\n</message>')
            if vendor == "gemini":  # stateless CLI: give it the recent thread instead of a session
                prompt = _transcript_context(thread) + prompt
            persona = (role or "") + prompts.BUS_ADDENDUM.format(name=name, thread=thread)
            result = agents.run(agent, prompt, cwd=cwd, kind="ask", access=access, role=persona, resume=resume,
                                chat=True, extra_allow=["Bash(cic bus *)"], title=f"bus {name}: {message.get('body', '')}")
            session = result.meta.get("session_id") or result.meta.get("thread_id")
            if session:
                state["threads"][thread] = session
            reply = result.text if result.ok else f"[{name} could not answer] {result.error}"
            bus.send(name, message["from"], reply, thread=thread, kind="reply", reply_to=message["id"],
                     meta={"ok": result.ok, "job": result.meta.get("job_id"), "model": result.meta.get("model")})
            state["handled"] = int(state.get("handled", 0)) + 1
            state["last_message_at"] = now_iso()
            atomic_write_json(path, state)
    finally:
        state.update(status="stopped", stopped_at=now_iso())
        atomic_write_json(path, state)
    return 0


def start_detached(name: str, agent: str, *, cwd: str, access: str, role: str | None, poll: float,
                   idle_exit: float) -> int:
    existing = read_json(_state_path(name))
    if isinstance(existing, dict) and existing.get("status") == "running" and pid_alive(existing.get("pid")):
        raise CicError(f"bus agent {name!r} is already running (pid {existing['pid']})")
    src_dir = str(Path(__file__).resolve().parents[1])
    env = dict(os.environ)
    env["PYTHONPATH"] = src_dir + (os.pathsep + env["PYTHONPATH"] if env.get("PYTHONPATH") else "")
    argv = [sys.executable, "-m", "cic", "serve", "start", name, "--agent", agent, "--cwd", cwd, "--access", access,
            "--poll", str(poll), "--idle-exit", str(idle_exit), "--foreground"]
    if role:
        argv += ["--role", role]
    log = config.serve_dir() / f"{name.replace(':', '__')}.log"
    with open(log, "ab") as handle:
        proc = subprocess.Popen(argv, cwd=str(config.serve_dir()), env=env, stdin=subprocess.DEVNULL,
                                stdout=handle, stderr=subprocess.STDOUT, start_new_session=True)
    return proc.pid


def stop(name: str, grace: float = 15.0) -> dict:
    state = read_json(_state_path(name))
    if not isinstance(state, dict):
        raise CicError(f"no bus agent named {name!r}")
    if state.get("status") == "running" and pid_alive(state.get("pid")):
        bus.send("cic", name, "stop", kind="control")
        deadline = time.time() + grace
        while time.time() < deadline and pid_alive(state.get("pid")):
            time.sleep(0.5)
        if pid_alive(state.get("pid")):
            try:
                os.kill(state["pid"], signal.SIGTERM)
            except OSError:
                pass
    return read_json(_state_path(name)) or state
