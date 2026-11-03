import unittest

from sddctx.frontmatter import FrontmatterError, parse_document, parse_yaml


class FrontmatterTests(unittest.TestCase):
    def test_simple_mapping(self):
        data = parse_yaml("id: SPEC-1\ntitle: 标题\n")
        self.assertEqual(data, {"id": "SPEC-1", "title": "标题"})

    def test_flow_sequence(self):
        data = parse_yaml("tags: [a, b, c]\n")
        self.assertEqual(data["tags"], ["a", "b", "c"])

    def test_block_sequence(self):
        data = parse_yaml("tags:\n  - a\n  - b\n")
        self.assertEqual(data["tags"], ["a", "b"])

    def test_nested_mapping(self):
        data = parse_yaml("outer:\n  inner: 1\n  other: two\n")
        self.assertEqual(data, {"outer": {"inner": 1, "other": "two"}})

    def test_sequence_of_mappings(self):
        data = parse_yaml("items:\n  - id: A\n    value: 1\n  - id: B\n    value: 2\n")
        self.assertEqual(
            data["items"],
            [{"id": "A", "value": 1}, {"id": "B", "value": 2}],
        )

    def test_sequence_of_mappings_with_nested_sequence(self):
        data = parse_yaml(
            "requirements:\n"
            "  - id: REQ-1\n"
            "    verified_by:\n"
            "      - tests/test_a.py::test_x\n"
        )
        self.assertEqual(
            data["requirements"],
            [{"id": "REQ-1", "verified_by": ["tests/test_a.py::test_x"]}],
        )

    def test_comments_are_ignored(self):
        data = parse_yaml("# 头部注释\nid: SPEC-1  # 行尾注释\n")
        self.assertEqual(data, {"id": "SPEC-1"})

    def test_quoted_values(self):
        data = parse_yaml('name: "含 # 号的值"\nother: \'单引号\'\n')
        self.assertEqual(data["name"], "含 # 号的值")
        self.assertEqual(data["other"], "单引号")

    def test_null_bool_and_numbers(self):
        data = parse_yaml("a: null\nb: ~\nc: true\nd: false\ne: 3\nf: 2.5\n")
        self.assertIsNone(data["a"])
        self.assertIsNone(data["b"])
        self.assertIs(data["c"], True)
        self.assertIs(data["d"], False)
        self.assertEqual(data["e"], 3)
        self.assertEqual(data["f"], 2.5)

    def test_value_containing_colon(self):
        data = parse_yaml("text: 入口 resolve_context\nurl: http://example.com/a\n")
        self.assertEqual(data["text"], "入口 resolve_context")
        self.assertEqual(data["url"], "http://example.com/a")

    def test_missing_colon_raises(self):
        with self.assertRaises(FrontmatterError):
            parse_yaml("这一行不是键值对\n")

    def test_bad_indent_raises(self):
        with self.assertRaises(FrontmatterError):
            parse_yaml("a: 1\n  b: 2\n")

    def test_parse_document_splits_frontmatter_and_body(self):
        text = "---\nid: SPEC-1\ntitle: T\n---\n# 正文\n内容\n"
        data, body = parse_document(text)
        self.assertEqual(data["id"], "SPEC-1")
        self.assertIn("正文", body)
        self.assertNotIn("title:", body)

    def test_parse_document_without_frontmatter(self):
        data, body = parse_document("只有正文\n")
        self.assertEqual(data, {})
        self.assertEqual(body, "只有正文\n")


if __name__ == "__main__":
    unittest.main()

