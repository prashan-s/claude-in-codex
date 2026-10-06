"""Uniform adapters for the three agent CLIs.

Agent specs: ``claude[:model]``, ``codex[:model]``, ``gemini[:model]``.
Claude runs go through the cic job machinery (tracked, verifiable, resumable);
Codex uses ``codex exec --json``; Gemini uses ``gemini -p --output-format json``.
"""

from __future__ import annotations

import copy
import json
import re
import shutil
import subprocess
import tempfile
from dataclasses import dataclass, field
from pathlib import Path

from . import config, jobs, prompts, router
from .util import child_env, oneline, which

VENDORS = ("claude", "codex", "gemini")


@dataclass
class AgentResult:
    spec: str
    ok: bool
    text: str
    data: dict | None = None
    error: str | None = None
    meta: dict = field(default_factory=dict)


def parse_spec(spec: str) -> tuple[str, str | None]:
    vendor, _, model = spec.strip().partition(":")
    vendor = vendor.lower()
    if vendor not in VENDORS:
        raise ValueError(f"unknown agent {spec!r}; use claude[:model], codex[:model], or gemini[:model]")
    return vendor, (model or None)


def run(spec: str, prompt: str, *, cwd: str, kind: str = "ask", schema: str | None = None, access: str = "read",
        role: str | None = None, resume: str | None = None, parent: str | None = None, title: str | None = None,
        verify: list[str] | None = None, max_attempts: int = 1, chat: bool = False,
        extra_allow: list[str] | None = None) -> AgentResult:
    vendor, model = parse_spec(spec)
    if vendor == "claude":
        return run_claude(prompt, cwd=cwd, model=model, kind=kind, schema=schema, access=access, role=role,
                          resume=resume, parent=parent, title=title or prompt, verify=verify,
                          max_attempts=max_attempts, chat=chat, spec=spec, extra_allow=extra_allow)
    if vendor == "codex":
        return run_codex(prompt, cwd=cwd, model=model, write=access != "read", schema=schema, resume=resume, spec=spec)
    return run_gemini(prompt, cwd=cwd, model=model, write=access != "read", schema=schema, spec=spec)


# ----------------------------------------------------------------- claude

def run_claude(prompt: str, *, cwd: str, model: str | None, kind: str, schema: str | None, access: str,
               role: str | None, resume: str | None, parent: str | None, title: str, verify: list[str] | None,
               max_attempts: int, chat: bool, spec: str = "claude", extra_allow: list[str] | None = None) -> AgentResult:
    from .worker import JobRunner  # local import: worker imports this module's siblings

    route = router.route(prompt, kind=kind, model=model, access=access)
    params = {
        "task": prompt,
        "kind": route.kind,
        "model": route.model,
        "effort": route.effort,
        "fallback": route.fallback,
        "access": route.access,
        "cwd": cwd,
        "schema": schema,
        "verify": verify or [],
        "max_attempts": max_attempts,
        "escalate": not route.explicit_model,
        "resume": resume,
        "allow": list(extra_allow or []),
        "route": route.to_dict(),
    }
    job = jobs.create(route.kind if not chat else "say", cwd=cwd, title=title, params=params, parent=parent)
    jobs.write_file(job, "system.md", prompts.contract_for(route.kind, chat=chat, role=role))
    jobs.write_file(job, "brief.md", prompt)
    finished = JobRunner(job["id"]).run()
    text = jobs.read_final(finished["id"]) if finished.get("report") else (finished.get("result_text") or "")
    ok = finished.get("status") == "done"
    return AgentResult(
        spec=spec,
        ok=ok,
        text=text.strip(),
        data=finished.get("report"),
        error=None if ok else (finished.get("reason") or finished.get("status")),
        meta={
            "job_id": finished["id"],
            "session_id": finished.get("session_id"),
            "status": finished.get("status"),
            "model": finished.get("model_final"),
            "cost_usd": finished.get("cost_usd"),
        },
    )


# ----------------------------------------------------------------- codex

def strict_schema(schema: dict) -> dict:
    """Codex structured output rejects some JSON Schema keywords; drop them."""
    clean = copy.deepcopy(schema)

    def walk(node):
        if isinstance(node, dict):
            for key in ("minimum", "maximum", "format"):
                node.pop(key, None)
            for value in node.values():
                walk(value)
        elif isinstance(node, list):
            for value in node:
                walk(value)

    walk(clean)
    return clean


def run_codex(prompt: str, *, cwd: str, model: str | None = None, write: bool = False, schema: str | None = None,
              resume: str | None = None, spec: str = "codex", timeout: float = 1800) -> AgentResult:
    from .schemas import BY_NAME

    binary = config.get("codex_bin")
    if not which(binary):
        return AgentResult(spec, False, "", error="codex CLI not found on PATH")
    tmp = Path(tempfile.mkdtemp(prefix="cic-codex-"))
    last = tmp / "last.txt"
    try:
        if resume:
            argv = [binary, "exec", "resume", "--json", "--skip-git-repo-check", "-o", str(last),
                    "-c", f'sandbox_mode="{"workspace-write" if write else "read-only"}"']
        else:
            argv = [binary, "exec", "--json", "--skip-git-repo-check", "-C", cwd,
                    "-s", "workspace-write" if write else "read-only", "-o", str(last)]
        if model:
            argv += ["-m", model]
        if schema:
            schema_path = tmp / "schema.json"
            schema_path.write_text(json.dumps(strict_schema(BY_NAME[schema])), encoding="utf-8")
            argv += ["--output-schema", str(schema_path)]
        argv.append("--")
        if resume:
            argv.append(resume)
        argv.append(prompt)
        try:
            proc = subprocess.run(argv, cwd=cwd, env=child_env(), stdin=subprocess.DEVNULL, capture_output=True,
                                  text=True, errors="replace", timeout=timeout)
        except subprocess.TimeoutExpired:
            return AgentResult(spec, False, "", error=f"codex timed out after {int(timeout)}s")
        thread_id, messages, failures, usage = None, [], [], None
        for line in proc.stdout.splitlines():
            try:
                event = json.loads(line)
            except ValueError:
                continue
            etype = event.get("type")
            if etype == "thread.started":
                thread_id = event.get("thread_id")
            elif etype == "item.completed":
                item = event.get("item") or {}
                if item.get("type") == "agent_message" and item.get("text"):
                    messages.append(item["text"])
            elif etype == "turn.completed":
                usage = event.get("usage")
            elif etype in ("turn.failed", "error"):
                failures.append(oneline(json.dumps(event.get("error") or event), 300))
        text = last.read_text(encoding="utf-8").strip() if last.exists() else ""
        text = text or (messages[-1] if messages else "")
        data = None
        if schema and text:
            try:
                data = json.loads(text)
            except ValueError:
                data = None
        ok = proc.returncode == 0 and bool(text) and not failures
        error = None if ok else (failures[-1] if failures else oneline(proc.stderr.strip()[-400:] or f"exit {proc.returncode}", 300))
        return AgentResult(spec, ok, text, data, error, meta={"thread_id": thread_id, "usage": usage})
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


# ----------------------------------------------------------------- gemini

_GEMINI_AUTH = re.compile(r"IneligibleTier|no longer supported|login|authenticat|credential|GEMINI_API_KEY", re.I)


def run_gemini(prompt: str, *, cwd: str, model: str | None = None, write: bool = False, schema: str | None = None,
               spec: str = "gemini", timeout: float = 900) -> AgentResult:
    from .schemas import BY_NAME

    binary = config.get("gemini_bin")
    if not which(binary):
        return AgentResult(spec, False, "", error="gemini CLI not found on PATH")
    if schema:
        prompt += ("\n\nReturn ONLY a JSON object (no prose, no code fences) matching this JSON Schema:\n"
                   + json.dumps(BY_NAME[schema]))
    argv = [binary, "-p", prompt, "--output-format", "json", "--approval-mode", "auto_edit" if write else "plan",
            "--skip-trust"]
    if model:
        argv += ["-m", model]
    try:
        proc = subprocess.run(argv, cwd=cwd, env=child_env(), stdin=subprocess.DEVNULL, capture_output=True,
                              text=True, errors="replace", timeout=timeout)
    except subprocess.TimeoutExpired:
        return AgentResult(spec, False, "", error=f"gemini timed out after {int(timeout)}s")
    payload = None
    start = proc.stdout.find("{")
    if start >= 0:
        try:
            payload = json.loads(proc.stdout[start:])
        except ValueError:
            payload = None
    if proc.returncode != 0 or not isinstance(payload, dict) or payload.get("error"):
        detail = ""
        if isinstance(payload, dict) and payload.get("error"):
            detail = json.dumps(payload["error"])
        detail = detail or proc.stderr.strip() or proc.stdout.strip() or f"exit {proc.returncode}"
        lines = [l for l in detail.splitlines() if l.strip()]
        first = next((l for l in lines if _GEMINI_AUTH.search(l)), lines[0] if lines else detail)
        kind = "unavailable (auth/tier)" if _GEMINI_AUTH.search(detail) else "failed"
        return AgentResult(spec, False, "", error=f"gemini {kind}: {oneline(first, 240)}")
    text = str(payload.get("response") or "").strip()
    data = None
    if schema and text:
        match = re.search(r"\{.*\}", text, re.S)
        if match:
            try:
                data = json.loads(match.group(0))
            except ValueError:
                data = None
    return AgentResult(spec, bool(text), text, data, None if text else "empty response",
                       meta={"stats": payload.get("stats")})
