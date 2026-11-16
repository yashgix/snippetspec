import tempfile
import unittest
from datetime import date, datetime
from pathlib import Path

from snippetspec.history import days_open, evaluate, problem_ids

PAGE = "page.mdx"


def specs():
    return {
        "v5": {
            "paths": {
                "/items": {"get": {}},
                "/items/{id}": {"get": {"parameters": [{"name": "id", "in": "path", "schema": {"type": "integer"}}]}},
            }
        }
    }


def write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def code(url: str) -> str:
    return f"```bash\ncurl {url}\n```\n"


class ProblemIdsTest(unittest.TestCase):
    def test_problems_become_tuples(self):
        rows = [
            {"method": "GET", "operation": "v5:GET /items", "problems": [["type", "body.a"], ["enum", "body.b"]]},
            {"method": "POST", "operation": None, "problems": [("unknown_path", "/nope")]},
        ]
        self.assertEqual(
            problem_ids(rows),
            {
                ("GET", "v5:GET /items", "type", "body.a"),
                ("GET", "v5:GET /items", "enum", "body.b"),
                ("POST", None, "unknown_path", "/nope"),
            },
        )

    def test_rows_without_problems_add_nothing(self):
        self.assertEqual(problem_ids([{"method": "GET", "operation": None}]), set())


class EvaluateTest(unittest.TestCase):
    def case(self, **changes):
        base = {
            "id": "case-1",
            "page": PAGE,
            "introduced": "aaa",
            "buggy": "bbb",
            "fixed": "ccc",
            "method": "GET",
            "operation": None,
            "code": "unknown_path",
            "where": "/nope",
        }
        base.update(changes)
        return base

    def history(self, folder: Path, fixed: str) -> Path:
        write(folder / "aaa" / PAGE, code("https://api.supermemory.ai/nope"))
        write(folder / "bbb" / PAGE, code("https://api.supermemory.ai/nope"))
        write(folder / "ccc" / PAGE, fixed)
        return folder

    def test_detected_and_cleared(self):
        with tempfile.TemporaryDirectory() as tmp:
            history = self.history(Path(tmp), code("https://api.supermemory.ai/items"))
            result = evaluate(self.case(), history, specs())
        self.assertEqual(
            result,
            {"id": "case-1", "introduced_detected": True, "detected": True, "cleared": True, "caught": True},
        )

    def test_still_broken_after_the_fix_is_not_cleared(self):
        with tempfile.TemporaryDirectory() as tmp:
            history = self.history(Path(tmp), code("https://api.supermemory.ai/nope"))
            result = evaluate(self.case(), history, specs())
        self.assertTrue(result["detected"])
        self.assertFalse(result["cleared"])
        self.assertFalse(result["caught"])

    def test_missing_page_is_not_flagged(self):
        with tempfile.TemporaryDirectory() as tmp:
            result = evaluate(self.case(), Path(tmp), specs())
        self.assertFalse(result["introduced_detected"])
        self.assertFalse(result["detected"])
        self.assertTrue(result["cleared"])
        self.assertFalse(result["caught"])

    def test_matched_operation_is_compared_with_the_spec_prefix(self):
        broken = code("https://api.supermemory.ai/items/abc")
        fixed = code("https://api.supermemory.ai/items/1")
        case = self.case(operation="v5:GET /items/{id}", code="type", where="path:id")
        with tempfile.TemporaryDirectory() as tmp:
            history = self.history(Path(tmp), fixed)
            write(history / "aaa" / PAGE, broken)
            write(history / "bbb" / PAGE, broken)
            result = evaluate(case, history, specs())
        self.assertTrue(result["detected"])
        self.assertTrue(result["cleared"])


class DaysOpenTest(unittest.TestCase):
    def test_days_between_commit_dates(self):
        commits = {
            "a": {"date": "2026-01-01"},
            "b": {"date": "2026-01-11"},
            "c": {"date": "2026-01-05T12:00:00Z"},
        }
        self.assertEqual(days_open({"introduced": "a", "fixed": "b"}, commits), 10)
        self.assertEqual(days_open({"introduced": "c", "fixed": "b"}, commits), 6)

    def test_date_objects_are_accepted(self):
        commits = {
            "a": {"date": date(2026, 1, 1)},
            "b": {"date": datetime(2026, 1, 3, 12, 0)},
        }
        self.assertEqual(days_open({"introduced": "a", "fixed": "b"}, commits), 2)


if __name__ == "__main__":
    unittest.main()
