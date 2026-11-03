import unittest

from sddctx.drift import DriftChecker
from sddctx.ingestion import parse_decision, parse_spec
from sddctx.models import Symbol
from sddctx.resolver import ContextResolver
from sddctx.store import SqliteStore
from tests.support import decision_doc, spec_doc


class ResolverTests(unittest.TestCase):
    def setUp(self):
        self.store = SqliteStore(":memory:")
        self.store.replace_files(["sddctx/resolver.py", "tests/test_resolver.py"])
        self.store.replace_symbols(
            [
                Symbol(
                    path="sddctx/resolver.py", qualname="ContextResolver.resolve", kind="method", line=1
                )
            ]
        )
        self.store.upsert_spec(
            parse_spec(
                spec_doc(
                    spec_id="SPEC-1",
                    title="上下文解析契约",
                    scope=["resolver"],
                    tags=["context"],
                    requirements=[("REQ-1", "只允许生效规格", [])],
                    code_refs=[("sddctx/resolver.py", "ContextResolver.resolve", "入口")],
                    test_refs=[("tests/test_resolver.py", "tests/test_resolver.py::test_x", ["REQ-1"])],
                ),
                "spec/specs/SPEC-1.md",
            )
        )
        self.store.upsert_spec(
            parse_spec(
                spec_doc(
                    spec_id="SPEC-OLD",
                    title="旧版上下文解析",
                    status="superseded",
                    scope=["resolver"],
                    tags=["context"],
                    superseded_by="SPEC-1",
                ),
                "spec/specs/SPEC-OLD.md",
            )
        )
        self.store.upsert_spec(
            parse_spec(
                spec_doc(
                    spec_id="SPEC-DRAFT",
                    title="上下文解析草案",
                    status="draft",
                    scope=["resolver"],
                    tags=["context"],
                ),
                "spec/specs/SPEC-DRAFT.md",
            )
        )
        self.store.upsert_decision(
            parse_decision(
                decision_doc(decision_id="ADR-1", scope=["resolver"], tags=["context"]),
                "spec/decisions/ADR-1.md",
            )
        )
        self.store.upsert_decision(
            parse_decision(
                decision_doc(
                    decision_id="ADR-2",
                    status="superseded",
                    scope=["resolver"],
                    tags=["context"],
                    superseded_by="ADR-1",
                ),
                "spec/decisions/ADR-2.md",
            )
        )
        self.resolver = ContextResolver(self.store, DriftChecker(self.store))

    def tearDown(self):
        self.store.close()

    def test_resolve_excludes_superseded_spec(self):
        bundle = self.resolver.resolve("上下文解析 resolver")
        ids = [spec.id for spec in bundle.specs]
        self.assertIn("SPEC-1", ids)
        self.assertNotIn("SPEC-OLD", ids)
        self.assertNotIn("SPEC-DRAFT", ids)
        self.assertIn("SPEC-OLD", [spec.id for spec in bundle.invalidated_specs])
        self.assertIn("SPEC-DRAFT", [spec.id for spec in bundle.candidates])

    def test_resolve_returns_code_and_tests(self):
        bundle = self.resolver.resolve("上下文解析 resolver")
        self.assertTrue(bundle.code_refs)
        self.assertEqual(bundle.code_refs[0].file, "sddctx/resolver.py")
        self.assertEqual(bundle.code_refs[0].symbol, "ContextResolver.resolve")
        self.assertTrue(bundle.tests)
        self.assertEqual(bundle.tests[0].test_id, "tests/test_resolver.py::test_x")
        markdown = bundle.to_markdown()
        self.assertIn("sddctx/resolver.py", markdown)
        self.assertIn("tests/test_resolver.py::test_x", markdown)

    def test_resolve_excludes_superseded_decision(self):
        bundle = self.resolver.resolve("上下文解析 resolver")
        decision_ids = [decision.id for decision in bundle.decisions]
        invalidated = [decision.id for decision in bundle.invalidated_decisions]
        self.assertIn("ADR-1", decision_ids)
        self.assertNotIn("ADR-2", decision_ids)
        self.assertIn("ADR-2", invalidated)
        self.assertIn("已失效", bundle.to_markdown())

    def test_resolve_is_deterministic(self):
        first = self.resolver.resolve("上下文解析")
        second = self.resolver.resolve("上下文解析")
        self.assertEqual(
            [s.id for s in first.specs], [s.id for s in second.specs]
        )

    def test_resolve_without_match_returns_empty(self):
        bundle = self.resolver.resolve("完全无关的请求")
        self.assertEqual(bundle.specs, [])


if __name__ == "__main__":
    unittest.main()

