import tempfile
import unittest
from pathlib import Path

from sddctx.indexer import index_root, is_test_file

APP_SOURCE = "\n".join(
    [
        "def helper(value):",
        "    return value + 1",
        "",
        "",
        "class Service:",
        "    def run(self):",
        "        return helper(1)",
        "",
        "    def stop(self):",
        "        return None",
        "",
    ]
)

TEST_SOURCE = "\n".join(
    [
        "from app import Service",
        "",
        "",
        "def test_helper():",
        "    assert True  # @covers REQ-1",
        "",
        "",
        "class TestService:",
        "    def test_run(self):",
        "        assert True",
        "",
    ]
)


class IndexerTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        (self.root / "app.py").write_text(APP_SOURCE, encoding="utf-8")
        (self.root / "tests").mkdir()
        (self.root / "tests" / "test_app.py").write_text(TEST_SOURCE, encoding="utf-8")
        self.index = index_root(self.root)

    def tearDown(self):
        self._tmp.cleanup()

    def test_index_collects_files_and_symbols(self):
        self.assertIn("app.py", self.index.files)
        self.assertTrue(self.index.has_symbol("app.py", "helper"))
        self.assertTrue(self.index.has_symbol("app.py", "Service"))
        self.assertTrue(self.index.has_symbol("app.py", "Service.run"))
        self.assertFalse(self.index.has_symbol("app.py", "missing"))

    def test_index_collects_tests(self):
        self.assertTrue(self.index.has_test("tests/test_app.py::test_helper"))
        self.assertTrue(self.index.has_test("tests/test_app.py::TestService::test_run"))
        self.assertFalse(self.index.has_test("tests/test_app.py::test_nope"))

    def test_covers_marker_is_parsed(self):
        self.assertEqual(self.index.test_covers("tests/test_app.py::test_helper"), ("REQ-1",))
        self.assertEqual(self.index.test_covers("tests/test_app.py::TestService::test_run"), ())

    def test_is_test_file(self):
        self.assertTrue(is_test_file("tests/test_app.py"))
        self.assertFalse(is_test_file("app.py"))

    def test_index_empty_root(self):
        with tempfile.TemporaryDirectory() as empty:
            index = index_root(empty)
            self.assertEqual(index.files, ())


if __name__ == "__main__":
    unittest.main()

