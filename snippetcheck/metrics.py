"""Distinct findings, the problem-code vocabulary and ratio rounding."""

from __future__ import annotations

from urllib.parse import urlsplit

CODES = (
    "unknown_path",
    "method_not_allowed",
    "undocumented_param",
    "missing_param",
    "enum",
    "type",
    "undocumented_field",
    "missing_field",
    "unexpected_body",
    "missing_body",
    "content_type",
)


def ratio(part: int, whole: int) -> float:
    """A share rounded to six places, or 0.0 when there is nothing to divide."""
    return round(part / whole, 6) if whole else 0.0


def _path(url: str) -> str:
    """The path part of a URL, still percent-encoded."""
    try:
        return urlsplit(url).path
    except ValueError:
        return ""


def findings(rows: list[dict]) -> list[tuple[str, str, str, str]]:
    """The sorted distinct (method, URL path, code, where) over every problem."""
    found = set()
    for row in rows:
        path = _path(row.get("url", ""))
        for code, where in row.get("problems", []):
            found.add((row.get("method"), path, code, where))
    return sorted(found)
