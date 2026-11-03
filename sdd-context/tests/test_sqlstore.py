import sqlite3
import unittest

from sddctx.ingestion import parse_spec
from sddctx.sqlstore import SqlStore
from sddctx.store import Review
from tests.support import spec_doc


class SqlStoreTests(unittest.TestCase):
    """用 SQLite 的 qmark 风格验证 DB-API 适配器（不需要任何外部实例）。"""

    def setUp(self):
        self.conn = sqlite3.connect(":memory:")
        self.store = SqlStore(self.conn)
        self.store.create_schema()

    def tearDown(self):
        self.store.close()

    def test_spec_roundtrip(self):
        spec = parse_spec(
            spec_doc(
                spec_id="SPEC-1",
                title="外部实例规格",
                requirements=[("REQ-1", "需求一", [])],
                code_refs=[("app.py", "f", "")],
                test_refs=[("tests/test_app.py", "tests/test_app.py::t", ["REQ-1"])],
            ),
            "spec/specs/SPEC-1.md",
        )
        self.store.upsert_spec(spec, "2026-11-03")
        loaded = self.store.get_spec("SPEC-1")
        self.assertIsNotNone(loaded)
        self.assertEqual(loaded.title, "外部实例规格")
        self.assertEqual(loaded.requirements[0].id, "REQ-1")
        self.assertEqual(loaded.test_refs[0].covers, ("REQ-1",))
        self.assertEqual(len(self.store.list_specs()), 1)

    def test_upsert_is_idempotent(self):
        spec = parse_spec(spec_doc(), "spec/specs/SPEC-1.md")
        self.store.upsert_spec(spec, "2026-11-03")
        self.store.upsert_spec(spec, "2026-11-03")
        self.assertEqual(len(self.store.list_specs()), 1)
        self.assertEqual(len(self.store.list_specs()[0].requirements), 0)

    def test_symbols_files_tests_and_review(self):
        from sddctx.models import Symbol, TestCase

        self.store.replace_files(["a.py"])
        self.store.replace_symbols([Symbol(path="a.py", qualname="f", line=3)])
        self.store.replace_tests([TestCase(path="a.py", test_id="a.py::t", covers=("REQ-1",))])
        self.store.set_review(Review(spec_id="SPEC-1", content_hash="abc", reviewed_at="2026-11-03"))
        self.assertEqual(self.store.list_files(), ["a.py"])
        self.assertEqual(self.store.list_symbols()[0].qualname, "f")
        self.assertEqual(self.store.list_tests()[0].covers, ("REQ-1",))
        self.assertEqual(self.store.get_review("SPEC-1").content_hash, "abc")
        self.assertEqual(self.store.stats()["specs"], 0)


if __name__ == "__main__":
    unittest.main()

