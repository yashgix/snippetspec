import json
import tempfile
import unittest
from pathlib import Path

from experiment import experiment, main


class ExperimentContractTest(unittest.TestCase):
    def test_metrics_are_returned_in_sorted_key_order(self):
        metrics, details = experiment()
        self.assertEqual(list(metrics), sorted(metrics))
        self.assertIn("calls", details)
        self.assertIn("ledger", details)
        self.assertIn("mutations", details)

    def test_metrics_have_expected_high_level_keys(self):
        metrics, _details = experiment()
        for key in (
            "pages",
            "examples",
            "calls",
            "findings",
            "ledger_cases",
            "mutation_breaking_cases",
            "mutation_neutral_cases",
        ):
            self.assertIn(key, metrics)


class ExperimentMainTest(unittest.TestCase):
    def test_main_writes_sorted_json_with_trailing_newline_and_details(self):
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / "metrics.json"
            self.assertEqual(main(["--out", str(out)]), 0)
            text = out.read_text(encoding="utf-8")
            self.assertTrue(text.endswith("\n"))
            parsed = json.loads(text)
            self.assertEqual(list(parsed), sorted(parsed))
            self.assertTrue((Path(tmp) / "details.json").exists())


if __name__ == "__main__":
    unittest.main()
