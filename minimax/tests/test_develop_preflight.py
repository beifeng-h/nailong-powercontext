"""Offline safety regressions for the MiniMax development adapter."""

import contextlib
import io
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

from minimax_sdd import develop


class DeliveredAfterPreflightTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="minimax-preflight-", dir=os.environ.get("MINIMAX_TEST_TEMP"))
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.head = "a" * 40
        self.before = b"# fixed before snapshot\n"
        self.tests = b"# fixed test snapshot\n"
        for relative, data in (
            (develop.BEFORE, self.before),
            (develop.TESTS, self.tests),
            (develop.AFTER, b"# delivered result must remain unchanged\n"),
        ):
            path = self.root / relative
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(data)

        sources = []
        required = []
        for kind, relative, data in (
            ("spec", "specs/task.md", b"# specification\n"),
            ("code", develop.BEFORE, self.before),
            ("test", develop.TESTS, self.tests),
        ):
            logical_key = f"task/{kind}"
            required.append({"logical_key": logical_key, "kind": kind, "source_path": relative})
            sources.append({"logical_key": logical_key, "kind": kind, "source_path": relative,
                            "content": data.decode("utf-8"), "content_sha256": develop.digest(data)})
        task = {"task_id": "offline-check", "request": "Check the delivered snapshot", "required_sources": required}
        context = {"task_id": task["task_id"], "request": task["request"], "project_id": "offline-project",
                   "database_query": {"sql": "SELECT logical_key FROM source_docs", "params": ["offline-project"],
                                      "rows_returned": len(sources)}, "sources": sources,
                   "previous_task_state": {"state": {"task_id": task["task_id"], "completed": [],
                                                       "pending": ["verify"], "verification": {"before": "checked"}},
                                           "citation": {"id": "local-test"}, "next_step": "verify"}}
        (self.root / "task.json").write_text(json.dumps(task), encoding="utf-8")
        (self.root / "context.json").write_text(json.dumps(context), encoding="utf-8")
        self.config = develop.RunConfig("cn", develop.ENDPOINTS["cn"], "MiniMax-M3.1-Flash", True)

    def args(self):
        return ["--root", str(self.root), "--task", "task.json", "--context", "context.json",
                "--region", "cn", "--endpoint", develop.ENDPOINTS["cn"], "--model", "MiniMax-M3.1-Flash",
                "--source-version", self.head, "--expected-before-sha256", develop.digest(self.before),
                "--expected-tests-sha256", develop.digest(self.tests), "--run-dir", "evidence/minimax/check"]

    def snapshot(self):
        return {str(path.relative_to(self.root)): path.read_bytes() if path.is_file() else None
                for path in self.root.rglob("*")}

    def reject_key_read(self):
        original_get = develop.os.environ.get

        def get(name, default=None):
            if name == develop.KEY_ENV:
                raise AssertionError("key must not be read")
            return original_get(name, default)

        return mock.patch.object(develop.os.environ, "get", side_effect=get)

    def test_check_only_accepts_delivered_after_without_key_network_or_writes(self):
        before = self.snapshot()
        output = io.StringIO()
        with (mock.patch.object(develop, "actual_git_head", return_value=self.head),
              self.reject_key_read(),
              mock.patch.object(develop, "build_opener", side_effect=AssertionError("network must not be opened")),
              mock.patch.object(develop, "write_fresh", side_effect=AssertionError("files must not be written")),
              contextlib.redirect_stdout(output)):
            self.assertEqual(develop.main(self.args() + ["--check-only"]), 0)
        self.assertEqual(json.loads(output.getvalue())["status"], "offline_preflight_only")
        self.assertEqual(self.snapshot(), before)

    def test_check_only_accepts_fresh_output_without_key_network_or_writes(self):
        (self.root / develop.AFTER).unlink()
        before = self.snapshot()
        output = io.StringIO()
        with (mock.patch.object(develop, "actual_git_head", return_value=self.head),
              self.reject_key_read(),
              mock.patch.object(develop, "build_opener", side_effect=AssertionError("network must not be opened")),
              mock.patch.object(develop, "write_fresh", side_effect=AssertionError("files must not be written")),
              contextlib.redirect_stdout(output)):
            self.assertEqual(develop.main(self.args() + ["--check-only"]), 0)
        self.assertEqual(json.loads(output.getvalue())["status"], "offline_preflight_only")
        self.assertEqual(self.snapshot(), before)

    def test_cli_actual_run_rejects_existing_after_before_key_or_network(self):
        before = self.snapshot()
        error = io.StringIO()
        with (mock.patch.object(develop, "actual_git_head", return_value=self.head),
              self.reject_key_read(),
              mock.patch.object(develop, "build_opener", side_effect=AssertionError("network must not be opened")),
              mock.patch.object(develop, "write_fresh", side_effect=AssertionError("files must not be written")),
              contextlib.redirect_stderr(error)):
            self.assertEqual(develop.main(self.args() + ["--confirm-mplan-entitlement-and-quota"]), 2)
        self.assertEqual(json.loads(error.getvalue())["error_code"], "after_must_be_fresh")
        self.assertEqual(self.snapshot(), before)

    def test_direct_actual_run_rejects_existing_after_before_key_or_network(self):
        before = self.snapshot()
        with (self.reject_key_read(),
              mock.patch.object(develop, "build_opener", side_effect=AssertionError("network must not be opened")),
              mock.patch.object(develop, "write_fresh", side_effect=AssertionError("files must not be written"))):
            with self.assertRaises(develop.DevelopError) as caught:
                develop.run_actual({"root": self.root}, self.config, "evidence/minimax/check")
        self.assertEqual(caught.exception.code, "after_must_be_fresh")
        self.assertEqual(self.snapshot(), before)


class GitEnvironmentIsolationTests(unittest.TestCase):
    def test_git_child_does_not_inherit_dedicated_key(self):
        real_run = subprocess.run
        fake_env = {develop.KEY_ENV: "fictional-test-value", "MINIMAX_TEST_KEEP": "kept"}
        if "SYSTEMROOT" in os.environ:
            fake_env["SYSTEMROOT"] = os.environ["SYSTEMROOT"]
        head = "b" * 40

        def inspect_child(args, **kwargs):
            child_env = kwargs.get("env")
            self.assertIsNotNone(child_env, "git must receive an explicit filtered environment")
            self.assertNotIn(develop.KEY_ENV, child_env)
            self.assertEqual(child_env.get("MINIMAX_TEST_KEEP"), "kept")
            result = real_run([sys.executable, "-c",
                               "import os,sys; sys.exit(0 if 'MINIMAX_MPLAN_API_KEY' not in os.environ "
                               "and os.environ.get('MINIMAX_TEST_KEEP') == 'kept' else 1)"],
                              env=child_env, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                              timeout=10, check=False)
            self.assertEqual(result.returncode, 0)
            return subprocess.CompletedProcess(args, 0, stdout=(head + "\n").encode("ascii"), stderr=b"")

        with mock.patch.dict(os.environ, fake_env, clear=True), mock.patch.object(develop.subprocess, "run", side_effect=inspect_child):
            self.assertEqual(develop.actual_git_head(Path.cwd()), head)

    def test_real_git_from_fresh_process_excludes_dummy_key(self):
        project = Path(__file__).resolve().parents[1]
        allowed = {"SYSTEMROOT", "WINDIR", "PATH", "PATHEXT", "COMSPEC", "TEMP", "TMP"}
        env = {name: os.environ[name] for name in os.environ if name.upper() in allowed}
        env[develop.KEY_ENV] = "fictional-test-value"
        env["MINIMAX_TEST_KEEP"] = "kept"
        env["PYTHONDONTWRITEBYTECODE"] = "1"
        probe = """
import os, sys
from minimax_sdd import develop
observed = []
def audit(event, args):
    if event == 'subprocess.Popen':
        child_env = args[3]
        assert child_env is not None
        assert not any(name.upper() == develop.KEY_ENV for name in child_env)
        assert child_env.get('MINIMAX_TEST_KEEP') == 'kept'
        observed.append(True)
sys.addaudithook(audit)
assert len(develop.actual_git_head(os.getcwd())) == 40
assert observed == [True]
print('git_environment_filtered')
"""
        result = subprocess.run([sys.executable, "-B", "-c", probe], cwd=project, env=env,
                                stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=20, check=False)
        self.assertEqual(result.returncode, 0, result.stderr.decode("utf-8", errors="replace"))
        self.assertEqual(result.stdout.strip(), b"git_environment_filtered")


if __name__ == "__main__":
    unittest.main()
