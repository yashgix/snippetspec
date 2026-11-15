"""Measure snippetcheck on the pinned data: today's report, the docs-fix ledger and seeded drift."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from snippetcheck.data import DATA, STUDY, load_json, load_pages, load_specs
from snippetcheck.history import days_open, evaluate
from snippetcheck.metrics import CODES, findings, ratio
from snippetcheck.mutate import BREAKING, NEUTRAL, run
from snippetcheck.report import page_calls, scan
from snippetcheck.spec import operations

# Codes that mean no operation matched at all, so the endpoint itself is in doubt.
MISSING_OPERATION = ("unknown_path", "method_not_allowed")


def _verdicts(rows: list[dict]) -> dict[str, int]:
    """How many rows got each verdict."""
    counts = {"ok": 0, "partial": 0, "mismatch": 0}
    for row in rows:
        counts[row["verdict"]] += 1
    return counts


def _tools(rows: list[dict]) -> dict[str, int]:
    """How many rows each tool produced."""
    return {f"calls_{tool}": sum(1 for row in rows if row["tool"] == tool) for tool in ("curl", "fetch", "requests")}


def _examples(rows: list[dict]) -> tuple[int, int]:
    """The number of distinct (page, line) examples with a call, and how many of those are all ok."""
    verdicts: dict[tuple[str, int], list[str]] = {}
    for row in rows:
        verdicts.setdefault((row["page"], row["line"]), []).append(row["verdict"])
    return len(verdicts), sum(1 for found in verdicts.values() if all(verdict == "ok" for verdict in found))


def _problem_counts(rows: list[dict]) -> dict[str, int]:
    """How many problems each code accounts for, over every row."""
    counts: dict[str, int] = dict.fromkeys(CODES, 0)
    for row in rows:
        for code, _where in row["problems"]:
            counts[code] = counts.get(code, 0) + 1
    return {f"problems_{code}": counts[code] for code in CODES}


def _triage_metrics(found: list[tuple], triage: list[dict]) -> dict[str, int]:
    """How today's findings split across the hand-triage labels."""
    labels = {(item["method"], item["path"], item["code"], item["where"]): item["label"] for item in triage}
    counts = {"spec_gap": 0, "unconfirmed": 0, "false_positive": 0}
    untriaged = 0
    for finding in found:
        label = labels.get(finding)
        if label in counts:
            counts[label] += 1
        else:
            untriaged += 1
    return {
        "triage_spec_gap": counts["spec_gap"],
        "triage_unconfirmed": counts["unconfirmed"],
        "triage_false_positive": counts["false_positive"],
        "triage_untriaged": untriaged,
    }


def _ledger(ledger: dict, history: Path, specs: dict) -> tuple[list[dict], list[int]]:
    """One evaluate() result per ledger case, and the days each case stayed open."""
    cases = ledger["cases"]
    commits = ledger["commits"]
    return [evaluate(case, history, specs) for case in cases], [days_open(case, commits) for case in cases]


def _ledger_metrics(results: list[dict], days: list[int]) -> dict:
    """The ledger totals, its recall and the list of days-open values."""
    caught = sum(1 for result in results if result["caught"])
    return {
        "ledger_cases": len(results),
        "ledger_introduced_detected": sum(1 for result in results if result["introduced_detected"]),
        "ledger_detected": sum(1 for result in results if result["detected"]),
        "ledger_cleared": sum(1 for result in results if result["cleared"]),
        "ledger_caught": caught,
        "ledger_recall": ratio(caught, len(results)),
        "ledger_days_open": days,
    }


def _kind(mutation: str) -> str:
    """The kind of a mutation id, e.g. "rename_field" of "rename_field:name"."""
    return mutation.partition(":")[0]


def _mutation_metrics(rows: list[dict]) -> dict:
    """Per-kind case counts with caught (breaking) or flagged (neutral) counts, then both totals."""
    metrics: dict = {}
    for kind, expected in BREAKING.items():
        matching = [row for row in rows if _kind(row["mutation"]) == kind]
        metrics[f"mutation_{kind}_cases"] = len(matching)
        metrics[f"mutation_{kind}_caught"] = sum(1 for row in matching if set(row["codes"]) & set(expected))
    for kind in NEUTRAL:
        matching = [row for row in rows if _kind(row["mutation"]) == kind]
        metrics[f"mutation_{kind}_cases"] = len(matching)
        metrics[f"mutation_{kind}_flagged"] = sum(1 for row in matching if row["codes"])
    breaking = [row for row in rows if _kind(row["mutation"]) in BREAKING]
    neutral = [row for row in rows if _kind(row["mutation"]) in NEUTRAL]
    caught = [row for row in breaking if set(row["codes"]) & set(BREAKING[_kind(row["mutation"])])]
    metrics["mutation_breaking_cases"] = len(breaking)
    metrics["mutation_breaking_caught"] = len(caught)
    metrics["mutation_breaking_recall"] = ratio(len(caught), len(breaking))
    metrics["mutation_neutral_cases"] = len(neutral)
    metrics["mutation_neutral_flagged"] = sum(1 for row in neutral if row["codes"])
    return metrics


def experiment(data: str | Path = DATA, study: str | Path = STUDY) -> tuple[dict, dict]:
    """The metrics and the details they are counted from, for the docs and ledger under data and study."""
    data, study = Path(data), Path(study)
    pages = load_pages(data / "docs")
    specs = load_specs(data)
    scanned = scan(pages, specs)
    rows = scanned["calls"]
    found = findings(rows)
    ledger_rows, days = _ledger(load_json(study / "ledger.json"), data / "history", specs)
    mutation_rows = run(specs, page_calls(pages))
    verdicts = _verdicts(rows)
    examples_http, examples_validated = _examples(rows)
    metrics = {
        "pages": scanned["pages"],
        "examples": scanned["examples"],
        "examples_http": examples_http,
        "examples_validated": examples_validated,
        "calls": len(rows),
        "calls_other_host": scanned["other_host"],
        "calls_ok": verdicts["ok"],
        "calls_partial": verdicts["partial"],
        "calls_mismatch": verdicts["mismatch"],
        "spec_operations": len(operations(list(specs.items()))),
        "spec_operations_with_example": len({row["operation"] for row in rows if row["operation"]}),
        "mismatch_endpoints": len(
            {(method, path) for method, path, code, _where in found if code in MISSING_OPERATION}
        ),
        "findings": len(found),
        **_tools(rows),
        **_problem_counts(rows),
        **_triage_metrics(found, load_json(study / "triage.json")),
        **_ledger_metrics(ledger_rows, days),
        **_mutation_metrics(mutation_rows),
    }
    return dict(sorted(metrics.items())), {"calls": rows, "ledger": ledger_rows, "mutations": mutation_rows}


def _write(path: Path, value: dict) -> None:
    """Write JSON with sorted keys, one-space indent and a trailing newline, creating the folder."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=1, sort_keys=True) + "\n", encoding="utf-8")


def main(argv: list[str] | None = None) -> int:
    """Measure, then write the metrics to --out and their details beside it."""
    parser = argparse.ArgumentParser(prog="experiment.py", description="Measure snippetcheck on the pinned data.")
    parser.add_argument("--out", type=Path, default=Path("results/metrics.json"), metavar="PATH")
    args = parser.parse_args(argv)
    metrics, details = experiment()
    _write(args.out, metrics)
    _write(args.out.parent / "details.json", details)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
