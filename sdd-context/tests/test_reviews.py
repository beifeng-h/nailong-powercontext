import json
import tempfile
import unittest
from pathlib import Path

from sddctx.assistant import AssistantRuntime
from sddctx.reviews import load_reviews, save_review
from sddctx.store import Review, SqliteStore
from tests.support import spec_doc

NL = chr(10)


class ReviewsTests(unittest.TestCase):
    def test_review_baseline_persists_in_repo(self):
        with tempfile.TemporaryDirectory() as tmp:
            review = Review(
                spec_id="SPEC-1",
                content_hash="abc123",
                reviewed_at="2026-11-03",
                note="验收通过",
            )
            path = save_review(tmp, review)
            self.assertTrue(path.exists())
            self.assertEqual(path.name, "reviews.json")
            loaded = load_reviews(tmp)
            self.assertEqual(len(loaded), 1)
            self.assertEqual(loaded[0].content_hash, "abc123")
            self.assertEqual(loaded[0].note, "验收通过")
            save_review(tmp, Review(spec_id="SPEC-2", content_hash="def", reviewed_at="2026-11-03"))
            self.assertEqual(len(load_reviews(tmp)), 2)
            save_review(tmp, Review(spec_id="SPEC-1", content_hash="zzz", reviewed_at="2026-11-04"))
            by_id = {item.spec_id: item for item in load_reviews(tmp)}
            self.assertEqual(by_id["SPEC-1"].content_hash, "zzz")
            self.assertEqual(len(by_id), 2)

    def test_broken_reviews_file_is_ignored(self):
        with tempfile.TemporaryDirectory() as tmp:
            Path(tmp, "reviews.json").write_text("{不是 JSON", encoding="utf-8")
            self.assertEqual(load_reviews(tmp), [])

    def test_refresh_applies_review_baselines(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "spec" / "specs").mkdir(parents=True)
            (root / "spec" / "specs" / "SPEC-1.md").write_text(spec_doc(), encoding="utf-8")
            (root / "app.py").write_text("def f():" + NL + "    return 1" + NL, encoding="utf-8")
            payload = {
                "reviews": [
                    {
                        "spec_id": "SPEC-1",
                        "content_hash": "deadbeef",
                        "reviewed_at": "2026-11-03",
                        "note": "",
                    }
                ]
            }
            (root / "spec" / "reviews.json").write_text(
                json.dumps(payload, ensure_ascii=False), encoding="utf-8"
            )
            store = SqliteStore(":memory:")
            runtime = AssistantRuntime(store, root=root)
            runtime.refresh()
            review = store.get_review("SPEC-1")
            self.assertIsNotNone(review)
            self.assertEqual(review.content_hash, "deadbeef")
            store.close()


if __name__ == "__main__":
    unittest.main()

