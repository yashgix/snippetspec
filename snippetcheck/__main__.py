"""Command line: check the HTTP calls in docs code examples against the pinned specs."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from urllib.parse import urlsplit

from snippetcheck.data import DATA, load_pages, load_specs
from snippetcheck.report import scan


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="snippetcheck",
        description="Check the HTTP calls in API docs code examples against the OpenAPI specs.",
    )
    parser.add_argument("pages", nargs="*", metavar="PAGE", help=".mdx page to scan")
    parser.add_argument(
        "--docs",
        type=Path,
        default=DATA / "docs",
        metavar="DIR",
        help="folder of .mdx pages to scan when no PAGE is given",
    )
    parser.add_argument("--json", action="store_true", help="print the scan as JSON")
    return parser


def _pages(args: argparse.Namespace) -> dict[str, str]:
    """The pages to scan, keyed by the path as given or by folder-relative path."""
    if args.pages:
        return {str(page): Path(page).read_text(encoding="utf-8") for page in args.pages}
    return load_pages(args.docs)


def _path(url: str) -> str:
    """The path part of a URL, still percent-encoded."""
    try:
        return urlsplit(url).path
    except ValueError:
        return ""


def _line(row: dict) -> str:
    """One report line for a call that is not ok."""
    line = f"{row['page']}:{row['line']} #{row['index']} {row['method']} {_path(row['url'])} {row['verdict']}"
    if row["verdict"] == "mismatch" and row["problems"]:
        line += " " + "; ".join(f"{code} {where}" for code, where in row["problems"])
    return line


def _report(result: dict) -> None:
    """Print every non-ok call, then the verdict counts."""
    counts = {"ok": 0, "partial": 0, "mismatch": 0}
    for row in result["calls"]:
        counts[row["verdict"]] = counts.get(row["verdict"], 0) + 1
        if row["verdict"] != "ok":
            print(_line(row))
    print(
        f"{len(result['calls'])} calls: {counts['ok']} ok, "
        f"{counts['partial']} partial, {counts['mismatch']} mismatch"
    )


def main(argv: list[str] | None = None) -> int:
    """Scan the pages, print a text report or the scan as JSON, and return 1 on any mismatch."""
    args = _parser().parse_args(argv)
    result = scan(_pages(args), load_specs())
    if args.json:
        print(json.dumps(result, indent=1, sort_keys=True))
    else:
        _report(result)
    return 1 if any(row["verdict"] == "mismatch" for row in result["calls"]) else 0


if __name__ == "__main__":
    sys.exit(main())
