"""Hold-out: the checker on another API's docs, plus hand-broken examples frozen before the first run."""

from __future__ import annotations

import argparse
import hashlib
import json
from collections import Counter
from pathlib import Path

from snippetspec.data import DATA, STUDY, load_json
from snippetspec.history import problem_ids
from snippetspec.report import scan

HOLDOUT = DATA / "holdout"
HOST = "ms.example"
PLACEHOLDER = "MEILISEARCH_URL"


def load_holdout(folder: Path = HOLDOUT) -> tuple[dict[str, str], dict]:
    """The sample pages (raw text, keyed by file name) and the spec under its name."""
    pages = {path.name: path.read_text(encoding="utf-8") for path in sorted((folder / "docs").glob("*.mdx"))}
    return pages, {"meili": load_json(folder / "spec" / "openapi.json")}


def _scan(pages: dict[str, str], specs: dict) -> dict:
    """Scan pages after giving the docs' URL placeholder a real host."""
    return scan({name: text.replace(PLACEHOLDER, f"https://{HOST}") for name, text in pages.items()}, specs, HOST)


def break_page(text: str, case: dict) -> str:
    """The page with the case's one change applied to its first occurrence."""
    return text.replace(case["find"], case["replace"], 1)


def _key(case: dict) -> tuple:
    return (case["method"], case["operation"], case["code"], case["where"])


def evaluate(case: dict, pages: dict[str, str], specs: dict) -> dict:
    """Whether the case's expected problem appears in the broken page and not in the original."""
    original = pages[case["page"]]
    before = _key(case) in problem_ids(_scan({case["page"]: original}, specs)["calls"])
    after = _key(case) in problem_ids(_scan({case["page"]: break_page(original, case)}, specs)["calls"])
    return {
        "id": case["id"],
        "kind": case["kind"],
        "in_original": before,
        "in_broken": after,
        "caught": after and not before,
    }


def _problem_groups(rows: list[dict]) -> dict[str, int]:
    """How many clean calls carry each kind of problem, as "code where" with example values left in."""
    groups = Counter()
    for row in rows:
        for code in {code for code, _where in row["problems"]}:
            groups[code] += 1
    return dict(sorted(groups.items()))


def _by_kind(results: list[dict]) -> dict[str, dict[str, int]]:
    kinds: dict[str, dict[str, int]] = {}
    for result in results:
        counts = kinds.setdefault(result["kind"], {"cases": 0, "caught": 0})
        counts["cases"] += 1
        counts["caught"] += result["caught"]
    return kinds


def holdout(folder: Path = HOLDOUT, cases_file: Path = STUDY / "holdout_cases.json") -> dict:
    """Clean-docs verdicts and the hand-broken cases' results."""
    pages, specs = load_holdout(folder)
    cases = load_json(cases_file)["cases"]
    clean = _scan(pages, specs)
    rows = clean["calls"]
    results = [evaluate(case, pages, specs) for case in cases]
    verdicts = Counter(row["verdict"] for row in rows)
    return {
        "frozen_sha256": hashlib.sha256(cases_file.read_bytes()).hexdigest(),
        "pages": clean["pages"],
        "calls": len(rows),
        "unparsed_commands": clean["unparsed"],
        "calls_ok": verdicts["ok"],
        "calls_partial": verdicts["partial"],
        "calls_mismatch": verdicts["mismatch"],
        "clean_problem_calls_by_code": _problem_groups(rows),
        "cases": len(results),
        "caught": sum(result["caught"] for result in results),
        "by_kind": _by_kind(results),
        "results": results,
        "clean_rows": rows,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="holdout.py", description="Run the checker on the hold-out data.")
    parser.add_argument("--out", type=Path, default=Path("results/holdout.json"), metavar="PATH")
    args = parser.parse_args(argv)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(holdout(), indent=1, sort_keys=True) + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
