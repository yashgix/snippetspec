"""Show what the checker found, or rewrite the README's generated results table."""

from __future__ import annotations

import argparse
from pathlib import Path

from snippetcheck.data import ROOT, load_json
from snippetcheck.metrics import findings

RESULTS = ROOT / "results"
START = "<!-- snippetcheck:results -->"
END = "<!-- /snippetcheck:results -->"
COLUMNS = (
    "pages",
    "examples",
    "examples_http",
    "calls",
    "calls_mismatch",
    "findings",
    "triage_spec_gap",
    "triage_unconfirmed",
    "triage_false_positive",
    "ledger_cases",
    "ledger_caught",
    "ledger_recall",
    "mutation_breaking_cases",
    "mutation_breaking_caught",
    "mutation_neutral_cases",
    "mutation_neutral_flagged",
    "spec_operations",
    "spec_operations_with_example",
)


def table(metrics: dict) -> str:
    """The results block body: a metric table in the documented column order."""
    lines = ["| metric | value |", "|---|---|"]
    lines.extend(f"| {name} | {metrics[name]} |" for name in COLUMNS)
    return "\n".join(lines)


def render(readme: str, metrics: dict) -> str:
    """Replace the text between the results markers, keeping both markers on their own lines."""
    if readme.count(START) != 1 or readme.count(END) != 1:
        raise ValueError("README needs exactly one snippetcheck results block")
    start = readme.index(START)
    end = readme.index(END)
    if end < start:
        raise ValueError("README results block ends before it starts")
    return f"{readme[: start + len(START)]}\n{table(metrics)}\n{readme[end:]}"


def _report(metrics: dict, details: dict) -> None:
    """Print the scan size, every finding and every ledger case's result."""
    rows = details["calls"]
    print(f"{metrics['pages']} pages, {metrics['examples']} code examples, {metrics['examples_http']} with HTTP calls")
    print(
        f"{metrics['calls']} calls: {metrics['calls_ok']} ok, "
        f"{metrics['calls_partial']} partial, {metrics['calls_mismatch']} mismatch"
    )
    found = findings(rows)
    print(f"{len(found)} findings")
    for method, path, code, where in found:
        print(f"  {method} {path} {code} {where}")
    print(f"{len(details['ledger'])} ledger cases")
    for case in details["ledger"]:
        print(f"  {case['id']}: {'caught' if case['caught'] else 'not caught'}")


def main(argv: list[str] | None = None) -> int:
    """Print the report, or write the README with its results block rendered."""
    parser = argparse.ArgumentParser(prog="demo.py", description="Show the checker's report or render the README.")
    parser.add_argument("--metrics", type=Path, default=RESULTS / "metrics.json", metavar="PATH")
    parser.add_argument("--details", type=Path, default=RESULTS / "details.json", metavar="PATH")
    parser.add_argument("--readme", type=Path, metavar="PATH", help="README whose results block is rewritten")
    parser.add_argument("--out", type=Path, metavar="PATH", help="file to write; defaults to --readme")
    args = parser.parse_args(argv)
    metrics = load_json(args.metrics)
    if args.readme is None:
        _report(metrics, load_json(args.details))
        return 0
    out = args.out or args.readme
    out.write_text(render(args.readme.read_text(encoding="utf-8"), metrics), encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
