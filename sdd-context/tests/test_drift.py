import unittest

from sddctx.drift import DriftChecker
from sddctx.ingestion import parse_spec
from sddctx.models import Severity, Symbol, TestCase
from sddctx.store import Review, SqliteStore
from tests.support import spec_doc


class DriftTests(unittest.TestCase):
    def setUp(self):
        self.store = SqliteStore(":memory:")
        self.checker = DriftChecker(self.store)

    def tearDown(self):
        self.store.close()

    def _codes(self, findings):
        return [finding.code for finding in findings]

    def test_detect_missing_symbol(self):
        self.store.replace_files(["app.py"])
        self.store.replace_symbols([Symbol(path="app.py", qualname="compute_sum", line=1)])
        self.store.upsert_spec(
            parse_spec(
                spec_doc(
                    code_refs=[("app.py", "compute_total", "求和入口")],
                ),
                "spec/specs/SPEC-1.md",
            )
        )
        findings = self.checker.check()
        self.assertIn("SPEC_CODE_SYMBOL_MISSING", self._codes(findings))
        finding = [f for f in findings if f.code == "SPEC_CODE_SYMBOL_MISSING"][0]
        self.assertIs(finding.severity, Severity.ERROR)
        self.assertEqual(finding.target, "SPEC-1")

    def test_detect_missing_test(self):
        self.store.replace_files(["tests/test_app.py"])
        self.store.replace_tests([TestCase(path="tests/test_app.py", test_id="tests/test_app.py::test_other")])
        self.store.upsert_spec(
            parse_spec(
                spec_doc(
                    test_refs=[("tests/test_app.py", "tests/test_app.py::test_total", ["REQ-1"])],
                ),
                "spec/specs/SPEC-1.md",
            )
        )
        findings = self.checker.check()
        self.assertIn("SPEC_TEST_MISSING", self._codes(findings))
        finding = [f for f in findings if f.code == "SPEC_TEST_MISSING"][0]
        self.assertIs(finding.severity, Severity.ERROR)

    def test_detect_changed_after_review(self):
        spec = parse_spec(spec_doc(body="第一版正文\n"), "spec/specs/SPEC-1.md")
        self.store.upsert_spec(spec, "2026-11-03")
        self.store.set_review(
            Review(spec_id="SPEC-1", content_hash=spec.content_hash, reviewed_at="2026-11-03")
        )
        self.assertNotIn("SPEC_CHANGED_AFTER_REVIEW", self._codes(self.checker.check()))

        changed = parse_spec(spec_doc(body="第二版正文\n"), "spec/specs/SPEC-1.md")
        self.store.upsert_spec(changed, "2026-11-04")
        findings = self.checker.check()
        self.assertIn("SPEC_CHANGED_AFTER_REVIEW", self._codes(findings))
        finding = [f for f in findings if f.code == "SPEC_CHANGED_AFTER_REVIEW"][0]
        self.assertIs(finding.severity, Severity.WARNING)

    def test_detect_conflicting_specs(self):
        self.store.upsert_spec(
            parse_spec(
                spec_doc(
                    spec_id="SPEC-A",
                    requirements=[("REQ-SHARED", "超时时间 3 秒", [])],
                ),
                "spec/specs/SPEC-A.md",
            )
        )
        self.store.upsert_spec(
            parse_spec(
                spec_doc(
                    spec_id="SPEC-B",
                    requirements=[("REQ-SHARED", "超时时间 10 秒", [])],
                ),
                "spec/specs/SPEC-B.md",
            )
        )
        findings = self.checker.check()
        self.assertIn("SPEC_ACTIVE_CONFLICT", self._codes(findings))
        finding = [f for f in findings if f.code == "SPEC_ACTIVE_CONFLICT"][0]
        self.assertIs(finding.severity, Severity.ERROR)

    def test_detect_superseded_decision(self):
        from sddctx.ingestion import parse_decision
        from tests.support import decision_doc

        self.store.upsert_decision(
            parse_decision(
                decision_doc(decision_id="ADR-2", status="superseded", superseded_by="ADR-1"),
                "spec/decisions/ADR-2.md",
            )
        )
        findings = self.checker.check()
        self.assertIn("DECISION_SUPERSEDED", self._codes(findings))
        self.assertIn("DECISION_SUPERSEDER_MISSING", self._codes(findings))

    def test_clean_project_has_no_errors(self):
        self.store.replace_files(["app.py"])
        self.store.replace_symbols([Symbol(path="app.py", qualname="compute_total", line=1)])
        self.store.replace_tests([TestCase(path="tests/test_app.py", test_id="tests/test_app.py::test_total")])
        self.store.upsert_spec(
            parse_spec(
                spec_doc(
                    code_refs=[("app.py", "compute_total", "")],
                    test_refs=[("tests/test_app.py", "tests/test_app.py::test_total", ["REQ-1"])],
                ),
                "spec/specs/SPEC-1.md",
            )
        )
        errors = [f for f in self.checker.check() if f.severity is Severity.ERROR]
        self.assertEqual(errors, [])


if __name__ == "__main__":
    unittest.main()

