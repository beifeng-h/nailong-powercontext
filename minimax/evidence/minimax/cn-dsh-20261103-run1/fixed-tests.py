"""One fixed test file for both the baseline and actual MiniMax output.

The implementation directory is selected by run_tests.py. The test file and
fixture are identical across before/after runs; no provider or database is faked.
"""

import copy
import json
from pathlib import Path
import unittest

from taskboard import list_tasks


FIXTURE = Path(__file__).resolve().parents[1] / "fixtures" / "tasks.json"


class FixtureCase(unittest.TestCase):
    def setUp(self):
        self.tasks = json.loads(FIXTURE.read_text(encoding="utf-8"))
        self.original = copy.deepcopy(self.tasks)

    def tearDown(self):
        self.assertEqual(self.tasks, self.original, "input task values were changed")

    def assert_records(self, state, indexes):
        expected = [self.original[index] for index in indexes]
        self.assertEqual(list_tasks(self.tasks, state), expected)


class TargetBehaviorTests(FixtureCase):
    def test_trim_state_filter(self):
        self.assert_records(" OPEN ", [0, 2])

    def test_casefold_state_filter(self):
        self.assert_records("DoNe", [1])

    def test_unicode_casefold_state_filter(self):
        self.assert_records("Straße", [3])


class RegressionBehaviorTests(FixtureCase):
    def test_none_returns_all_in_source_order(self):
        self.assert_records(None, [0, 1, 2, 3])

    def test_canonical_exact_queries(self):
        for state, indexes in [("open", [0, 2]), ("done", [1]), ("strasse", [3])]:
            with self.subTest(state=state):
                self.assert_records(state, indexes)

    def test_unmatched_empty_and_whitespace_queries(self):
        for state in ["queued", "", "   "]:
            with self.subTest(state=state):
                self.assert_records(state, [])

    def test_matched_records_keep_source_order(self):
        self.assert_records("open", [0, 2])

    def test_returned_records_preserve_all_fields(self):
        self.assert_records("done", [1])
        self.assertEqual(self.tasks[1], self.original[1])

    def test_empty_input(self):
        for state in [None, "open", " OPEN "]:
            with self.subTest(state=state):
                tasks = []
                self.assertEqual(list_tasks(tasks, state), [])
                self.assertEqual(tasks, [])


if __name__ == "__main__":
    unittest.main(verbosity=2)
