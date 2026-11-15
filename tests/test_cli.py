import io
import json
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path

from snippetcheck.__main__ import main


def write_page(folder: Path, name: str, url: str) -> Path:
    path = folder / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(f"```bash\ncurl {url}\n```\n", encoding="utf-8")
    return path


class TextOutputTest(unittest.TestCase):
    def test_ok_page_prints_only_the_summary(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = write_page(Path(tmp), "page.mdx", "https://api.supermemory.ai/namespaces")
            out = io.StringIO()
            with redirect_stdout(out):
                code = main([str(path)])
        self.assertEqual(code, 0)
        self.assertEqual(out.getvalue().strip(), "1 calls: 1 ok, 0 partial, 0 mismatch")

    def test_mismatch_page_prints_the_problem_and_returns_one(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = write_page(Path(tmp), "page.mdx", "https://api.supermemory.ai/nope")
            out = io.StringIO()
            with redirect_stdout(out):
                code = main([str(path)])
        self.assertEqual(code, 1)
        lines = out.getvalue().strip().splitlines()
        self.assertEqual(len(lines), 2)
        self.assertIn(" GET /nope mismatch unknown_path /nope", lines[0])
        self.assertEqual(lines[1], "1 calls: 0 ok, 0 partial, 1 mismatch")

    def test_docs_folder_keys_pages_by_relative_path(self):
        with tempfile.TemporaryDirectory() as tmp:
            folder = Path(tmp)
            write_page(folder, "nested/page.mdx", "https://api.supermemory.ai/nope")
            out = io.StringIO()
            with redirect_stdout(out):
                code = main(["--docs", str(folder)])
        self.assertEqual(code, 1)
        self.assertIn("nested/page.mdx:1 #0", out.getvalue())


class JsonOutputTest(unittest.TestCase):
    def test_json_is_the_full_scan(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = write_page(Path(tmp), "page.mdx", "https://api.supermemory.ai/namespaces")
            out = io.StringIO()
            with redirect_stdout(out):
                code = main([str(path), "--json"])
        self.assertEqual(code, 0)
        result = json.loads(out.getvalue())
        self.assertEqual(result["pages"], 1)
        self.assertEqual(len(result["calls"]), 1)
        self.assertEqual(result["calls"][0]["verdict"], "ok")

    def test_json_still_returns_one_for_a_mismatch(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = write_page(Path(tmp), "page.mdx", "https://api.supermemory.ai/nope")
            out = io.StringIO()
            with redirect_stdout(out):
                code = main([str(path), "--json"])
        self.assertEqual(code, 1)
        self.assertEqual(json.loads(out.getvalue())["calls"][0]["verdict"], "mismatch")


if __name__ == "__main__":
    unittest.main()
