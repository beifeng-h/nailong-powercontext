import tempfile
import unittest
from pathlib import Path

from sddctx.assistant import AssistantRuntime
from sddctx.store import SqliteStore
from tests.support import spec_doc

APP_SOURCE = "def list_tasks():" + chr(10) + "    return []" + chr(10)
TEST_SOURCE = "def test_list_tasks():" + chr(10) + "    assert True" + chr(10)


def write_project(root: Path, spec_body: str) -> None:
    (root / "spec" / "specs").mkdir(parents=True, exist_ok=True)
    doc = spec_doc(
        spec_id="SPEC-1",
        title="任务列表过滤",
        scope=["api"],
        tags=["task"],
        requirements=[("REQ-1", "必须支持按状态过滤", [])],
        code_refs=[("app.py", "list_tasks", "")],
        test_refs=[("tests/test_app.py", "tests/test_app.py::test_list_tasks", ["REQ-1"])],
        body=spec_body,
    )
    (root / "spec" / "specs" / "SPEC-1.md").write_text(doc, encoding="utf-8")
    (root / "app.py").write_text(APP_SOURCE, encoding="utf-8")
    (root / "tests").mkdir(exist_ok=True)
    (root / "tests" / "test_app.py").write_text(TEST_SOURCE, encoding="utf-8")


class AssistantTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        write_project(self.root, "正文" + chr(10))
        self.store = SqliteStore(":memory:")
        self.runtime = AssistantRuntime(self.store, root=self.root)
        self.runtime.refresh()

    def tearDown(self):
        self.store.close()
        self._tmp.cleanup()

    def test_prepare_task_returns_packet(self):
        packet = self.runtime.prepare_task("给任务列表加按状态过滤")
        self.assertEqual(packet.task, "给任务列表加按状态过滤")
        self.assertTrue(packet.prompt)
        self.assertIn("SPEC-1", packet.prompt)
        self.assertTrue(packet.checklist)
        self.assertTrue(any("SPEC-1" in step for step in packet.checklist))
        self.assertTrue(any("test_list_tasks" in step for step in packet.checklist))
        self.assertTrue(packet.bundle.specs)

    def test_blocking_finding_marks_not_ready(self):
        # 把规格指向的符号改名，模拟代码演进
        (self.root / "app.py").write_text(
            "def query_tasks():" + chr(10) + "    return []" + chr(10), encoding="utf-8"
        )
        self.runtime.refresh()
        packet = self.runtime.prepare_task("给任务列表加按状态过滤")
        self.assertFalse(packet.ready)
        self.assertTrue(packet.blocking)
        self.assertEqual(packet.blocking[0].code, "SPEC_CODE_SYMBOL_MISSING")

    def test_refresh_reindexes_code(self):
        stats = self.runtime.refresh()
        self.assertEqual(stats["specs"], 1)
        self.assertEqual(stats["files"], 2)
        self.assertEqual(stats["tests"], 1)


if __name__ == "__main__":
    unittest.main()

