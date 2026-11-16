import json
import tempfile
import unittest
from pathlib import Path

from experiment import experiment, main
from snippetspec.metrics import CODES
from snippetspec.mutate import BREAKING

METRICS, DETAILS = experiment()


class MetricsTest(unittest.TestCase):
    def test_names_are_sorted(self):
        self.assertEqual(list(METRICS), sorted(METRICS))

    def test_call_verdicts_add_up(self):
        total = METRICS["calls_ok"] + METRICS["calls_partial"] + METRICS["calls_mismatch"]
        self.assertEqual(total, METRICS["calls"])
        self.assertEqual(METRICS["calls"], len(DETAILS["calls"]))

    def test_tools_add_up(self):
        tools = METRICS["calls_curl"] + METRICS["calls_fetch"] + METRICS["calls_requests"]
        self.assertEqual(tools, METRICS["calls"])

    def test_every_problem_code_has_a_count(self):
        for code in CODES:
            self.assertIn(f"problems_{code}", METRICS)

    def test_every_finding_is_triaged(self):
        triaged = METRICS["triage_spec_gap"] + METRICS["triage_unconfirmed"] + METRICS["triage_false_positive"]
        self.assertEqual(triaged, METRICS["findings"])
        self.assertEqual(METRICS["triage_untriaged"], 0)

    def test_ledger_counts(self):
        self.assertEqual(METRICS["ledger_cases"], len(DETAILS["ledger"]))
        self.assertEqual(len(METRICS["ledger_days_open"]), METRICS["ledger_cases"])
        self.assertLessEqual(METRICS["ledger_caught"], METRICS["ledger_cases"])

    def test_mutation_counts(self):
        for kind in BREAKING:
            self.assertEqual(METRICS[f"mutation_{kind}_cases"], METRICS[f"mutation_{kind}_caught"], kind)
        self.assertEqual(METRICS["mutation_neutral_flagged"], 0)
        self.assertEqual(
            sum(METRICS[f"mutation_{kind}_cases"] for kind in BREAKING), METRICS["mutation_breaking_cases"]
        )
        self.assertEqual(
            len(DETAILS["mutations"]), METRICS["mutation_breaking_cases"] + METRICS["mutation_neutral_cases"]
        )


class MainTest(unittest.TestCase):
    def test_writes_metrics_and_details_beside_it(self):
        with tempfile.TemporaryDirectory() as folder:
            out = Path(folder) / "results" / "metrics.json"
            self.assertEqual(main(["--out", str(out)]), 0)
            self.assertEqual(json.loads(out.read_text()), METRICS)
            self.assertEqual(
                set(json.loads((out.parent / "details.json").read_text())), {"calls", "ledger", "mutations"}
            )


if __name__ == "__main__":
    unittest.main()
