import tempfile
import unittest
from pathlib import Path

from sddctx.assistant import AssistantRuntime
from sddctx.models import Severity
from sddctx.store import SqliteStore
from tests.support import spec_doc

NL = chr(10)

APP_V1 = "def compute_total(items):" + NL + "    return sum(items)" + NL
APP_V2 = "def compute_sum(items):" + NL + "    return sum(items)" + NL
TEST_V1 = "def test_total():" + NL + "    assert True" + NL
TEST_V2 = "def test_sum():" + NL + "    assert True" + NL


class EndToEndTests(unittest.TestCase):
    """用真实的代码改动验证上下文系统确实会发现脱节。"""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        (self.root / "spec" / "specs").mkdir(parents=True)
        (self.root / "tests").mkdir()
        (self.root / "app.py").write_text(APP_V1, encoding="utf-8")
        (self.root / "tests" / "test_app.py").write_text(TEST_V1, encoding="utf-8")
        self._write_spec("compute_total", "tests/test_app.py::test_total")
        self.store = SqliteStore(":memory:")
        self.runtime = AssistantRuntime(self.store, root=self.root)
        self.runtime.refresh()

    def tearDown(self):
        self.store.close()
        self._tmp.cleanup()

    def _write_spec(self, symbol: str, test_id: str) -> None:
        doc = spec_doc(
            spec_id="SPEC-1",
            title="合计计算",
            scope=["app"],
            tags=["calc"],
            requirements=[("REQ-1", "必须正确计算合计", [test_id])],
            code_refs=[("app.py", symbol, "合计入口")],
            test_refs=[("tests/test_app.py", test_id, ["REQ-1"])],
        )
        (self.root / "spec" / "specs" / "SPEC-1.md").write_text(doc, encoding="utf-8")

    def _error_codes(self):
        codes = []
        for finding in self.runtime.checker.check():
            if finding.severity is Severity.ERROR:
                codes.append(finding.code)
        return codes

    def test_code_change_is_detected(self):
        # 起点：规格与代码一致
        self.assertEqual(self._error_codes(), [])
        # 真实改动 1：把 compute_total 改名为 compute_sum，规格没跟着改
        (self.root / "app.py").write_text(APP_V2, encoding="utf-8")
        self.runtime.refresh()
        self.assertIn("SPEC_CODE_SYMBOL_MISSING", self._error_codes())
        # 真实改动 2：验证用例被删除 -> 先前的验证不再适用
        (self.root / "tests" / "test_app.py").unlink()
        self.runtime.refresh()
        codes = self._error_codes()
        self.assertIn("SPEC_TEST_MISSING", codes)
        self.assertIn("SPEC_REQ_VERIFY_MISSING", codes)
        # 把规格跟上代码：改符号名、补回测试用例 -> 上下文恢复有效
        (self.root / "tests" / "test_app.py").write_text(TEST_V2, encoding="utf-8")
        self._write_spec("compute_sum", "tests/test_app.py::test_sum")
        self.runtime.refresh()
        self.assertEqual(self._error_codes(), [])

    def test_assistant_blocks_on_stale_context(self):
        (self.root / "app.py").write_text(APP_V2, encoding="utf-8")
        self.runtime.refresh()
        packet = self.runtime.prepare_task("调整合计计算逻辑")
        self.assertFalse(packet.ready)
        self.assertEqual(packet.blocking[0].code, "SPEC_CODE_SYMBOL_MISSING")
        self.assertIn("阻塞", packet.prompt)


if __name__ == "__main__":
    unittest.main()

