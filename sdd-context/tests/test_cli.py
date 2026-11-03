import tempfile
import unittest
from pathlib import Path

from sddctx.cli import main
from tests.support import spec_doc

NL = chr(10)


class CliTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        self.db = str(self.root / "ctx.db")
        (self.root / "spec" / "specs").mkdir(parents=True)
        (self.root / "app.py").write_text(
            "def list_tasks():" + NL + "    return []" + NL, encoding="utf-8"
        )

    def tearDown(self):
        self._tmp.cleanup()

    def _run(self, *args: str) -> int:
        return main(["--db", self.db, "--root", str(self.root), *args])

    def _write_spec(self, **kwargs) -> None:
        (self.root / "spec" / "specs" / "SPEC-1.md").write_text(
            spec_doc(**kwargs), encoding="utf-8"
        )

    def test_doctor_exit_code_on_error(self):
        self._write_spec(code_refs=[("app.py", "list_tasks", "")])
        self.assertEqual(self._run("ingest"), 0)
        self.assertEqual(self._run("index"), 0)
        # 规格指向的测试用例不存在 -> error -> 退出码 1
        self._write_spec(
            code_refs=[("app.py", "list_tasks", "")],
            test_refs=[("tests/test_app.py", "tests/test_app.py::test_gone", [])],
        )
        self.assertEqual(self._run("ingest"), 0)
        self.assertEqual(self._run("doctor"), 1)

    def test_doctor_exit_code_zero_when_clean(self):
        self._write_spec(code_refs=[("app.py", "list_tasks", "")])
        self._run("ingest")
        self._run("index")
        self.assertEqual(self._run("doctor"), 0)

    def test_context_command_runs(self):
        self._write_spec(title="任务列表", scope=["api"], tags=["task"])
        self._run("ingest")
        self.assertEqual(self._run("context", "--task", "任务列表"), 0)

    def test_review_records_baseline(self):
        self._write_spec()
        self._run("ingest")
        self.assertEqual(self._run("review", "SPEC-1"), 0)
        self.assertEqual(self._run("review", "SPEC-404"), 2)


if __name__ == "__main__":
    unittest.main()

