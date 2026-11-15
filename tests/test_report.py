import unittest

from snippetcheck.report import page_calls, scan


def page(code: str) -> dict[str, str]:
    return {"page.mdx": code}


def simple_spec() -> dict:
    body_schema = {"type": "object"}
    return {
        "v5": {
            "paths": {
                "/items": {
                    "get": {},
                    "post": {"requestBody": {"content": {"application/json": {"schema": body_schema}}}},
                }
            }
        }
    }


class PageCallsTest(unittest.TestCase):
    def test_only_calls_to_the_host_are_kept(self):
        text = (
            "```bash\n"
            "curl https://other.example/x\n"
            "curl https://api.supermemory.ai/items\n"
            "```\n"
            "```bash\n"
            "curl https://api.supermemory.ai/other\n"
            "```\n"
        )
        found = page_calls({"a.mdx": text})
        self.assertEqual(
            [call.url for _example, _index, call in found],
            ["https://api.supermemory.ai/items", "https://api.supermemory.ai/other"],
        )
        self.assertEqual([index for _example, index, _call in found], [0, 0])

    def test_index_counts_only_matching_calls_within_an_example(self):
        text = (
            "```bash\n"
            "curl https://other.example/x\n"
            "curl https://api.supermemory.ai/a\n"
            "curl https://api.supermemory.ai/b\n"
            "```\n"
        )
        found = page_calls(page(text))
        self.assertEqual([index for _example, index, _call in found], [0, 1])


class ScanTest(unittest.TestCase):
    def test_counts_and_rows(self):
        text = (
            "```bash\n"
            "curl https://api.supermemory.ai/items\n"
            "```\n"
            "```bash\n"
            "curl https://api.supermemory.ai/nope\n"
            "```\n"
            "```bash\n"
            "curl https://other.example/x\n"
            "```\n"
        )
        result = scan(page(text), simple_spec())
        self.assertEqual((result["pages"], result["examples"], result["other_host"]), (1, 3, 1))
        self.assertEqual(len(result["calls"]), 2)
        first, second = result["calls"]
        self.assertEqual(first["operation"], "v5:GET /items")
        self.assertEqual(first["verdict"], "ok")
        self.assertEqual(first["problems"], [])
        self.assertEqual(second["operation"], None)
        self.assertEqual(second["verdict"], "mismatch")
        self.assertEqual(second["problems"], [["unknown_path", "/nope"]])

    def test_row_fields_are_present(self):
        result = scan(page("```bash\ncurl https://api.supermemory.ai/items\n```\n"), simple_spec())
        row = result["calls"][0]
        self.assertEqual(
            set(row),
            {
                "page",
                "line",
                "index",
                "language",
                "group",
                "tool",
                "method",
                "url",
                "operation",
                "verdict",
                "problems",
            },
        )
        self.assertEqual(row["page"], "page.mdx")
        self.assertEqual(row["line"], 1)
        self.assertEqual(row["tool"], "curl")
        self.assertEqual(row["method"], "GET")

    def test_unparsed_body_is_partial_when_it_has_no_problems(self):
        text = '```javascript\nfetch("https://api.supermemory.ai/items", {method: "POST", body: "hello"})\n```\n'
        result = scan(page(text), simple_spec())
        self.assertEqual(result["calls"][0]["verdict"], "partial")

    def test_unknown_in_a_json_body_is_partial(self):
        text = (
            "```python\n"
            'requests.post("https://api.supermemory.ai/items", json={"outer": [{"x": payload}]})\n'
            "```\n"
        )
        result = scan(page(text), simple_spec())
        self.assertEqual(result["calls"][0]["verdict"], "partial")

    def test_problems_win_over_partial(self):
        text = '```javascript\nfetch("https://api.supermemory.ai/nope", {method: "POST", body: "hello"})\n```\n'
        result = scan(page(text), simple_spec())
        self.assertEqual(result["calls"][0]["verdict"], "mismatch")


if __name__ == "__main__":
    unittest.main()
