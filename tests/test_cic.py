"""Tests for cic. Run: python3 -m unittest discover -s tests -v

End-to-end tests drive the real CLI and detached workers against
tests/fake_claude.py, so they cost no tokens and need no login.
"""

import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from cic import bus, claude, config, prompts, router  # noqa: E402

FAKE = ROOT / "tests" / "fake_claude.py"
CIC = ROOT / "bin" / "cic"


class Env:
    """Isolated CIC_HOME + fake claude for one test."""

    def __init__(self):
        self.home = Path(tempfile.mkdtemp(prefix="cic-home-"))
        self.work = Path(tempfile.mkdtemp(prefix="cic-work-"))
        self.argv_log = self.home / "fake-argv.jsonl"
        self.models_log = self.home / "fake-models.txt"
        self.env = {k: v for k, v in os.environ.items() if not k.startswith(("CIC_", "CODEX_SANDBOX", "FAKE_"))}
        self.env.update({
            "CIC_HOME": str(self.home),
            "CIC_CLAUDE_BIN": str(FAKE),
            "CIC_CODEX_BIN": "/nonexistent/codex",
            "CIC_GEMINI_BIN": "/nonexistent/gemini",
            "FAKE_CLAUDE_LOG": str(self.argv_log),
            "FAKE_CLAUDE_MODELS": str(self.models_log),
        })

    def cic(self, *args, scenario="done", extra=None, timeout=90):
        env = dict(self.env, FAKE_CLAUDE_SCENARIO=scenario, **(extra or {}))
        return subprocess.run([sys.executable, str(CIC), *args], cwd=self.work, env=env, capture_output=True,
                              text=True, timeout=timeout)

    def job(self, job_id):
        return json.loads((self.home / "jobs" / job_id / "job.json").read_text())

    def last_job_id(self):
        jobs_dir = self.home / "jobs"
        return sorted((p.name for p in jobs_dir.iterdir() if (p / "job.json").exists()))[-1]

    def argvs(self):
        if not self.argv_log.exists():
            return []
        return [json.loads(line) for line in self.argv_log.read_text().splitlines() if line.strip()]

    def cleanup(self):
        shutil.rmtree(self.home, ignore_errors=True)
        shutil.rmtree(self.work, ignore_errors=True)


def setUpModule():
    os.chmod(FAKE, 0o755)


# ----------------------------------------------------------------- unit tests

class RouterTests(unittest.TestCase):
    def test_simple_tasks_go_to_haiku(self):
        for task in ("Fix the typo in README", "Summarize the README", "Write a commit message for the staged changes"):
            self.assertEqual(router.route(task).tier, "haiku", task)

    def test_default_work_goes_to_sonnet(self):
        for task in ("Add unit tests for the parser module", "Implement OAuth login with refresh tokens",
                     "Why does the build fail on CI?"):
            self.assertEqual(router.route(task).tier, "sonnet", task)

    def test_hard_tasks_go_to_opus(self):
        for task in ("Design the architecture for a distributed job queue",
                     "Find the race condition causing intermittent failures in the scheduler"):
            self.assertEqual(router.route(task).tier, "opus", task)

    def test_haiku_never_gets_effort_or_auto_mode(self):
        r = router.route("Fix the typo in README")
        self.assertIsNone(r.effort)
        self.assertEqual(r.access, "edit")
        self.assertEqual(r.fallback, ["sonnet"])

    def test_questions_are_read_only(self):
        self.assertEqual(router.route("Why does the build fail on CI?").access, "read")
        self.assertEqual(router.route("What does utils.py do?").access, "read")

    def test_explicit_model_wins(self):
        r = router.route("Fix the typo", model="opus")
        self.assertEqual((r.model, r.tier, r.explicit_model), ("opus", "opus", True))
        self.assertEqual(router.route("x", model="fast").model, "haiku")

    def test_fable_never_auto_selected(self):
        r = router.route("Design a distributed consensus protocol with security review across the entire codebase")
        self.assertEqual(r.tier, "opus")
        self.assertIsNone(router.next_tier("opus"))
        self.assertEqual(router.next_tier("opus", allow_fable=True), "fable")
        self.assertEqual(router.next_tier("haiku"), "sonnet")


class ProfileTests(unittest.TestCase):
    def test_read_profile(self):
        mode, allowed, denied = claude.access_profile("read", cwd=".", allow=[], deny=[], verify=[], allow_git_write=False)
        self.assertEqual(mode, "dontAsk")
        self.assertIn("Edit", denied)
        self.assertIn("Bash(git push *)", denied)
        self.assertIn("Bash(git diff *)", allowed)

    def test_edit_profile_detects_project_and_verify(self):
        with tempfile.TemporaryDirectory() as tmp:
            Path(tmp, "package.json").write_text("{}")
            mode, allowed, denied = claude.access_profile("edit", cwd=tmp, allow=["Bash(make *)"], deny=[],
                                                          verify=["npm test -- --watch=false && npm run lint"],
                                                          allow_git_write=True)
        self.assertEqual(mode, "acceptEdits")
        self.assertIn("Bash(npm run *)", allowed)
        self.assertIn("Bash(npm test -- --watch=false)", allowed)
        self.assertIn("Bash(npm run lint *)", allowed)
        self.assertIn("Bash(make *)", allowed)
        self.assertNotIn("Bash(git push *)", denied)

    def test_argv_shape(self):
        spec = claude.ClaudeSpec(model="haiku", cwd=".", access="read", effort="high", fallback=["sonnet"],
                                 session_id="abc", schema={"type": "object"})
        argv = claude.build_argv(spec)
        self.assertNotIn("--effort", argv)  # haiku has no effort control
        self.assertIn("--session-id", argv)
        self.assertEqual(argv[argv.index("--fallback-model") + 1], "sonnet")
        self.assertEqual(argv[argv.index("--permission-prompts") + 1], "none")
        resumed = claude.build_argv(claude.ClaudeSpec(model="sonnet", cwd=".", resume="abc", session_id="zzz"))
        self.assertIn("--resume", resumed)
        self.assertNotIn("--session-id", resumed)


class ClassifyTests(unittest.TestCase):
    def test_auth_error_reported_as_success_is_caught(self):
        outcome = claude.classify({"type": "result", "subtype": "success", "is_error": True,
                                   "terminal_reason": "api_error", "result": "Not logged in · Please run /login"},
                                  expect_report=True)
        self.assertEqual(outcome.error, "auth")

    def test_max_turns_and_interrupt(self):
        self.assertEqual(claude.classify({"subtype": "error_max_turns", "is_error": True}, expect_report=False).error,
                         "max_turns")
        self.assertEqual(claude.classify({"subtype": "error_during_execution", "is_error": True,
                                          "terminal_reason": "aborted_streaming"}, expect_report=False).error,
                         "interrupted")

    def test_report_and_denials(self):
        outcome = claude.classify({"subtype": "success", "is_error": False, "terminal_reason": "completed",
                                   "structured_output": {"status": "done"},
                                   "permission_denials": [{"tool_name": "Bash", "tool_input": {"command": "x"}}]},
                                  expect_report=True)
        self.assertIsNone(outcome.error)
        self.assertEqual(outcome.report, {"status": "done"})
        self.assertEqual(outcome.denials[0]["tool"], "Bash")

    def test_missing_result_is_crash(self):
        self.assertEqual(claude.classify(None, expect_report=True).error, "crash")


class PromptTests(unittest.TestCase):
    def test_brief_has_contract_blocks(self):
        with tempfile.TemporaryDirectory() as tmp:
            brief = prompts.build_brief("Fix the login bug", kind="fix", cwd=tmp, verify=["pytest -q"],
                                        criteria=["login works"])
        for tag in ("<task>", "<context>", "<acceptance_criteria>", "<verification>", "<approach>"):
            self.assertIn(tag, brief)
        self.assertIn("Reproduce first", brief)

    def test_lint(self):
        warnings = prompts.lint_brief("fix the bug", kind="fix", criteria=None, verify=None, files=None,
                                      context=None, context_files=None)
        self.assertTrue(any("very short" in w for w in warnings))
        self.assertTrue(any("--verify" in w for w in warnings))
        self.assertTrue(any("vague" in w for w in warnings))
        secret = prompts.lint_brief("use key sk-abcdefghijklmnopqrstuvwxyz to call the api and implement it now please",
                                    kind="implement", criteria=["x"], verify=["y"], files=None, context=None,
                                    context_files=None)
        self.assertTrue(any("secret" in w for w in secret))


class VerifyTests(unittest.TestCase):
    def test_environment_errors_are_not_code_failures(self):
        from cic.verify import environment_error

        self.assertIsNotNone(environment_error("python3 -m pytest -q", 1, "/usr/bin/python3: No module named pytest"))
        self.assertIsNotNone(environment_error("cargo test", 127, "zsh: command not found: cargo"))
        # A missing *project* module is a real failure Claude should fix.
        self.assertIsNone(environment_error("python3 -m pytest -q", 1, "E   ModuleNotFoundError: No module named 'myapp.utils'"))
        self.assertIsNone(environment_error("npm test", 1, "1 failing"))


class BusTests(unittest.TestCase):
    def setUp(self):
        self.home = tempfile.mkdtemp(prefix="cic-bus-")
        os.environ["CIC_HOME"] = self.home
        config.reset_cache()

    def tearDown(self):
        shutil.rmtree(self.home, ignore_errors=True)
        os.environ.pop("CIC_HOME", None)

    def test_send_recv_claims_once(self):
        message = bus.send("codex", "claude:worker", "hello", thread="t1")
        first = bus.recv("claude:worker", thread="t1")
        second = bus.recv("claude:worker", thread="t1")
        self.assertEqual([m["id"] for m in first], [message["id"]])
        self.assertEqual(second, [])
        self.assertEqual(len(bus.transcript("t1")), 1)

    def test_reply_matching_and_peek(self):
        question = bus.send("codex", "gemini", "q?", thread="t2", kind="task")
        bus.send("gemini", "codex", "unrelated", thread="t2")
        bus.send("gemini", "codex", "answer", thread="t2", kind="reply", reply_to=question["id"])
        peeked = bus.recv("codex", thread="t2", reply_to=question["id"], peek=True)
        self.assertEqual(peeked[0]["body"], "answer")
        got = bus.recv("codex", thread="t2", reply_to=question["id"])
        self.assertEqual(got[0]["body"], "answer")
        self.assertEqual(bus.recv("codex", thread="t2")[0]["body"], "unrelated")

    def test_wait_times_out(self):
        started = time.time()
        self.assertEqual(bus.recv("nobody", wait=0.6), [])
        self.assertGreaterEqual(time.time() - started, 0.5)


# ----------------------------------------------------------------- end-to-end

class EndToEndTests(unittest.TestCase):
    def setUp(self):
        self.e = Env()

    def tearDown(self):
        self.e.cleanup()

    def test_run_done_unverified(self):
        out = self.e.cic("run", "Implement the greeting feature in app.py", "--model", "sonnet", "--wait", "60")
        self.assertEqual(out.returncode, 0, out.stdout + out.stderr)
        self.assertIn("DONE", out.stdout)
        self.assertIn("not independently verified", out.stdout)
        job = self.e.job(self.e.last_job_id())
        self.assertEqual(job["status"], "done")
        self.assertTrue((self.e.home / "jobs" / job["id"] / "final.md").exists())
        argv = self.e.argvs()[-1]
        self.assertIn("--append-system-prompt-file", argv)
        self.assertIn("--json-schema", argv)

    def test_verification_failure_triggers_repair(self):
        out = self.e.cic("run", "Write the answer file with the right content", "--kind", "implement",
                         "--model", "sonnet", "--verify", "grep -q good answer.txt", "--wait", "60",
                         scenario="verify_fix")
        self.assertEqual(out.returncode, 0, out.stdout + out.stderr)
        self.assertIn("✓ verified", out.stdout)
        job = self.e.job(self.e.last_job_id())
        self.assertEqual(job["attempt"], 2)
        self.assertTrue(job["verified"])
        followup = (self.e.home / "jobs" / job["id"] / "followup-2.md").read_text()
        self.assertIn("verification_failed", followup)

    def test_unrunnable_check_blocks_without_repairs(self):
        out = self.e.cic("run", "Implement the greeting feature in app.py", "--model", "sonnet",
                         "--verify", "python3 -m cic_no_such_runner_xyz -q", "--wait", "60")
        self.assertEqual(out.returncode, 4, out.stdout + out.stderr)
        job = self.e.job(self.e.last_job_id())
        self.assertEqual(job["status"], "blocked")
        self.assertEqual(job["attempt"], 1)
        self.assertIn("cannot run in this environment", job["reason"])
        self.assertIn("CANNOT RUN", out.stdout)

    def test_needs_input_then_reply_resumes(self):
        out = self.e.cic("run", "Add persistence for user settings", "--model", "sonnet", "--wait", "60",
                         scenario="needs_input")
        self.assertEqual(out.returncode, 4, out.stdout + out.stderr)
        self.assertIn("NEEDS INPUT", out.stdout)
        first = self.e.last_job_id()
        out = self.e.cic("reply", first, "Use SQLite.", "--wait", "60", scenario="done")
        self.assertEqual(out.returncode, 0, out.stdout + out.stderr)
        argv = self.e.argvs()[-1]
        self.assertIn("--resume", argv)
        self.assertEqual(argv[argv.index("--resume") + 1], self.e.job(first)["session_id"])

    def test_auth_failure_is_blocked_not_done(self):
        out = self.e.cic("run", "Implement the feature now please", "--model", "sonnet", "--wait", "60",
                         scenario="auth")
        self.assertEqual(out.returncode, 4)
        job = self.e.job(self.e.last_job_id())
        self.assertEqual(job["status"], "blocked")
        self.assertIn("not authenticated", job["reason"])

    def test_denials_block(self):
        out = self.e.cic("run", "Implement the feature and run the tests", "--model", "sonnet", "--wait", "60",
                         scenario="denied")
        self.assertEqual(out.returncode, 4)
        self.assertIn("permission denials", self.e.job(self.e.last_job_id())["reason"])

    def test_escalation_after_repeated_partial(self):
        out = self.e.cic("run", "Implement the importer for the new CSV format", "--wait", "90",
                         scenario="stubborn")
        self.assertEqual(out.returncode, 0, out.stdout + out.stderr)
        job = self.e.job(self.e.last_job_id())
        self.assertEqual(job["attempt"], 3)
        self.assertTrue(job.get("escalations"), job)
        self.assertEqual(self.e.models_log.read_text().split(), [job["escalations"][0]["to"]])

    def test_missing_report_is_requested(self):
        out = self.e.cic("run", "Implement the thing in the module", "--model", "sonnet", "--wait", "60",
                         scenario="noreport")
        self.assertEqual(out.returncode, 0, out.stdout + out.stderr)
        self.assertEqual(self.e.job(self.e.last_job_id())["attempt"], 2)

    def test_background_steer_and_cancel(self):
        out = self.e.cic("run", "Implement a long task", "--model", "sonnet", "--background", scenario="slow")
        self.assertEqual(out.returncode, 0, out.stderr)
        job_id = self.e.last_job_id()
        time.sleep(1.5)
        out = self.e.cic("steer", job_id, "also handle the edge case", scenario="slow")
        self.assertEqual(out.returncode, 0, out.stderr)
        out = self.e.cic("wait", job_id, "--timeout", "40", scenario="slow")
        self.assertEqual(out.returncode, 0, out.stdout + out.stderr)
        self.assertIn("STEERED", out.stdout)
        self.assertIn("edge case", out.stdout)

        out = self.e.cic("run", "Implement another long task", "--model", "sonnet", "--background", scenario="slow")
        job_id = self.e.last_job_id()
        time.sleep(1.5)
        out = self.e.cic("cancel", job_id, scenario="slow")
        self.assertIn("cancelled", out.stdout)
        self.assertEqual(self.e.job(job_id)["status"], "cancelled")

    def test_session_turns_resume_same_session(self):
        out = self.e.cic("say", "design", "Let's talk about the API shape", "--wait", "60", scenario="chat")
        self.assertEqual(out.returncode, 0, out.stdout + out.stderr)
        out = self.e.cic("say", "design", "And pagination?", "--wait", "60", scenario="chat")
        self.assertEqual(out.returncode, 0, out.stdout + out.stderr)
        first, second = self.e.argvs()[-2:]
        session_id = first[first.index("--session-id") + 1]
        self.assertEqual(second[second.index("--resume") + 1], session_id)
        record = json.loads((self.e.home / "sessions" / "design.json").read_text())
        self.assertEqual(record["turns"], 2)

    def test_review_in_git_repo(self):
        subprocess.run(["git", "init", "-q"], cwd=self.e.work, check=True)
        Path(self.e.work, "a.py").write_text("print('hi')\n")
        out = self.e.cic("review", "--wait", "60", extra={"FAKE_REVIEW_VERDICT": "needs-attention"})
        self.assertEqual(out.returncode, 0, out.stdout + out.stderr)
        self.assertIn("needs-attention", out.stdout)
        self.assertIn("[HIGH]", out.stdout)

    def test_plan_first(self):
        out = self.e.cic("run", "Implement the export feature", "--plan", "--model", "sonnet", "--wait", "60")
        self.assertEqual(out.returncode, 0, out.stdout + out.stderr)
        job = self.e.job(self.e.last_job_id())
        self.assertIn("plan", job)
        brief = (self.e.home / "jobs" / job["id"] / "brief.md").read_text()
        self.assertIn("<plan>", brief)
        plan_argv, main_argv = self.e.argvs()[-2:]
        self.assertEqual(plan_argv[plan_argv.index("--model") + 1], "opus")
        self.assertEqual(main_argv[main_argv.index("--model") + 1], "sonnet")

    def test_council_skips_unavailable_members(self):
        out = self.e.cic("council", "Which queue library should we use?", "--members",
                         "claude:haiku,codex,gemini", "--synth", "claude:sonnet", "--wait", "90", scenario="chat")
        self.assertEqual(out.returncode, 0, out.stdout + out.stderr)
        self.assertIn("Synthesis", out.stdout)
        self.assertIn("unavailable", out.stdout)

    def test_pair_approves(self):
        subprocess.run(["git", "init", "-q"], cwd=self.e.work, check=True)
        out = self.e.cic("pair", "Implement the hello command", "--driver", "claude:sonnet",
                         "--navigator", "claude:opus", "--rounds", "2", "--wait", "90", scenario="done")
        self.assertEqual(out.returncode, 0, out.stdout + out.stderr)
        self.assertIn("navigator approve", out.stdout)

    def test_depth_and_sandbox_guards(self):
        out = self.e.cic("run", "Implement x", extra={"CIC_DEPTH": "1"})
        self.assertEqual(out.returncode, 5)
        out = self.e.cic("run", "Implement x", extra={"CODEX_SANDBOX": "seatbelt"})
        self.assertEqual(out.returncode, 6)
        self.assertIn("exec-policy rule", out.stderr)

    def test_dry_run_runs_nothing(self):
        out = self.e.cic("run", "Fix the typo in README", "--dry-run")
        self.assertEqual(out.returncode, 0, out.stderr)
        self.assertIn("route: fix -> haiku", out.stdout)
        self.assertEqual(self.e.argvs(), [])


if __name__ == "__main__":
    unittest.main()
