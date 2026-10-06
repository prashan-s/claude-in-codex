"""cic: control Claude Code from Codex (or any agent) through one CLI.

Exit codes: 0 done · 1 failed/cancelled/error · 2 usage · 3 still running
(wait timed out) · 4 needs attention (partial, needs_input, blocked) ·
5 delegation depth limit · 6 running inside the Codex sandbox.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import uuid

from . import __version__, config, gitctx, jobs, prompts, router, sessions
from .claude import ClaudeSpec, build_argv, printable_argv
from .render import render_final, render_jobs, render_status
from .util import CicError, oneline

EXIT = {"done": 0, "partial": 4, "needs_input": 4, "blocked": 4, "failed": 1, "cancelled": 1}
_SCHEMA_FOR_KIND = {"review": "review", "plan": "plan"}


# ----------------------------------------------------------------- helpers

def _cwd(value: str | None) -> str:
    path = os.path.abspath(os.path.expanduser(value or os.getcwd()))
    if not os.path.isdir(path):
        raise CicError(f"--cwd {path} is not a directory", code=2)
    return path


def _text(arg: str | None, file: str | None, what: str) -> str:
    if file:
        with open(os.path.expanduser(file), encoding="utf-8") as handle:
            return handle.read()
    if arg == "-" or (arg is None and not sys.stdin.isatty()):
        data = sys.stdin.read()
        if data.strip():
            return data
    if not arg or not arg.strip():
        raise CicError(f"missing {what}", code=2)
    return arg


def _print(text: str) -> None:
    sys.stdout.write(text if text.endswith("\n") else text + "\n")
    sys.stdout.flush()


def _summary(job: dict) -> dict:
    progress = job.get("progress") or {}
    return {
        "id": job["id"],
        "kind": job.get("kind"),
        "status": job.get("status"),
        "verified": job.get("verified"),
        "reason": job.get("reason"),
        "report": job.get("report"),
        "result_text": job.get("result_text"),
        "verification": job.get("verification"),
        "files_edited": progress.get("files"),
        "denials": progress.get("denials"),
        "warnings": job.get("warnings"),
        "session_id": job.get("session_id"),
        "model": job.get("model_final") or (job.get("params") or {}).get("model"),
        "escalations": job.get("escalations"),
        "cost_usd": job.get("cost_usd"),
        "tokens": job.get("tokens"),
        "elapsed_s": round(job.get("elapsed") or 0, 1),
        "thread": job.get("thread"),
    }


def _finish_or_status(job_id: str, timeout: float, as_json: bool) -> int:
    job = jobs.wait(job_id, timeout)
    if job.get("status") in jobs.TERMINAL:
        if as_json:
            _print(json.dumps(_summary(job), indent=2, ensure_ascii=False))
        else:
            _print(jobs.read_final(job_id) or render_final(job))
        return EXIT.get(job["status"], 1)
    if as_json:
        _print(json.dumps({**_summary(job), "still_running": True}, indent=2))
    else:
        _print(render_status(job) + f"Still running after {int(timeout)}s. Keep waiting with: cic wait {job_id} --timeout 300")
    return 3


def _launch(job: dict, args, start_line: str) -> int:
    jobs.spawn(job)
    _print(start_line)
    if getattr(args, "background", False):
        _print(f"Running in the background. Check: `cic status {job['id']}` · wait: `cic wait {job['id']} --timeout 300` · "
               f"steer: `cic steer {job['id']} \"<message>\"` · stop: `cic cancel {job['id']}`")
        return 0
    timeout = args.wait if getattr(args, "wait", None) is not None else config.get("wait_seconds")
    return _finish_or_status(job["id"], float(timeout), getattr(args, "json", False))


def _profile(args) -> str:
    """Context profile: --profile, else --lean, else config (see claude.PROFILES)."""
    if getattr(args, "profile", None):
        return args.profile
    if getattr(args, "lean", False) or config.get("lean"):
        return "lean"
    return str(config.get("profile"))


def _guards(dry_run: bool = False) -> None:
    jobs.guard_depth()
    if not dry_run:
        jobs.guard_sandbox()


def _route_args(args, task: str, *, kind: str | None = None) -> router.Route:
    model = args.model or (router.TIER_ALIASES.get(args.tier) if getattr(args, "tier", None) else None)
    default = config.get("default_model")
    access = "read" if getattr(args, "read_only", False) else getattr(args, "access", None)
    return router.route(task, kind=kind or getattr(args, "kind", None), model=model, effort=args.effort,
                        access=access, files=len(getattr(args, "file", None) or []),
                        default_model=None if model or default == "auto" else default)


# ----------------------------------------------------------------- run

def _examples(values: list[str] | None, cwd: str) -> list[str]:
    """--example takes literal text or @path (read relative to --cwd)."""
    found = []
    for value in values or []:
        if value.startswith("@"):
            path = os.path.join(cwd, os.path.expanduser(value[1:]))
            try:
                with open(path, encoding="utf-8") as handle:
                    found.append(handle.read()[:8000])
            except OSError as exc:
                raise CicError(f"--example {value}: {exc}", code=2)
        else:
            found.append(value)
    return found


def _images(values: list[str] | None, cwd: str) -> list[str]:
    from .claude import image_block

    paths = []
    for value in values or []:
        path = value if os.path.isabs(value) else os.path.join(cwd, os.path.expanduser(value))
        if not os.path.isfile(path):
            raise CicError(f"--image {value}: file not found", code=2)
        try:
            image_block(path)  # validate type and size now, not inside the worker
        except ValueError as exc:
            raise CicError(f"--image {value}: {exc}", code=2)
        paths.append(os.path.abspath(path))
    return paths


def cmd_run(args) -> int:
    task = _text(args.task, args.task_file, "task text")
    cwd = _cwd(args.cwd)
    _guards(args.dry_run)
    r = _route_args(args, task)
    kind = r.kind
    write = kind in router.WRITE_KINDS and r.access != "read"
    schema = _SCHEMA_FOR_KIND.get(kind) or ("task" if kind in router.WRITE_KINDS else None)
    max_attempts = args.max_attempts or (int(config.get("max_attempts")) if write else 1)
    escalate = args.escalate if args.escalate is not None else not r.explicit_model
    lean = args.lean or bool(config.get("lean"))
    hints = args.hint or []
    examples = _examples(args.example, cwd)
    if not examples and prompts.wants_message_examples(task, kind):
        recent = prompts.repo_message_examples(cwd)
        if recent:  # few-shot from the repository's own history
            examples = ["Recent commit subjects in this repository:\n" + "\n".join(recent)]
    images = _images(args.image, cwd)
    techniques = prompts.techniques_for(kind, hints=bool(hints), examples=bool(examples), images=bool(images),
                                        plan=args.plan)
    params = {
        "task": task, "kind": kind, "model": r.model, "effort": r.effort, "fallback": r.fallback,
        "access": r.access, "cwd": cwd, "schema": schema, "files": args.file or [], "context": args.context or [],
        "context_files": args.context_file or [], "criteria": args.done or [], "verify": args.verify or [],
        "constraints": args.constraint or [], "allow": args.allow or [], "deny": args.deny or [],
        "allow_git_write": args.allow_git_write, "max_attempts": max_attempts, "escalate": escalate,
        "allow_fable": args.allow_fable or bool(config.get("allow_fable_escalation")),
        "max_turns": args.max_turns, "budget": args.budget, "timeout": args.timeout, "worktree": args.worktree,
        "add_dirs": args.add_dir or [], "lean": lean, "profile": _profile(args), "plan": args.plan,
        "plan_model": args.plan_model,
        "read_only": r.access == "read", "name": args.name, "route": r.to_dict(), "hints": hints,
        "examples": examples, "images": images, "techniques": [name for name, _ in techniques],
    }
    warnings = list(r.warnings) + prompts.lint_brief(task, kind=kind, criteria=args.done, verify=args.verify,
                                                     files=args.file, context=args.context,
                                                     context_files=args.context_file, tier=r.tier, plan=args.plan)
    system = prompts.contract_for(kind)
    if args.plan:
        brief = None
        plan_brief = prompts.build_plan_brief(task, cwd=cwd, files=args.file, context=args.context,
                                              context_files=args.context_file, criteria=args.done, verify=args.verify,
                                              constraints=args.constraint, hints=hints)
    else:
        plan_brief = None
        brief = prompts.build_brief(task, kind=kind, cwd=cwd, files=args.file, context=args.context,
                                    context_files=args.context_file, criteria=args.done, verify=args.verify,
                                    constraints=args.constraint, read_only=r.access == "read", hints=hints,
                                    examples=examples, image_count=len(images))
    if args.dry_run:
        spec = ClaudeSpec(model=r.model, cwd=cwd, access=r.access, effort=r.effort, fallback=r.fallback,
                          session_id="<pre-assigned>", schema={} if schema else None, system_file="<system.md>",
                          allow=args.allow or [], deny=args.deny or [], verify=args.verify or [],
                          allow_git_write=args.allow_git_write, max_turns=args.max_turns, budget_usd=args.budget,
                          worktree=args.worktree, add_dirs=args.add_dir or [], profile=_profile(args))
        out = [f"route: {r.kind} -> {r.label()} · access {r.access} · fallback {','.join(r.fallback) or '-'} · "
               f"attempts {max_attempts} · escalate {escalate} · schema {schema or 'text'}",
               "why: " + "; ".join(r.reasons),
               "techniques (promptingguide.ai): " + "; ".join(f"{n}: {how}" for n, how in techniques)]
        if images:
            out.append(f"images: {len(images)} attached")
        out += [f"warning: {w}" for w in warnings]
        out += ["", "argv: " + printable_argv(build_argv(spec)), "", "----- system (appended) -----", system,
                "----- " + ("plan brief" if args.plan else "brief") + " -----", plan_brief or brief or ""]
        _print("\n".join(out))
        return 0
    job = jobs.create(kind, cwd=cwd, title=task, params=params)
    jobs.write_file(job, "system.md", system)
    if args.plan:
        jobs.write_file(job, "plan-brief.md", plan_brief)
        jobs.write_file(job, "system-plan.md", prompts.contract_for("plan"))
    else:
        jobs.write_file(job, "brief.md", brief)
    if warnings:
        job["warnings"] = warnings
        jobs.save(job)
    line = (f"cic: job {job['id']} started · {kind} · {r.label()} · access {r.access}"
            + (" · plan-first (opus plans, then executes)" if args.plan else ""))
    if warnings:
        line += "\n" + "\n".join(f"cic: note: {w}" for w in warnings)
    return _launch(job, args, line)


def cmd_ask(args) -> int:
    question = _text(args.question, args.task_file, "question")
    cwd = _cwd(args.cwd)
    _guards()
    kind = args.kind or router.infer_kind(question)[0]
    if kind in router.WRITE_KINDS:
        kind = "explain"
    if kind == "plan":
        kind = "research"
    args.read_only = True
    r = _route_args(args, question, kind=kind)
    images = _images(args.image, cwd)
    params = {"task": question, "kind": kind, "model": r.model, "effort": r.effort, "fallback": r.fallback,
              "access": "read", "cwd": cwd, "schema": None, "max_attempts": 1, "escalate": False,
              "add_dirs": args.add_dir or [], "profile": _profile(args), "route": r.to_dict(),
              "images": images, "hints": args.hint or []}
    job = jobs.create(kind, cwd=cwd, title=question, params=params)
    jobs.write_file(job, "system.md", prompts.contract_for(kind))
    jobs.write_file(job, "brief.md", prompts.build_brief(question, kind=kind, cwd=cwd, files=args.file,
                                                          context=args.context, read_only=True, hints=args.hint,
                                                          image_count=len(images)))
    return _launch(job, args, f"cic: job {job['id']} · {kind} · {r.label()} · read-only")


def cmd_improve(args) -> int:
    """APE: have Claude critique and rewrite a brief (read-only, grounded in the repo)."""
    task = _text(args.task, args.task_file, "brief to improve")
    cwd = _cwd(args.cwd)
    _guards()
    kind = args.kind or router.infer_kind(task)[0]
    model = router.normalize_model(args.model) or "sonnet"
    route = router.route(task, kind=kind, model=model, effort=args.effort or "medium", access="read")
    params = {"task": task, "kind": "improve", "model": route.model, "effort": route.effort,
              "fallback": route.fallback, "access": "read", "cwd": cwd, "schema": "improve", "max_attempts": 1,
              "escalate": False, "profile": _profile(args), "route": route.to_dict(), "target_kind": kind}
    job = jobs.create("improve", cwd=cwd, title=f"improve brief: {task}", params=params)
    jobs.write_file(job, "system.md", prompts.contract_for("improve"))
    jobs.write_file(job, "brief.md", prompts.build_improve_prompt(task, kind=kind, cwd=cwd))
    return _launch(job, args, f"cic: job {job['id']} · improving a {kind} brief · {route.label()} · read-only")


def cmd_setup(args) -> int:
    """Finish an install done via `npx skills add` + pip/uv: write the Codex exec-policy rule, then run doctor."""
    from . import doctor

    codex_home = os.path.expanduser(args.codex_home or os.environ.get("CODEX_HOME") or "~/.codex")
    if not args.no_rule:
        rules_dir = os.path.join(codex_home, "rules")
        os.makedirs(rules_dir, exist_ok=True)
        paths = ["cic"]
        if os.path.basename(sys.argv[0]) == "cic":  # also allow the absolute paths Codex may type
            for candidate in (os.path.abspath(sys.argv[0]), os.path.realpath(sys.argv[0])):
                if candidate not in paths:
                    paths.append(candidate)
        rules = [
            "# claude-in-codex: let Codex run the cic CLI outside its sandbox (Claude Code needs its keychain login).",
            "# Trade-off: anything passed to cic (including --verify commands) then runs unsandboxed without a prompt.",
        ]
        for entry in paths:
            rules.append(f'prefix_rule(pattern = ["{entry}"], decision = "allow", '
                         'justification = "claude-in-codex: headless Claude Code needs keychain login and ~/.claude")')
        target = os.path.join(rules_dir, "claude-in-codex.rules")
        with open(target, "w", encoding="utf-8") as handle:
            handle.write("\n".join(rules) + "\n")
        _print(f"wrote {target}")
    os.environ["CODEX_HOME"] = codex_home  # doctor checks the same Codex home we just wrote to
    result = doctor.run_doctor()
    _print(doctor.render(result) + "Restart Codex so it loads the skills and the rule.")
    return 0 if result["ok"] else 1


def cmd_review(args) -> int:
    cwd = _cwd(args.cwd)
    _guards(args.dry_run)
    try:
        ctx = gitctx.resolve(cwd, args.scope, args.base)
    except ValueError as exc:
        raise CicError(str(exc), code=2)
    if not ctx.get("repo"):
        raise CicError("cic review needs a git repository (use `cic run --kind review` for loose files)", code=2)
    if ctx.get("empty"):
        _print("Nothing to review: no uncommitted changes and no branch diff found.")
        return 0
    focus = " ".join(args.focus) if args.focus else None
    model = args.model
    if not model and (args.adversarial or ctx.get("changed_lines", 0) > 1500):
        model = "opus"
    r = router.route((focus or "") + " review", kind="review", model=model, effort=args.effort or "high", access="read")
    prompt = prompts.build_review_prompt(label=ctx["label"], change_text=gitctx.render_for_prompt(ctx), focus=focus,
                                         adversarial=args.adversarial)
    if args.dry_run:
        _print(f"route: review -> {r.label()} ({ctx['label']}, {ctx.get('changed_lines', 0)} changed lines)\n\n{prompt}")
        return 0
    params = {"task": prompt, "kind": "review", "model": r.model, "effort": r.effort, "fallback": r.fallback,
              "access": "read", "cwd": cwd, "schema": "review", "max_attempts": 1, "escalate": False,
              "profile": _profile(args), "route": r.to_dict(),
              "review": {"label": ctx["label"], "adversarial": args.adversarial, "focus": focus}}
    title = f"{'adversarial ' if args.adversarial else ''}review of {ctx['label']}" + (f": {focus}" if focus else "")
    job = jobs.create("review", cwd=cwd, title=title, params=params)
    jobs.write_file(job, "system.md", prompts.contract_for("review"))
    jobs.write_file(job, "brief.md", prompt)
    return _launch(job, args, f"cic: job {job['id']} · review of {ctx['label']} ({ctx.get('changed_lines', 0)} lines) · {r.label()}")


# ----------------------------------------------------------------- sessions

def cmd_session(args) -> int:
    if args.action == "new":
        cwd = _cwd(args.cwd)
        model = args.model or "sonnet"
        record = sessions.create(args.name, cwd=cwd, model=router.normalize_model(model) or "sonnet",
                                 effort=args.effort, access=args.access or "read", role=args.role)
        _print(f"session {record['name']} ready · {record['model']} · access {record['access']} · cwd {cwd}\n"
               f'talk: cic say {record["name"]} "<message>"')
        return 0
    if args.action == "list":
        rows = sessions.list_all()
        if not rows:
            _print("No sessions.")
            return 0
        lines = ["| session | model | turns | access | last job | cwd |", "|---|---|---|---|---|---|"]
        for s in rows:
            lines.append(f"| {s['name']} | {s.get('last_model') or s.get('model')} | {s.get('turns', 0)} | "
                         f"{s.get('access')} | {s.get('last_job') or '-'} | {s.get('cwd')} |")
        _print("\n".join(lines))
        return 0
    if args.action == "show":
        record = sessions.load(args.name)
        if not record:
            raise CicError(f"no session {args.name!r}")
        _print(json.dumps(record, indent=2))
        return 0
    if args.action == "rm":
        _print("removed" if sessions.remove(args.name) else "not found")
        return 0
    raise CicError("unknown session action", code=2)


def cmd_say(args) -> int:
    message = _text(args.message, args.task_file, "message")
    _guards()
    record = sessions.load(args.name)
    if not record:
        cwd = _cwd(args.cwd)
        record = sessions.create(args.name, cwd=cwd, model=router.normalize_model(args.model) or "sonnet",
                                 effort=args.effort, access=args.access or "read", role=args.role)
    cwd = record["cwd"]
    model = router.normalize_model(args.model) or record["model"]
    if args.model and model != record["model"]:
        record["model"] = model  # stays on the new model from here on (one cache rebuild)
        sessions.save(record)
    started = bool(record.get("started"))
    if not started:
        message = prompts.chat_opening(message, cwd=cwd)  # ground the conversation once: cwd, git, date
    images = _images(args.image, cwd)
    if images:
        message += (f"\n\n({len(images)} image(s) attached: first describe what they show that matters here, "
                    "then answer using that description.)")
    params = {"task": message, "kind": "say", "model": model, "effort": args.effort or record.get("effort"),
              "images": images,
              "fallback": router.route("", kind="ask", model=model).fallback, "access": record.get("access") or "read",
              "cwd": cwd, "schema": None, "max_attempts": 1, "escalate": False,
              "resume": record["session_id"] if started else None, "allow": ["Bash(cic bus *)"],
              "profile": _profile(args), "name": f"cic:{record['name']}",
              "baseline": {"cost": record.get("cost_usd") or 0.0, "tokens": record.get("tokens") or {}} if started
              else None}
    job = jobs.create("say", cwd=cwd, title=message, params=params,
                      session_id=None if started else record["session_id"], session_name=record["name"])
    jobs.write_file(job, "system.md", prompts.contract_for("ask", chat=True, role=record.get("role")))
    jobs.write_file(job, "brief.md", message)
    return _launch(job, args, f"cic: {record['name']} turn {int(record.get('turns', 0)) + 1} · {model} · job {job['id']}")


def cmd_reply(args) -> int:
    message = _text(args.message, args.task_file, "message")
    _guards()
    parent = jobs.resolve(args.job)
    if parent.get("status") not in jobs.TERMINAL:
        raise CicError(f"job {parent['id']} is still {parent.get('status')}; use `cic steer {parent['id']} \"...\"` "
                       "to talk to it while it runs", code=2)
    if parent.get("kind") in ("pair", "council"):
        raise CicError("reply works on Claude jobs; for pair/council start a new run", code=2)
    params = dict(parent["params"])
    session = (parent.get("progress") or {}).get("session_id") or parent.get("session_id")
    model = router.normalize_model(args.model) or parent.get("model_final") or params.get("model")
    params.update(resume=session, model=model, plan=False, fork=args.fork, images=[],
                  # Resumed sessions report running totals; this job's usage is the delta from here.
                  baseline=None if args.fork else {
                      "cost": parent.get("session_cost_usd") or (parent.get("progress") or {}).get("cost_usd") or 0.0,
                      "tokens": parent.get("session_tokens") or (parent.get("progress") or {}).get("tokens") or {}})
    if args.verify:
        params["verify"] = args.verify
    if args.access:
        params["access"] = args.access
    if params.get("schema") == "task":
        brief = prompts.follow_up_message(message)
    elif params.get("schema") == "review":
        brief = message + "\n\nReturn an updated structured review."
    else:
        brief = message
    job = jobs.create(parent["kind"], cwd=parent["cwd"], title=message, params=params, parent=parent["id"],
                      session_id=session, session_name=parent.get("session_name"))
    source = jobs.job_dir(parent["id"]) / "system.md"
    if source.exists():
        jobs.write_file(job, "system.md", source.read_text(encoding="utf-8"))
    jobs.write_file(job, "brief.md", brief)
    return _launch(job, args, f"cic: job {job['id']} continues {parent['id']} on session {session} · {model}")


# ----------------------------------------------------------------- job control

def cmd_jobs(args) -> int:
    cwd = None if args.all else _cwd(args.cwd)
    rows = jobs.list_jobs(cwd=cwd, limit=args.limit)
    if args.json:
        _print(json.dumps([_summary(j) for j in rows], indent=2))
    else:
        _print(render_jobs(rows) if rows or args.all else "No jobs in this directory (use --all).")
    return 0


def cmd_status(args) -> int:
    if args.job:
        job = jobs.resolve(args.job)
        _print(json.dumps(_summary(job), indent=2) if args.json else render_status(job))
        return 0
    active = [j for j in jobs.list_jobs(limit=50) if j.get("status") in jobs.ACTIVE]
    recent = jobs.list_jobs(cwd=_cwd(args.cwd), limit=5)
    if args.json:
        _print(json.dumps({"active": [_summary(j) for j in active], "recent": [_summary(j) for j in recent]}, indent=2))
        return 0
    out = ["Active jobs:", render_jobs(active) if active else "none", "", "Recent here:", render_jobs(recent)]
    _print("\n".join(out))
    return 0


def cmd_wait(args) -> int:
    job = jobs.resolve(args.job)
    return _finish_or_status(job["id"], args.timeout, args.json)


def cmd_result(args) -> int:
    job = jobs.resolve(args.job)
    if args.json:
        _print(json.dumps(_summary(job), indent=2, ensure_ascii=False))
    elif job.get("status") in jobs.TERMINAL:
        _print(render_final(job, full=True) if args.full else (jobs.read_final(job["id"]) or render_final(job)))
    else:
        _print(render_status(job))
        return 3
    return EXIT.get(job.get("status"), 1)


def cmd_stats(args) -> int:
    from .render import render_stats
    from .util import iso_to_epoch

    cwd = None if args.all else _cwd(args.cwd)
    cutoff = __import__("time").time() - args.days * 86400
    rows = [j for j in jobs.list_jobs(cwd=cwd, limit=5000)
            if (iso_to_epoch(j.get("created_at")) or 0) >= cutoff and j.get("status") in jobs.TERMINAL]
    scope = f"the last {args.days:g} days" + (" (all directories)" if args.all else f" ({cwd})")
    _print(render_stats(rows, scope))
    return 0


def cmd_logs(args) -> int:
    job = jobs.resolve(args.job)
    name = "events.jsonl" if args.raw else "log.txt"
    path = jobs.job_dir(job["id"]) / name
    if not path.exists():
        _print("(no log yet)")
        return 0
    lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
    _print("\n".join(lines[-args.tail:]))
    return 0


def _require_active(ref: str) -> dict:
    job = jobs.resolve(ref)
    if job.get("status") not in jobs.ACTIVE:
        raise CicError(f"job {job['id']} is {job.get('status')}; use `cic reply {job['id']} \"...\"` to continue it", code=2)
    return job


def cmd_steer(args) -> int:
    job = _require_active(args.job)
    if job.get("kind") in ("pair", "council"):
        raise CicError("steering applies to Claude jobs; steer the current sub-job instead (see cic jobs --all)", code=2)
    message = _text(args.message, None, "message")
    jobs.send_control(job["id"], {"type": "steer", "text": message})
    _print(f"steering queued for {job['id']}: Claude sees it at its next step. Check `cic status {job['id']}`.")
    return 0


def cmd_model(args) -> int:
    job = _require_active(args.job)
    target = router.normalize_model(args.model) or args.model
    jobs.send_control(job["id"], {"type": "model", "model": target})
    _print(f"model switch to {target} queued for {job['id']} (rebuilds the prompt cache once).")
    return 0


def cmd_cancel(args) -> int:
    job = jobs.resolve(args.job)
    result = jobs.cancel(job["id"])
    _print(f"{result['id']}: {result.get('status')}" + (f" ({result.get('reason')})" if result.get("reason") else ""))
    return 0


# ----------------------------------------------------------------- routing / doctor

def cmd_route(args) -> int:
    task = _text(args.task, args.task_file, "task text")
    r = _route_args(args, task)
    if args.json:
        _print(json.dumps(r.to_dict(), indent=2))
        return 0
    lines = [f"kind {r.kind} -> {r.label()} · access {r.access} · fallback {','.join(r.fallback) or '-'} · score {r.score}",
             "why: " + "; ".join(r.reasons)]
    lines += [f"note: {w}" for w in r.warnings]
    _print("\n".join(lines))
    return 0


def cmd_doctor(args) -> int:
    from . import doctor

    result = doctor.run_doctor(probe=args.probe)
    _print(json.dumps(result, indent=2) if args.json else doctor.render(result))
    return 0 if result["ok"] else 1


# ----------------------------------------------------------------- bus / serve

def cmd_bus(args) -> int:
    from . import bus

    if args.action == "send":
        body = _text(args.body, args.body_file, "message body")
        message = bus.send(args.sender, args.to, body, thread=args.thread, kind=args.kind, reply_to=args.reply_to)
        _print(json.dumps({"id": message["id"], "thread": message["thread"], "to": message["to"]}) if args.json
               else f"sent {message['id']} on thread {message['thread']} to {', '.join(message['to'])}")
        return 0
    if args.action == "recv":
        messages = bus.recv(args.agent, thread=args.thread, sender=args.sender, wait=args.wait, limit=args.limit,
                            peek=args.peek)
        if args.json:
            _print(json.dumps(messages, indent=2, ensure_ascii=False))
        else:
            _print("\n".join(bus.format_message(m) for m in messages) if messages else "(no messages)")
        return 0 if messages else 3
    if args.action == "ask":
        body = _text(args.body, args.body_file, "message body")
        sent, reply = bus.ask(args.sender, args.to, body, thread=args.thread, wait=args.wait)
        if args.json:
            _print(json.dumps({"sent": sent, "reply": reply}, indent=2, ensure_ascii=False))
        else:
            _print(bus.format_message(reply) if reply else f"(no reply within {int(args.wait)}s; thread {sent['thread']}, "
                   f"message {sent['id']}; later: cic bus recv --as {args.sender} --thread {sent['thread']})")
        return 0 if reply else 3
    if args.action == "log":
        messages = bus.transcript(args.thread)
        if args.json:
            _print(json.dumps(messages, indent=2, ensure_ascii=False))
        else:
            _print("\n".join(bus.format_message(m, full=not args.brief) for m in messages) or "(empty thread)")
        return 0
    if args.action == "threads":
        rows = bus.threads()
        _print(json.dumps(rows, indent=2) if args.json else "\n".join(
            f"{r['thread']}: {r['messages']} msgs · last {r['last']} · {', '.join(r['participants'])}" for r in rows)
            or "(no threads)")
        return 0
    if args.action == "agents":
        from . import serve

        live = {s["name"]: s for s in serve.status_all()}
        rows = bus.agents()
        lines = []
        for row in rows:
            state = live.get(row["agent"])
            served = f" · served by {state['agent']} ({'running' if state['alive'] else 'stopped'})" if state else ""
            lines.append(f"{row['agent']}: {row['unread']} unread{served}")
        _print("\n".join(lines) or "(no agents yet)")
        return 0
    raise CicError("unknown bus action", code=2)


def cmd_serve(args) -> int:
    from . import serve

    if args.action == "list":
        rows = serve.status_all()
        _print("\n".join(f"{r['name']}: {r['agent']} · {'running' if r['alive'] else 'stopped'} · "
                         f"handled {r.get('handled', 0)} · threads {len(r.get('threads') or {})}" for r in rows)
               or "(no bus agents)")
        return 0
    if args.action == "stop":
        state = serve.stop(args.name)
        _print(f"{args.name}: {state.get('status')}")
        return 0
    if args.action == "start":
        _guards()
        cwd = _cwd(args.cwd)
        if args.foreground:
            return serve.serve_forever(args.name, args.agent, cwd=cwd, access=args.access, role=args.role,
                                       poll=args.poll, idle_exit=args.idle_exit)
        pid = serve.start_detached(args.name, args.agent, cwd=cwd, access=args.access, role=args.role,
                                   poll=args.poll, idle_exit=args.idle_exit)
        _print(f"bus agent {args.name} ({args.agent}) running as pid {pid}.\n"
               f'talk: cic bus ask --from codex --to {args.name} "<message>" --wait 600 · stop: cic serve stop {args.name}')
        return 0
    raise CicError("unknown serve action", code=2)


# ----------------------------------------------------------------- pair / council

def cmd_pair(args) -> int:
    task = _text(args.task, args.task_file, "task text")
    cwd = _cwd(args.cwd)
    _guards()
    kind = args.kind or router.infer_kind(task)[0]
    if kind not in router.WRITE_KINDS:
        kind = "implement"
    params = {"task": task, "cwd": cwd, "kind": kind, "driver": args.driver or config.get("pair_driver"),
              "navigator": args.navigator or config.get("pair_navigator"),
              "rounds": args.rounds or int(config.get("pair_rounds")), "verify": args.verify or [],
              "criteria": args.done or [], "files": args.file or [], "context": args.context or [],
              "constraints": args.constraint or [], "access": args.access or "auto"}
    job = jobs.create("pair", cwd=cwd, title=task, params=params, prefix="cp")
    return _launch(job, args, f"cic: pair job {job['id']} · driver {params['driver']} · navigator "
                              f"{params['navigator']} · up to {params['rounds']} rounds")


def cmd_council(args) -> int:
    question = _text(args.question, args.task_file, "question")
    cwd = _cwd(args.cwd)
    _guards()
    members = [m.strip() for m in (args.members.split(",") if args.members else config.get("council_members")) if m.strip()]
    params = {"question": question, "cwd": cwd, "members": members, "synth": args.synth or config.get("council_synth"),
              "context": args.context or [], "files": args.file or [], "parallel": args.parallel}
    job = jobs.create("council", cwd=cwd, title=question, params=params, prefix="cc")
    return _launch(job, args, f"cic: council job {job['id']} · members {', '.join(members)} · synth {params['synth']}")


# ----------------------------------------------------------------- parser

def _add_wait(p) -> None:
    p.add_argument("--background", action="store_true", help="return immediately with the job id")
    p.add_argument("--wait", type=float, default=None, metavar="SECONDS",
                   help="max seconds to block before returning a progress snapshot (default from config, 540)")
    p.add_argument("--json", action="store_true", help="machine-readable output")


def _add_route(p, *, kinds: bool = True) -> None:
    if kinds:
        p.add_argument("--kind", choices=router.KINDS, help="task kind (default: inferred)")
    p.add_argument("--model", help="haiku | sonnet | opus | fable | full model id (default: routed)")
    p.add_argument("--tier", choices=sorted(router.TIER_ALIASES), help="fast=haiku, balanced=sonnet, deep=opus")
    p.add_argument("--effort", choices=["low", "medium", "high", "xhigh", "max"])


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="cic", description="Control Claude Code from Codex and other agents.")
    parser.add_argument("--version", action="version", version=f"cic {__version__}")
    sub = parser.add_subparsers(dest="command", required=True)

    p = sub.add_parser("run", help="delegate a task to Claude (routed, verified, retried)")
    p.add_argument("task", nargs="?", help="task text, or - to read stdin")
    p.add_argument("--task-file")
    _add_route(p)
    p.add_argument("--access", choices=router.ACCESS_LEVELS, help="read | edit | auto | full (default by kind)")
    p.add_argument("--read-only", action="store_true")
    p.add_argument("--cwd")
    p.add_argument("--file", action="append", help="file Claude should start from (repeatable)")
    p.add_argument("--context", action="append", help="background text (repeatable)")
    p.add_argument("--context-file", action="append", help="inline a small file as background (repeatable)")
    p.add_argument("--done", action="append", help="acceptance criterion (repeatable)")
    p.add_argument("--verify", action="append", help="check that must pass; cic re-runs it (repeatable)")
    p.add_argument("--constraint", action="append", help="constraint (repeatable)")
    p.add_argument("--hint", action="append", help="likely lead, labeled as unverified (directional stimulus)")
    p.add_argument("--example", action="append",
                   help="format/style example: literal text or @path (few-shot; repeatable)")
    p.add_argument("--image", action="append", help="attach a screenshot or diagram (png/jpg/gif/webp, <=5 MB)")
    p.add_argument("--allow", action="append", help="extra Claude allow rule, e.g. 'Bash(npm install *)'")
    p.add_argument("--deny", action="append", help="extra Claude deny rule")
    p.add_argument("--allow-git-write", action="store_true", help="let Claude commit/push (denied by default)")
    p.add_argument("--max-attempts", type=int)
    p.add_argument("--escalate", dest="escalate", action="store_true", default=None)
    p.add_argument("--no-escalate", dest="escalate", action="store_false")
    p.add_argument("--allow-fable", action="store_true", help="permit escalation beyond opus to fable")
    p.add_argument("--max-turns", type=int)
    p.add_argument("--budget", type=float, metavar="USD", help="--max-budget-usd for Claude")
    p.add_argument("--timeout", type=float, metavar="SECONDS", help="hard limit for the whole job")
    p.add_argument("--worktree", help="run in an isolated git worktree with this name")
    p.add_argument("--add-dir", action="append")
    p.add_argument("--lean", action="store_true", help="same as --profile lean")
    p.add_argument("--profile", choices=["standard", "lean", "minimal", "full"],
                   help="context Claude loads: standard (cache-friendly, no MCP), lean (+ no user plugins/hooks), "
                        "minimal (safe mode), full (everything incl. MCP)")
    p.add_argument("--plan", action="store_true", help="opus plans read-only first, then a fresh run executes")
    p.add_argument("--plan-model", default="opus")
    p.add_argument("--name")
    p.add_argument("--dry-run", action="store_true", help="show route, argv, contract, and brief; run nothing")
    _add_wait(p)
    p.set_defaults(func=cmd_run)

    p = sub.add_parser("ask", help="quick read-only question for Claude")
    p.add_argument("question", nargs="?")
    p.add_argument("--task-file")
    _add_route(p)
    p.add_argument("--cwd")
    p.add_argument("--file", action="append")
    p.add_argument("--context", action="append")
    p.add_argument("--hint", action="append")
    p.add_argument("--image", action="append")
    p.add_argument("--add-dir", action="append")
    p.add_argument("--lean", action="store_true")
    p.add_argument("--profile", choices=["standard", "lean", "minimal", "full"],
                   help="context Claude loads: standard (cache-friendly, no MCP), lean (+ no user plugins/hooks), "
                        "minimal (safe mode), full (everything incl. MCP)")
    _add_wait(p)
    p.set_defaults(func=cmd_ask)

    p = sub.add_parser("improve", help="critique and rewrite a brief before delegating (automatic prompt engineer)")
    p.add_argument("task", nargs="?")
    p.add_argument("--task-file")
    p.add_argument("--kind", choices=router.KINDS)
    p.add_argument("--model", help="default sonnet")
    p.add_argument("--effort", choices=["low", "medium", "high", "xhigh", "max"])
    p.add_argument("--cwd")
    p.add_argument("--profile", choices=["standard", "lean", "minimal", "full"],
                   help="context Claude loads: standard (cache-friendly, no MCP), lean (+ no user plugins/hooks), "
                        "minimal (safe mode), full (everything incl. MCP)")
    _add_wait(p)
    p.set_defaults(func=cmd_improve)

    p = sub.add_parser("setup", help="write the Codex exec-policy rule and check the install")
    p.add_argument("--codex-home", help="default $CODEX_HOME or ~/.codex")
    p.add_argument("--no-rule", action="store_true", help="only run the checks")
    p.set_defaults(func=cmd_setup)

    p = sub.add_parser("review", help="Claude reviews local changes (read-only findings)")
    p.add_argument("focus", nargs="*", help="optional focus text")
    p.add_argument("--base", help="base ref for branch review")
    p.add_argument("--scope", choices=["auto", "working-tree", "branch"], default="auto")
    p.add_argument("--adversarial", action="store_true", help="try to break confidence in the change (opus)")
    p.add_argument("--model")
    p.add_argument("--effort", choices=["low", "medium", "high", "xhigh", "max"])
    p.add_argument("--cwd")
    p.add_argument("--lean", action="store_true")
    p.add_argument("--profile", choices=["standard", "lean", "minimal", "full"],
                   help="context Claude loads: standard (cache-friendly, no MCP), lean (+ no user plugins/hooks), "
                        "minimal (safe mode), full (everything incl. MCP)")
    p.add_argument("--dry-run", action="store_true")
    _add_wait(p)
    p.set_defaults(func=cmd_review)

    p = sub.add_parser("session", help="manage named multi-turn conversations")
    p.add_argument("action", choices=["new", "list", "show", "rm"])
    p.add_argument("name", nargs="?")
    p.add_argument("--model")
    p.add_argument("--effort", choices=["low", "medium", "high", "xhigh", "max"])
    p.add_argument("--access", choices=router.ACCESS_LEVELS)
    p.add_argument("--role", help="persona/instructions for this conversation")
    p.add_argument("--cwd")
    p.set_defaults(func=cmd_session)

    p = sub.add_parser("say", help="send the next message in a named conversation")
    p.add_argument("name")
    p.add_argument("message", nargs="?")
    p.add_argument("--task-file")
    p.add_argument("--model")
    p.add_argument("--effort", choices=["low", "medium", "high", "xhigh", "max"])
    p.add_argument("--access", choices=router.ACCESS_LEVELS, help="used when the session is auto-created")
    p.add_argument("--role")
    p.add_argument("--image", action="append", help="attach a screenshot or diagram to this turn")
    p.add_argument("--profile", choices=["standard", "lean", "minimal", "full"],
                   help="context Claude loads: standard (cache-friendly, no MCP), lean (+ no user plugins/hooks), "
                        "minimal (safe mode), full (everything incl. MCP)")
    p.add_argument("--cwd")
    _add_wait(p)
    p.set_defaults(func=cmd_say)

    p = sub.add_parser("reply", help="continue a finished job on the same Claude session")
    p.add_argument("job")
    p.add_argument("message", nargs="?")
    p.add_argument("--task-file")
    p.add_argument("--model")
    p.add_argument("--access", choices=router.ACCESS_LEVELS)
    p.add_argument("--verify", action="append")
    p.add_argument("--fork", action="store_true", help="branch into a new session instead of extending the old one")
    _add_wait(p)
    p.set_defaults(func=cmd_reply)

    p = sub.add_parser("jobs", help="list jobs")
    p.add_argument("--all", action="store_true")
    p.add_argument("--cwd")
    p.add_argument("--limit", type=int, default=15)
    p.add_argument("--json", action="store_true")
    p.set_defaults(func=cmd_jobs)

    p = sub.add_parser("status", help="progress snapshot of a job (or all active jobs)")
    p.add_argument("job", nargs="?")
    p.add_argument("--cwd")
    p.add_argument("--json", action="store_true")
    p.set_defaults(func=cmd_status)

    p = sub.add_parser("wait", help="block until a job finishes or the timeout passes")
    p.add_argument("job", nargs="?", default="last")
    p.add_argument("--timeout", type=float, default=300)
    p.add_argument("--json", action="store_true")
    p.set_defaults(func=cmd_wait)

    p = sub.add_parser("result", help="final report of a job")
    p.add_argument("job", nargs="?", default="last")
    p.add_argument("--full", action="store_true", help="untrimmed report (default output is length-capped)")
    p.add_argument("--json", action="store_true")
    p.set_defaults(func=cmd_result)

    p = sub.add_parser("stats", help="token and cost usage across jobs, with tips to spend less")
    p.add_argument("--days", type=float, default=7)
    p.add_argument("--all", action="store_true", help="all directories (default: this one)")
    p.add_argument("--cwd")
    p.set_defaults(func=cmd_stats)

    p = sub.add_parser("logs", help="step log of a job")
    p.add_argument("job", nargs="?", default="last")
    p.add_argument("--tail", type=int, default=40)
    p.add_argument("--raw", action="store_true", help="raw stream-json events")
    p.set_defaults(func=cmd_logs)

    p = sub.add_parser("steer", help="send guidance to a running job (seen at Claude's next step)")
    p.add_argument("job")
    p.add_argument("message", nargs="?")
    p.set_defaults(func=cmd_steer)

    p = sub.add_parser("model", help="switch a running job to another model")
    p.add_argument("job")
    p.add_argument("model")
    p.set_defaults(func=cmd_model)

    p = sub.add_parser("cancel", help="interrupt and stop a job")
    p.add_argument("job", nargs="?", default="last")
    p.set_defaults(func=cmd_cancel)

    p = sub.add_parser("route", help="show which model/effort/access a task would get")
    p.add_argument("task", nargs="?")
    p.add_argument("--task-file")
    _add_route(p)
    p.add_argument("--access", choices=router.ACCESS_LEVELS)
    p.add_argument("--json", action="store_true")
    p.set_defaults(func=cmd_route)

    p = sub.add_parser("doctor", help="check claude/codex/gemini, login, sandbox rule, skills")
    p.add_argument("--probe", action="store_true", help="also make a tiny Gemini call to test its login")
    p.add_argument("--json", action="store_true")
    p.set_defaults(func=cmd_doctor)

    p = sub.add_parser("bus", help="agent-to-agent message bus")
    bsub = p.add_subparsers(dest="action", required=True)
    b = bsub.add_parser("send")
    b.add_argument("--from", dest="sender", required=True)
    b.add_argument("--to", required=True, help="agent or comma list")
    b.add_argument("--thread")
    b.add_argument("--kind", default="message")
    b.add_argument("--reply-to")
    b.add_argument("--body-file")
    b.add_argument("--json", action="store_true")
    b.add_argument("body", nargs="?")
    b = bsub.add_parser("recv")
    b.add_argument("--as", dest="agent", required=True)
    b.add_argument("--thread")
    b.add_argument("--from", dest="sender")
    b.add_argument("--wait", type=float, default=0)
    b.add_argument("--limit", type=int, default=10)
    b.add_argument("--peek", action="store_true")
    b.add_argument("--json", action="store_true")
    b = bsub.add_parser("ask")
    b.add_argument("--from", dest="sender", required=True)
    b.add_argument("--to", required=True)
    b.add_argument("--thread")
    b.add_argument("--wait", type=float, default=300)
    b.add_argument("--body-file")
    b.add_argument("--json", action="store_true")
    b.add_argument("body", nargs="?")
    b = bsub.add_parser("log")
    b.add_argument("thread")
    b.add_argument("--brief", action="store_true")
    b.add_argument("--json", action="store_true")
    b = bsub.add_parser("threads")
    b.add_argument("--json", action="store_true")
    bsub.add_parser("agents")
    p.set_defaults(func=cmd_bus)

    p = sub.add_parser("serve", help="run Claude/Codex/Gemini as a long-lived bus agent")
    ssub = p.add_subparsers(dest="action", required=True)
    s = ssub.add_parser("start")
    s.add_argument("name")
    s.add_argument("--agent", default="claude:sonnet", help="claude[:model] | codex[:model] | gemini[:model]")
    s.add_argument("--cwd")
    s.add_argument("--access", choices=router.ACCESS_LEVELS, default="read")
    s.add_argument("--role")
    s.add_argument("--poll", type=float, default=30)
    s.add_argument("--idle-exit", type=float, default=0, help="stop after this many idle seconds (0 = never)")
    s.add_argument("--foreground", action="store_true")
    s = ssub.add_parser("stop")
    s.add_argument("name")
    ssub.add_parser("list")
    p.set_defaults(func=cmd_serve)

    p = sub.add_parser("pair", help="driver implements, navigator reviews, loop until approved")
    p.add_argument("task", nargs="?")
    p.add_argument("--task-file")
    p.add_argument("--kind", choices=sorted(router.WRITE_KINDS))
    p.add_argument("--driver", help="default claude:sonnet")
    p.add_argument("--navigator", help="default claude:opus (or codex, gemini)")
    p.add_argument("--rounds", type=int)
    p.add_argument("--access", choices=router.ACCESS_LEVELS)
    p.add_argument("--verify", action="append")
    p.add_argument("--done", action="append")
    p.add_argument("--file", action="append")
    p.add_argument("--context", action="append")
    p.add_argument("--constraint", action="append")
    p.add_argument("--cwd")
    _add_wait(p)
    p.set_defaults(func=cmd_pair)

    p = sub.add_parser("council", help="ask several agents in parallel, then synthesize")
    p.add_argument("question", nargs="?")
    p.add_argument("--task-file")
    p.add_argument("--members", help="comma list, default claude:sonnet,codex,gemini")
    p.add_argument("--synth", help="moderator agent spec, or 'none' (default claude:opus)")
    p.add_argument("--parallel", type=int, default=3)
    p.add_argument("--context", action="append")
    p.add_argument("--file", action="append")
    p.add_argument("--cwd")
    _add_wait(p)
    p.set_defaults(func=cmd_council)

    p = sub.add_parser("_worker", help=argparse.SUPPRESS)
    p.add_argument("job_id")
    p.set_defaults(func=lambda a: __import__("cic.worker", fromlist=["main"]).main(a.job_id))

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    if getattr(args, "action", None) in ("show", "rm", "new") and args.command == "session" and not args.name:
        parser.error("session name required")
    try:
        return int(args.func(args) or 0)
    except CicError as exc:
        sys.stderr.write(f"cic: {exc}\n")
        return exc.code
    except KeyboardInterrupt:
        return 130
    except ValueError as exc:
        sys.stderr.write(f"cic: {exc}\n")
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
