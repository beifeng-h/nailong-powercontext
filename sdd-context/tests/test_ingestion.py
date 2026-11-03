import tempfile
import unittest
from pathlib import Path

from sddctx.ingestion import IngestionError, load_tree, parse_decision, parse_spec

from tests.support import decision_doc, spec_doc


class IngestionTests(unittest.TestCase):
    def test_parse_spec(self):
        doc = spec_doc(
            spec_id="SPEC-1",
            title="上下文解析",
            scope=["resolver"],
            tags=["context"],
            requirements=[("REQ-1", "只允许生效规格", ["tests/test_x.py::test_a"])],
            code_refs=[("sddctx/resolver.py", "ContextResolver.resolve", "入口")],
            test_refs=[("tests/test_x.py", "tests/test_x.py::test_a", ["REQ-1"])],
        )
        spec = parse_spec(doc, "spec/specs/SPEC-1.md")
        self.assertEqual(spec.id, "SPEC-1")
        self.assertEqual(spec.title, "上下文解析")
        self.assertEqual(spec.scope, ("resolver",))
        self.assertEqual(spec.tags, ("context",))
        self.assertTrue(spec.is_effective)
        self.assertEqual(spec.requirements[0].id, "REQ-1")
        self.assertEqual(spec.requirements[0].verified_by, ("tests/test_x.py::test_a",))
        self.assertEqual(spec.code_refs[0].symbol, "ContextResolver.resolve")
        self.assertEqual(spec.test_refs[0].covers, ("REQ-1",))
        self.assertIn("正文内容", spec.body)

    def test_parse_spec_missing_id(self):
        doc = spec_doc(spec_id="", title="缺 id")
        with self.assertRaises(IngestionError) as ctx:
            parse_spec(doc, "spec/specs/bad.md")
        self.assertIn("bad.md", str(ctx.exception))
        self.assertIn("id", str(ctx.exception))

    def test_parse_spec_invalid_status(self):
        doc = spec_doc(status="unknown")
        with self.assertRaises(IngestionError):
            parse_spec(doc, "spec/specs/bad.md")

    def test_parse_spec_requirement_without_text(self):
        doc = "---\nid: SPEC-1\ntitle: T\nrequirements:\n  - id: REQ-1\n---\n正文\n"
        with self.assertRaises(IngestionError):
            parse_spec(doc, "spec/specs/bad.md")

    def test_parse_decision(self):
        decision = parse_decision(
            decision_doc(decision_id="ADR-1", status="superseded", superseded_by="ADR-2"),
            "spec/decisions/ADR-1.md",
        )
        self.assertEqual(decision.id, "ADR-1")
        self.assertEqual(decision.status.value, "superseded")
        self.assertEqual(decision.superseded_by, "ADR-2")
        self.assertFalse(decision.is_effective)

    def test_load_tree_separates_specs_and_decisions(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "specs").mkdir()
            (root / "decisions").mkdir()
            (root / "specs" / "SPEC-1.md").write_text(spec_doc(), encoding="utf-8")
            (root / "decisions" / "ADR-1.md").write_text(decision_doc(), encoding="utf-8")
            specs, decisions = load_tree(root)
            self.assertEqual([s.id for s in specs], ["SPEC-1"])
            self.assertEqual([d.id for d in decisions], ["ADR-1"])

    def test_load_tree_missing_dir(self):
        specs, decisions = load_tree("/nonexistent/path/for/tests")
        self.assertEqual(specs, [])
        self.assertEqual(decisions, [])


if __name__ == "__main__":
    unittest.main()

