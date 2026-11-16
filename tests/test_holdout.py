import hashlib
import unittest

from snippetspec.data import STUDY, load_json
from snippetspec.holdout import HOLDOUT, break_page, evaluate, holdout, load_holdout

CASES = load_json(STUDY / "holdout_cases.json")["cases"]
PAGES, SPECS = load_holdout()


class FrozenCasesTest(unittest.TestCase):
    def test_case_list_is_unchanged_since_it_was_frozen(self):
        digest = hashlib.sha256((STUDY / "holdout_cases.json").read_bytes()).hexdigest()
        self.assertEqual(digest, (STUDY / "holdout_cases.sha256").read_text().strip())

    def test_every_case_changes_its_page_once(self):
        for case in CASES:
            text = PAGES[case["page"]]
            self.assertNotEqual(break_page(text, case), text, case["id"])
            self.assertEqual(len(break_page(text, case)) - len(text), len(case["replace"]) - len(case["find"]))

    def test_case_ids_are_unique(self):
        self.assertEqual(len({case["id"] for case in CASES}), len(CASES))

    def test_hold_out_data_matches_its_manifest(self):
        manifest = load_json(HOLDOUT / "MANIFEST.json")["files"]
        for name, row in manifest.items():
            digest = hashlib.sha256((HOLDOUT / name).read_bytes()).hexdigest()
            self.assertEqual(digest, row["sha256"], name)


class EvaluateTest(unittest.TestCase):
    def test_a_problem_already_in_the_original_is_not_caught(self):
        case = {
            "id": "x",
            "kind": "x",
            "page": "code_samples_getting_started_search.mdx",
            "find": "botman",
            "replace": "batman",
            "method": "POST",
            "operation": "meili:POST /indexes/{indexUid}/search",
            "code": "missing_field",
            "where": "$.limit",
        }
        result = evaluate(case, PAGES, SPECS)
        self.assertEqual((result["in_original"], result["in_broken"], result["caught"]), (True, True, False))

    def test_a_case_whose_expected_problem_never_appears_is_not_caught(self):
        case = dict(next(case for case in CASES if case["id"] == "route-index-singular"), where="/nothing")
        self.assertFalse(evaluate(case, PAGES, SPECS)["caught"])


class HoldoutRunTest(unittest.TestCase):
    def test_summary_adds_up_and_results_match_cases(self):
        summary = holdout()
        self.assertEqual(summary["calls"], summary["calls_ok"] + summary["calls_partial"] + summary["calls_mismatch"])
        self.assertEqual(summary["cases"], len(CASES))
        self.assertEqual(summary["caught"], sum(result["caught"] for result in summary["results"]))
        self.assertEqual(sum(kind["cases"] for kind in summary["by_kind"].values()), len(CASES))


if __name__ == "__main__":
    unittest.main()
