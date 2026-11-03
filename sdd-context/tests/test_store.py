import unittest

from sddctx.models import Spec, SpecStatus
from sddctx.store import Review, SqliteStore

from sddctx.ingestion import parse_spec
from tests.support import spec_doc


class StoreTests(unittest.TestCase):
    def setUp(self):
        self.store = SqliteStore(":memory:")

    def tearDown(self):
        self.store.close()

    def _spec(self, body: str = "正文\n") -> Spec:
        doc = spec_doc(
            spec_id="SPEC-1",
            title="测试规格",
            requirements=[("REQ-1", "需求一", ["tests/test_x.py::test_a"])],
            code_refs=[("sddctx/resolver.py", "ContextResolver.resolve", "")],
            test_refs=[("tests/test_x.py", "tests/test_x.py::test_a", ["REQ-1"])],
            body=body,
        )
        return parse_spec(doc, "spec/specs/SPEC-1.md")

    def test_upsert_spec_roundtrip(self):
        spec = self._spec()
        self.store.upsert_spec(spec, "2026-11-03")
        loaded = self.store.get_spec("SPEC-1")
        self.assertIsNotNone(loaded)
        self.assertEqual(loaded.id, "SPEC-1")
        self.assertEqual(loaded.status, SpecStatus.ACTIVE)
        self.assertEqual(loaded.requirements[0].verified_by, ("tests/test_x.py::test_a",))
        self.assertEqual(loaded.code_refs[0].symbol, "ContextResolver.resolve")
        self.assertEqual(loaded.test_refs[0].covers, ("REQ-1",))

    def test_upsert_spec_is_idempotent(self):
        spec = self._spec()
        self.store.upsert_spec(spec, "2026-11-03")
        self.store.upsert_spec(spec, "2026-11-03")
        self.assertEqual(len(self.store.list_specs()), 1)
        self.assertEqual(len(self.store.list_specs()[0].requirements), 1)
        self.assertEqual(len(self.store.list_specs()[0].code_refs), 1)
        self.assertEqual(len(self.store.list_specs()[0].test_refs), 1)

    def test_content_hash_changes_with_body(self):
        first = self._spec(body="正文 A\n")
        second = self._spec(body="正文 B\n")
        self.assertNotEqual(first.content_hash, second.content_hash)
        self.assertEqual(first.content_hash, self._spec(body="正文 A\n").content_hash)

    def test_reviews(self):
        spec = self._spec()
        self.store.upsert_spec(spec, "2026-11-03")
        self.assertIsNone(self.store.get_review("SPEC-1"))
        self.store.set_review(
            Review(spec_id="SPEC-1", content_hash=spec.content_hash, reviewed_at="2026-11-03")
        )
        review = self.store.get_review("SPEC-1")
        self.assertIsNotNone(review)
        self.assertEqual(review.content_hash, spec.content_hash)

    def test_symbols_tests_and_files(self):
        from sddctx.models import Symbol, TestCase

        self.store.replace_files(["a.py", "b.py"])
        self.store.replace_symbols([Symbol(path="a.py", qualname="f", kind="function", line=1)])
        self.store.replace_tests([TestCase(path="a.py", test_id="a.py::t", covers=("REQ-1",))])
        self.assertEqual(self.store.list_files(), ["a.py", "b.py"])
        self.assertEqual(self.store.list_symbols()[0].qualname, "f")
        self.assertEqual(self.store.list_tests()[0].covers, ("REQ-1",))
        self.store.replace_files(["c.py"])
        self.assertEqual(self.store.list_files(), ["c.py"])

    def test_stats(self):
        self.store.upsert_spec(self._spec(), "2026-11-03")
        stats = self.store.stats()
        self.assertEqual(stats["specs"], 1)
        self.assertEqual(stats["files"], 0)


if __name__ == "__main__":
    unittest.main()

