import tempfile
import unittest
from pathlib import Path

from experiment import experiment, main

METRICS: dict = {}
DETAILS: dict = {}


def setUpModule() -> None:
    global METRICS, DETAILS
    METRICS, DETAILS = experiment()


class ExperimentTest(unittest.TestCase):
    def test_metric_names_are_sorted(self):
        self.assertEqual(list(METRICS), sorted(METRICS))
        self.assertEqual(len(METRICS), 57)

    def test_headline_counts(self):
        self.assertEqual((METRICS["calls"], METRICS["calls_ok"], METRICS["calls_mismatch"]), (148, 124, 24))
        self.assertEqual(METRICS["findings"], 11)
        self.assertEqual(
            (METRICS["triage_spec_gap"], METRICS["triage_unconfirmed"], METRICS["triage_false_positive"]),
            (10, 1, 0),
        )

    def test_ledger_every_case_is_caught(self):
        self.assertEqual((METRICS["ledger_cases"], METRICS["ledger_caught"]), (15, 15))
        self.assertEqual(METRICS["ledger_recall"], 1.0)

    def test_mutation_totals(self):
        self.assertEqual((METRICS["mutation_breaking_cases"], METRICS["mutation_breaking_caught"]), (308, 308))
        self.assertEqual((METRICS["mutation_neutral_cases"], METRICS["mutation_neutral_flagged"]), (99, 0))

    def test_details_shape(self):
        self.assertEqual(set(DETAILS), {"calls", "ledger", "mutations"})
        self.assertEqual(len(DETAILS["calls"]), 148)
        self.assertEqual(len(DETAILS["ledger"]), 15)
        self.assertEqual(len(DETAILS["mutations"]), 407)

    def test_two_runs_write_identical_metrics(self):
        with tempfile.TemporaryDirectory() as tmp:
            first = Path(tmp) / "first.json"
            second = Path(tmp) / "second.json"
            self.assertEqual(main(["--out", str(first)]), 0)
            self.assertEqual(main(["--out", str(second)]), 0)
            self.assertEqual(first.read_text(encoding="utf-8"), second.read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
