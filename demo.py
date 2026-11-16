"""Show what the checker found, or rewrite the README's generated results table."""

from __future__ import annotations

import argparse
from pathlib import Path

from snippetspec.data import ROOT, load_json
from snippetspec.metrics import findings

RESULTS = ROOT / "results"
START = "<!-- snippetspec:results -->"
END = "<!-- /snippetspec:results -->"
HOLDOUT_START = "<!-- snippetspec:holdout -->"
HOLDOUT_END = "<!-- /snippetspec:holdout -->"
HOLDOUT_COLUMNS = ("pages", "calls", "calls_mismatch", "unparsed_commands", "cases", "caught")
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


def _replace_block(text: str, start_marker: str, end_marker: str, body: str) -> str:
    """Replace the text between two markers, keeping both markers on their own lines."""
    if text.count(start_marker) != 1 or text.count(end_marker) != 1:
        raise ValueError("README needs exactly one snippetspec results block")
    start = text.index(start_marker)
    end = text.index(end_marker)
    if end < start:
        raise ValueError("README results block ends before it starts")
    return f"{text[: start + len(start_marker)]}\n{body}\n{text[end:]}"


def render(readme: str, metrics: dict) -> str:
    """Replace the text between the results markers."""
    return _replace_block(readme, START, END, table(metrics))


def holdout_table(summary: dict) -> str:
    """The hold-out block body: calls, flagged clean calls, and recall by kind of change."""
    lines = ["| hold-out metric | value |", "|---|---|"]
    for name in HOLDOUT_COLUMNS:
        lines.append(f"| {name} | {summary[name]} |")
    lines.extend(
        f"| recall, {kind} | {counts['caught']} of {counts['cases']} |" for kind, counts in summary["by_kind"].items()
    )
    return "\n".join(lines)


def render_holdout(readme: str, summary: dict) -> str:
    """Replace the text between the hold-out markers."""
    return _replace_block(readme, HOLDOUT_START, HOLDOUT_END, holdout_table(summary))


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
    parser.add_argument("--holdout", type=Path, default=RESULTS / "holdout.json", metavar="PATH")
    parser.add_argument("--readme", type=Path, metavar="PATH", help="README whose results block is rewritten")
    parser.add_argument("--out", type=Path, metavar="PATH", help="file to write; defaults to --readme")
    args = parser.parse_args(argv)
    metrics = load_json(args.metrics)
    if args.readme is None:
        _report(metrics, load_json(args.details))
        return 0
    out = args.out or args.readme
    text = render(args.readme.read_text(encoding="utf-8"), metrics)
    if HOLDOUT_START in text and args.holdout.is_file():
        text = render_holdout(text, load_json(args.holdout))
    out.write_text(text, encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
