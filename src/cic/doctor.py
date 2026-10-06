"""Environment checks with concrete fixes."""

from __future__ import annotations

import os
import re
import sys
from pathlib import Path

from . import agents, claude, config
from .util import oneline, run, which

SKILLS = ["claude-delegate", "claude-review", "claude-session", "claude-jobs", "claude-prompting",
          "claude-pair", "claude-council", "agent-bus", "claude-setup"]
MIN_CLAUDE = (2, 1, 259)  # --permission-prompts


def _version_tuple(text: str | None) -> tuple[int, ...]:
    match = re.search(r"(\d+)\.(\d+)\.(\d+)", text or "")
    return tuple(int(x) for x in match.groups()) if match else ()


def run_doctor(probe: bool = False) -> dict:
    checks: list[dict] = []

    def add(name: str, ok: bool, detail: str, fix: str | None = None, level: str = "error") -> None:
        checks.append({"check": name, "ok": ok, "level": "ok" if ok else level, "detail": detail, "fix": None if ok else fix})

    add("python", sys.version_info >= (3, 10), sys.version.split()[0], "Install Python 3.10 or newer.")

    sandbox = os.environ.get("CODEX_SANDBOX")
    add("not sandboxed", not sandbox, f"CODEX_SANDBOX={sandbox}" if sandbox else "running outside the Codex sandbox",
        "Install the exec-policy rule (install.sh) and call cic as one plain command so Codex runs it unsandboxed.")

    claude_bin = config.get("claude_bin")
    path = which(claude_bin)
    add("claude CLI", bool(path), path or f"{claude_bin} not found", "Install Claude Code: https://code.claude.com/docs")
    if path:
        version = claude.version()
        new_enough = _version_tuple(version) >= MIN_CLAUDE
        add("claude version", new_enough, version or "unknown",
            "Run `claude update` (needs >= 2.1.259 for --permission-prompts).", level="warn")
        auth = claude.auth_status() if not sandbox else {"loggedIn": False, "error": "skipped inside sandbox"}
        detail = (f"{auth.get('authMethod')} · {auth.get('subscriptionType') or auth.get('apiProvider') or ''}".strip(" ·")
                  if auth.get("loggedIn") else oneline(auth.get("error") or "not logged in", 160))
        add("claude login", bool(auth.get("loggedIn")), detail, "Run `claude auth login` in a normal terminal.")

    codex_bin = config.get("codex_bin")
    codex_path = which(codex_bin)
    if codex_path:
        _, out, _ = run([codex_bin, "--version"], timeout=20)
        add("codex CLI", True, oneline(out, 60))
    else:
        add("codex CLI", False, "not found (needed for pair/council with Codex)", "npm install -g @openai/codex", level="warn")

    gemini_bin = config.get("gemini_bin")
    gemini_path = which(gemini_bin)
    if not gemini_path:
        add("gemini CLI", False, "not found (optional council member)", "Install Gemini CLI or drop it from council members.", level="warn")
    elif probe:
        result = agents.run_gemini("Reply with exactly: PONG", cwd=os.getcwd(), timeout=90)
        add("gemini login", result.ok, "responding" if result.ok else (result.error or "failed"),
            "The free Code Assist login tier is no longer accepted; setting GEMINI_API_KEY (AI Studio key) is the likely fix.",
            level="warn")
    else:
        add("gemini CLI", True, f"{gemini_path} (auth not probed; use --probe)")

    cic_path = which("cic")
    add("cic on PATH", bool(cic_path), cic_path or "not found",
        "Run install.sh, or symlink bin/cic into a directory on PATH (e.g. ~/.local/bin).", level="warn")

    codex_home = Path(os.environ.get("CODEX_HOME") or Path.home() / ".codex")
    rule = codex_home / "rules" / "claude-in-codex.rules"
    if rule.exists() and codex_path:
        code, out, err = run([codex_bin, "execpolicy", "check", "--rules", str(rule), "--", "cic", "doctor"], timeout=20)
        allowed = '"allow"' in out or "allow" in out.lower()
        add("codex exec-policy rule", code == 0 and allowed, f"{rule} -> {oneline(out or err, 120)}",
            "Re-run install.sh or check the rule file syntax.")
    else:
        add("codex exec-policy rule", rule.exists(), str(rule) if rule.exists() else f"missing: {rule}",
            "Run install.sh (copies codex/rules/claude-in-codex.rules into ~/.codex/rules/).")

    skills_dir = codex_home / "skills"
    missing = [s for s in SKILLS if not (skills_dir / s / "SKILL.md").exists()]
    add("codex skills", not missing, "all installed" if not missing else "missing: " + ", ".join(missing),
        "Run install.sh to link the skills into ~/.codex/skills.", level="warn")

    try:
        test = config.home() / ".write-test"
        test.write_text("ok")
        test.unlink()
        add("state dir", True, str(config.home()))
    except OSError as exc:
        add("state dir", False, f"{config.home()}: {exc}", "Set CIC_HOME to a writable directory.")

    ok = all(c["ok"] or c["level"] != "error" for c in checks)
    return {"ok": ok, "checks": checks}


def render(result: dict) -> str:
    lines = [f"cic doctor: {'READY' if result['ok'] else 'NOT READY'}"]
    for check in result["checks"]:
        mark = "ok  " if check["ok"] else ("WARN" if check["level"] == "warn" else "FAIL")
        lines.append(f"[{mark}] {check['check']}: {check['detail']}")
        if check.get("fix"):
            lines.append(f"       fix: {check['fix']}")
    return "\n".join(lines) + "\n"
