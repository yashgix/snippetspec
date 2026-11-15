import tempfile
import unittest
from pathlib import Path

from snippetcheck.data import DATA, HOST, ROOT, SPECS, STUDY, load_json, load_pages, load_specs

METHODS = ("get", "post", "put", "patch", "delete")


def operation_count(spec):
    return sum(
        1 for path_item in spec.get("paths", {}).values() for method in METHODS if method in path_item
    )


class PathsTest(unittest.TestCase):
    def test_paths_point_into_the_repository(self):
        self.assertEqual(ROOT, Path(__file__).resolve().parents[1])
        self.assertEqual(DATA, ROOT / "data")
        self.assertEqual(STUDY, ROOT / "study")
        self.assertEqual(SPECS, ("v4", "v5"))
        self.assertEqual(HOST, "api.supermemory.ai")


class SpecsTest(unittest.TestCase):
    def test_specs_load_in_order_with_pinned_operation_counts(self):
        specs = load_specs()
        self.assertEqual(list(specs), ["v4", "v5"])
        self.assertEqual({name: operation_count(spec) for name, spec in specs.items()}, {"v4": 42, "v5": 33})
        self.assertIn("paths", specs["v4"])
        self.assertIn("paths", specs["v5"])

    def test_load_specs_accepts_another_data_folder(self):
        with tempfile.TemporaryDirectory() as tmp:
            folder = Path(tmp)
            (folder / "openapi").mkdir()
            (folder / "openapi" / "v5.json").write_text('{"paths": {"/x": {"get": {}}}}', encoding="utf-8")
            (folder / "openapi" / "v4.json").write_text('{"paths": {}}', encoding="utf-8")
            self.assertEqual(operation_count(load_specs(folder)["v5"]), 1)


class PagesTest(unittest.TestCase):
    def test_pinned_docs_page_count(self):
        pages = load_pages(DATA / "docs")
        self.assertEqual(len(pages), 147)
        self.assertIn("quickstart.mdx", pages)
        self.assertIn("v5/api-reference/ingest.mdx", pages)

    def test_pages_are_recursive_and_sorted_by_relative_key(self):
        with tempfile.TemporaryDirectory() as tmp:
            folder = Path(tmp)
            (folder / "a").mkdir()
            (folder / "b.mdx").write_text("b", encoding="utf-8")
            (folder / "a.mdx").write_text("a", encoding="utf-8")
            (folder / "a" / "z.mdx").write_text("z", encoding="utf-8")
            (folder / "a" / "b.mdx").write_text("nested", encoding="utf-8")
            (folder / "ignore.txt").write_text("ignored", encoding="utf-8")

            pages = load_pages(folder)

        self.assertEqual(list(pages), ["a.mdx", "a/b.mdx", "a/z.mdx", "b.mdx"])
        self.assertEqual(pages["a/b.mdx"], "nested")
        self.assertEqual(pages["b.mdx"], "b")


class JsonTest(unittest.TestCase):
    def test_load_json_reads_a_document(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "value.json"
            path.write_text('{"b": 2, "a": [1, true, null]}', encoding="utf-8")
            self.assertEqual(load_json(path), {"b": 2, "a": [1, True, None]})
            self.assertEqual(load_json(str(path))["b"], 2)


if __name__ == "__main__":
    unittest.main()
