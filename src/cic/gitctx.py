"""Collect bounded git context for reviews and pair loops.

Large diffs are not inlined: the reviewer gets the stat and file list and reads
the rest itself with git, so the prompt stays small and the cache stays warm.
"""

from __future__ import annotations

from .util import run

INLINE_LIMIT = 60_000


def _git(cwd: str, *args: str, timeout: float = 60) -> tuple[int, str]:
    code, out, _ = run(["git", *args], cwd=cwd, timeout=timeout)
    return code, out


def is_repo(cwd: str) -> bool:
    return _git(cwd, "rev-parse", "--is-inside-work-tree")[0] == 0


def has_head(cwd: str) -> bool:
    return _git(cwd, "rev-parse", "--verify", "HEAD")[0] == 0


def detect_base(cwd: str) -> str | None:
    code, out = _git(cwd, "symbolic-ref", "--quiet", "--short", "refs/remotes/origin/HEAD")
    if code == 0 and out.strip():
        return out.strip()
    for candidate in ("origin/main", "origin/master", "main", "master"):
        if _git(cwd, "rev-parse", "--verify", "--quiet", candidate)[0] == 0:
            return candidate
    return None


def _changed_lines(numstat: str) -> int:
    total = 0
    for line in numstat.splitlines():
        parts = line.split("\t")
        if len(parts) >= 2:
            for value in parts[:2]:
                if value.isdigit():
                    total += int(value)
    return total


def working_tree(cwd: str, limit: int = INLINE_LIMIT) -> dict:
    if not is_repo(cwd):
        return {"repo": False, "label": "working directory (not a git repository)", "diff": "", "stat": "",
                "untracked": [], "changed_lines": 0, "inline": False, "empty": False}
    ref = ["HEAD"] if has_head(cwd) else []
    _, stat = _git(cwd, "diff", *ref, "--stat")
    _, numstat = _git(cwd, "diff", *ref, "--numstat")
    _, diff = _git(cwd, "diff", *ref)
    if not ref:  # repository without commits: include staged files too
        _, staged = _git(cwd, "diff", "--cached")
        diff = staged + diff
    _, untracked = _git(cwd, "ls-files", "--others", "--exclude-standard")
    untracked_files = [line for line in untracked.splitlines() if line.strip()]
    inline = len(diff) <= limit
    return {
        "repo": True,
        "label": "uncommitted working-tree changes",
        "diff": diff if inline else "",
        "stat": stat.strip(),
        "untracked": untracked_files,
        "changed_lines": _changed_lines(numstat),
        "inline": inline,
        "empty": not diff.strip() and not untracked_files,
        "diff_command": "git diff" + (" HEAD" if ref else ""),
    }


def branch(cwd: str, base: str, limit: int = INLINE_LIMIT) -> dict:
    span = f"{base}...HEAD"
    _, stat = _git(cwd, "diff", span, "--stat")
    _, numstat = _git(cwd, "diff", span, "--numstat")
    _, diff = _git(cwd, "diff", span)
    _, log = _git(cwd, "log", "--oneline", f"{base}..HEAD")
    inline = len(diff) <= limit
    return {
        "repo": True,
        "label": f"branch changes vs {base}",
        "diff": diff if inline else "",
        "stat": stat.strip(),
        "commits": log.strip(),
        "untracked": [],
        "changed_lines": _changed_lines(numstat),
        "inline": inline,
        "empty": not diff.strip(),
        "diff_command": f"git diff {span}",
    }


def resolve(cwd: str, scope: str = "auto", base: str | None = None) -> dict:
    if scope == "branch" or (scope == "auto" and base):
        base = base or detect_base(cwd)
        if not base:
            raise ValueError("could not detect a base branch; pass --base <ref>")
        return branch(cwd, base)
    tree = working_tree(cwd)
    if scope == "auto" and tree.get("empty") and tree.get("repo"):
        detected = detect_base(cwd)
        if detected:
            return branch(cwd, detected)
    return tree


def render_for_prompt(ctx: dict) -> str:
    parts = []
    if ctx.get("commits"):
        parts.append(f"Commits:\n{ctx['commits']}")
    if ctx.get("stat"):
        parts.append(f"Diff stat:\n{ctx['stat']}")
    if ctx.get("untracked"):
        parts.append("Untracked files (read them directly):\n" + "\n".join(f"- {f}" for f in ctx["untracked"][:50]))
    if ctx.get("inline") and ctx.get("diff"):
        parts.append(f"Diff:\n```diff\n{ctx['diff'].rstrip()}\n```")
    elif ctx.get("repo"):
        parts.append(f"The diff is too large to inline. Inspect it yourself with `{ctx.get('diff_command', 'git diff')}` "
                     "(per file: append `-- <path>`).")
    return "\n\n".join(parts) if parts else "(no changes found)"
