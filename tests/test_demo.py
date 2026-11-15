import io
import json
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path

from demo import COLUMNS, HOLDOUT_COLUMNS, holdout_table, main, render, render_holdout, table

PAGE = "# Title\n\n<!-- snippetcheck:results -->\nold row\n<!-- /snippetcheck:results -->\n\ntail\n"


def metrics() -> dict:
    values = dict.fromkeys(COLUMNS, 1)
    values.update({"calls_ok": 1, "calls_partial": 0, "calls_mismatch": 0})
    return values


def write_json(path: Path, value: dict) -> Path:
    path.write_text(json.dumps(value), encoding="utf-8")
    return path


class TableTest(unittest.TestCase):
    def test_header_then_one_row_per_column_in_order(self):
        lines = table(metrics()).splitlines()
        self.assertEqual(lines[:2], ["| metric | value |", "|---|---|"])
        self.assertEqual([line.split("|")[1].strip() for line in lines[2:]], list(COLUMNS))
        self.assertEqual(lines[2], "| pages | 1 |")

    def test_values_are_written_as_text(self):
        values = metrics()
        values["ledger_recall"] = 0.5
        self.assertIn("| ledger_recall | 0.5 |", table(values))


class HoldoutTableTest(unittest.TestCase):
    def test_block_lists_counts_and_recall_by_kind(self):
        summary = dict.fromkeys(HOLDOUT_COLUMNS, 2)
        summary["by_kind"] = {"route": {"cases": 3, "caught": 2}}
        lines = holdout_table(summary).splitlines()
        self.assertEqual(lines[2], "| pages | 2 |")
        self.assertEqual(lines[-1], "| recall, route | 2 of 3 |")

    def test_block_is_replaced_between_its_own_markers(self):
        page = "a\n<!-- snippetcheck:holdout -->\nstale\n<!-- /snippetcheck:holdout -->\nb\n"
        summary = dict.fromkeys(HOLDOUT_COLUMNS, 1)
        summary["by_kind"] = {}
        rendered = render_holdout(page, summary)
        self.assertNotIn("stale", rendered)
        self.assertTrue(rendered.endswith("<!-- /snippetcheck:holdout -->\nb\n"))


class RenderTest(unittest.TestCase):
    def test_block_is_replaced_and_markers_kept(self):
        rendered = render(PAGE, metrics())
        self.assertTrue(rendered.startswith("# Title\n\n<!-- snippetcheck:results -->\n| metric | value |\n"))
        self.assertTrue(rendered.endswith("<!-- /snippetcheck:results -->\n\ntail\n"))
        self.assertNotIn("old row", rendered)

    def test_text_outside_the_block_is_left_alone(self):
        rendered = render(PAGE, metrics())
        self.assertIn("\ntail\n", rendered)

    def test_missing_markers_are_rejected(self):
        with self.assertRaises(ValueError):
            render("no markers here", metrics())

    def test_duplicate_markers_are_rejected(self):
        with self.assertRaises(ValueError):
            render(PAGE + PAGE, metrics())

    def test_end_before_start_is_rejected(self):
        with self.assertRaises(ValueError):
            render("<!-- /snippetcheck:results -->\n<!-- snippetcheck:results -->\n", metrics())


class MainTest(unittest.TestCase):
    def test_readme_mode_writes_the_rendered_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            folder = Path(tmp)
            metrics_path = write_json(folder / "metrics.json", metrics())
            readme = folder / "README.md"
            readme.write_text(PAGE, encoding="utf-8")
            out = folder / "OUT.md"
            code = main(["--metrics", str(metrics_path), "--readme", str(readme), "--out", str(out)])
            text = out.read_text(encoding="utf-8")
        self.assertEqual(code, 0)
        self.assertIn("| pages | 1 |", text)
        self.assertIn("<!-- /snippetcheck:results -->", text)
        self.assertNotIn("old row", text)

    def test_out_defaults_to_the_readme(self):
        with tempfile.TemporaryDirectory() as tmp:
            folder = Path(tmp)
            metrics_path = write_json(folder / "metrics.json", metrics())
            readme = folder / "README.md"
            readme.write_text(PAGE, encoding="utf-8")
            self.assertEqual(main(["--metrics", str(metrics_path), "--readme", str(readme)]), 0)
            text = readme.read_text(encoding="utf-8")
        self.assertIn("| calls_mismatch | 0 |", text)

    def test_report_mode_prints_findings_and_ledger_results(self):
        details = {
            "calls": [
                {
                    "method": "GET",
                    "url": "https://api.supermemory.ai/nope",
                    "problems": [["unknown_path", "/nope"]],
                }
            ],
            "ledger": [{"id": "case-1", "caught": True}, {"id": "case-2", "caught": False}],
            "mutations": [],
        }
        with tempfile.TemporaryDirectory() as tmp:
            folder = Path(tmp)
            metrics_path = write_json(folder / "metrics.json", metrics())
            details_path = write_json(folder / "details.json", details)
            out = io.StringIO()
            with redirect_stdout(out):
                code = main(["--metrics", str(metrics_path), "--details", str(details_path)])
        self.assertEqual(code, 0)
        text = out.getvalue()
        self.assertIn("GET /nope unknown_path /nope", text)
        self.assertIn("1 findings", text)
        self.assertIn("case-1: caught", text)
        self.assertIn("case-2: not caught", text)


if __name__ == "__main__":
    unittest.main()
