"""File-based message bus for agent-to-agent IPC.

Every agent (``codex``, ``claude:reviewer``, ``gemini``, ``user`` ...) owns a
Maildir-style inbox under ``$CIC_HOME/bus/inbox/<agent>/{tmp,new,cur}``.

* send:  write to tmp/, then rename into new/ (atomic, never half-read)
* recv:  claim by renaming new/ -> cur/ (exactly one reader wins)
* every message is also appended to ``bus/threads/<thread>.jsonl``, the
  durable transcript of a conversation between agents

No daemon is required: any process that can run ``cic bus ...`` can take part,
whether it is Codex, a Claude Code session, Gemini CLI, or a shell script.
"""

from __future__ import annotations

import json
import os
import re
import time
import uuid
from pathlib import Path

from . import config
from .util import CicError, append_jsonl, atomic_write_json, new_id, now_iso, read_json

_AGENT = re.compile(r"^[A-Za-z0-9][A-Za-z0-9:._-]{0,63}$")
_THREAD = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,95}$")
KINDS = ("message", "task", "reply", "event", "control")


def _check_agent(name: str) -> str:
    if not _AGENT.match(name or ""):
        raise CicError(f"invalid agent name {name!r} (letters, digits, : . _ -)")
    return name


def _check_thread(thread: str) -> str:
    if not _THREAD.match(thread or ""):
        raise CicError(f"invalid thread name {thread!r} (letters, digits, . _ -)")
    return thread


def _inbox(agent: str) -> Path:
    root = config.bus_dir() / "inbox" / agent.replace(":", "__")
    for sub in ("tmp", "new", "cur"):
        (root / sub).mkdir(parents=True, exist_ok=True)
    return root


def _thread_path(thread: str) -> Path:
    return config.bus_dir() / "threads" / f"{thread}.jsonl"


def send(sender: str, to: str | list[str], body: str, *, thread: str | None = None, kind: str = "message",
         reply_to: str | None = None, meta: dict | None = None) -> dict:
    _check_agent(sender)
    recipients = [r.strip() for r in (to.split(",") if isinstance(to, str) else to) if r and r.strip()]
    if not recipients:
        raise CicError("no recipients")
    for recipient in recipients:
        _check_agent(recipient)
    if kind not in KINDS:
        raise CicError(f"invalid kind {kind!r}; choose from {', '.join(KINDS)}")
    thread = _check_thread(thread) if thread else new_id("t")
    message = {
        "id": f"m-{uuid.uuid4().hex[:12]}",
        "ts": now_iso(),
        "from": sender,
        "to": recipients,
        "thread": thread,
        "kind": kind,
        "reply_to": reply_to,
        "body": body,
        "meta": meta or {},
    }
    filename = f"{time.time():.6f}-{message['id']}.json"
    for recipient in recipients:
        inbox = _inbox(recipient)
        atomic_write_json(inbox / "tmp" / filename, message)
        os.replace(inbox / "tmp" / filename, inbox / "new" / filename)
    append_jsonl(_thread_path(thread), message)
    return message


def record(sender: str, to: str | list[str], body: str, *, thread: str, kind: str = "message",
           meta: dict | None = None) -> dict:
    """Append to a thread transcript without delivering to inboxes (for orchestrated exchanges)."""
    recipients = [r for r in (to.split(",") if isinstance(to, str) else to) if r]
    message = {
        "id": f"m-{uuid.uuid4().hex[:12]}",
        "ts": now_iso(),
        "from": sender,
        "to": recipients,
        "thread": _check_thread(thread),
        "kind": kind,
        "reply_to": None,
        "body": body,
        "meta": meta or {},
    }
    append_jsonl(_thread_path(thread), message)
    return message


def recv(agent: str, *, thread: str | None = None, sender: str | None = None, reply_to: str | None = None,
         wait: float = 0.0, limit: int = 10, peek: bool = False) -> list[dict]:
    """Claim matching messages from an inbox, waiting up to ``wait`` seconds for the first."""
    inbox = _inbox(_check_agent(agent))
    deadline = time.time() + max(0.0, wait)
    delay = 0.2
    while True:
        found: list[dict] = []
        for name in sorted(os.listdir(inbox / "new")):
            path = inbox / "new" / name
            message = read_json(path)
            if not isinstance(message, dict):
                continue
            if thread and message.get("thread") != thread:
                continue
            if sender and message.get("from") != sender:
                continue
            if reply_to and message.get("reply_to") != reply_to:
                continue
            if not peek:
                try:
                    os.replace(path, inbox / "cur" / name)
                except FileNotFoundError:
                    continue  # another reader claimed it first
            found.append(message)
            if len(found) >= limit:
                break
        if found or time.time() >= deadline:
            return found
        time.sleep(min(delay, max(0.0, deadline - time.time())))
        delay = min(delay * 1.5, 1.0)


def ask(sender: str, to: str, body: str, *, thread: str | None = None, wait: float = 300.0,
        kind: str = "task") -> tuple[dict, dict | None]:
    """Send and block until the recipient replies to this exact message (or wait expires)."""
    message = send(sender, to, body, thread=thread, kind=kind)
    replies = recv(sender, thread=message["thread"], reply_to=message["id"], wait=wait, limit=1)
    return message, (replies[0] if replies else None)


def transcript(thread: str) -> list[dict]:
    path = _thread_path(_check_thread(thread))
    messages = []
    if path.exists():
        for line in path.read_text(encoding="utf-8").splitlines():
            try:
                messages.append(json.loads(line))
            except ValueError:
                continue
    return messages


def threads(limit: int = 30) -> list[dict]:
    root = config.bus_dir() / "threads"
    if not root.exists():
        return []
    rows = []
    for path in sorted(root.glob("*.jsonl"), key=lambda p: p.stat().st_mtime, reverse=True)[:limit]:
        messages = transcript(path.stem)
        if not messages:
            continue
        participants = sorted({m.get("from") for m in messages} | {t for m in messages for t in m.get("to", [])})
        rows.append({"thread": path.stem, "messages": len(messages), "last": messages[-1].get("ts"),
                     "participants": participants})
    return rows


def agents() -> list[dict]:
    root = config.bus_dir() / "inbox"
    if not root.exists():
        return []
    rows = []
    for inbox in sorted(root.iterdir()):
        if inbox.is_dir():
            unread = len(os.listdir(inbox / "new")) if (inbox / "new").exists() else 0
            rows.append({"agent": inbox.name.replace("__", ":"), "unread": unread})
    return rows


def format_message(message: dict, *, full: bool = True) -> str:
    head = f"[{message.get('ts')}] {message.get('from')} -> {', '.join(message.get('to', []))} ({message.get('kind')}, {message.get('id')}"
    if message.get("reply_to"):
        head += f", reply to {message['reply_to']}"
    head += f", thread {message.get('thread')})"
    body = message.get("body") or ""
    if not full and len(body) > 400:
        body = body[:400] + "…"
    return f"{head}\n{body}\n"
