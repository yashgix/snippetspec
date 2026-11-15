"""Replay the docs-fix ledger against the checker."""

from __future__ import annotations

from datetime import date, datetime
from pathlib import Path

from snippetcheck.report import scan


def problem_ids(rows: list[dict]) -> set[tuple[str, str | None, str, str]]:
    """The (method, operation, code, where) of every problem in scan rows."""
    found = set()
    for row in rows:
        method = row.get("method")
        operation = row.get("operation")
        for code, where in row.get("problems", []):
            found.add((method, operation, code, where))
    return found


def _flagged(case: dict, history: Path, specs: dict, commit: str) -> bool:
    """Whether the case's exact problem appears in its page at one commit."""
    page = history / commit / case["page"]
    if not page.is_file():
        return False
    text = page.read_text(encoding="utf-8")
    result = scan({case["page"]: text}, specs)
    key = (case["method"], case["operation"], case["code"], case["where"])
    return key in problem_ids(result["calls"])


def evaluate(case: dict, history: str | Path, specs: dict) -> dict:
    """Whether a ledger case is detected at its bug and gone at its fix."""
    folder = Path(history)
    introduced = _flagged(case, folder, specs, case["introduced"])
    detected = _flagged(case, folder, specs, case["buggy"])
    cleared = not _flagged(case, folder, specs, case["fixed"])
    return {
        "id": case["id"],
        "introduced_detected": introduced,
        "detected": detected,
        "cleared": cleared,
        "caught": detected and cleared,
    }


def _to_date(value: object) -> date:
    """A date from a JSON date string, datetime or date."""
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    return date.fromisoformat(str(value)[:10])


def days_open(case: dict, commits: dict) -> int:
    """Days from the introduced commit's date to the fixed commit's date."""
    introduced = commits[case["introduced"]]["date"]
    fixed = commits[case["fixed"]]["date"]
    return (_to_date(fixed) - _to_date(introduced)).days
