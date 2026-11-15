"""Scan the HTTP calls in docs code examples and report a verdict for each."""

from __future__ import annotations

from urllib.parse import urlsplit

from snippetcheck.calls import Call, find_calls, unparsed_commands
from snippetcheck.check import check_call
from snippetcheck.data import HOST
from snippetcheck.jsread import UNKNOWN
from snippetcheck.mdx import Example, extract
from snippetcheck.spec import operations


def _host(url: str) -> str | None:
    """The hostname a URL names, or None when it cannot be parsed."""
    try:
        return urlsplit(url).hostname
    except ValueError:
        return None


def page_calls(pages: dict[str, str], host: str = HOST) -> list[tuple[Example, int, Call]]:
    """Every call to host, with its index among such calls within its example."""
    found: list[tuple[Example, int, Call]] = []
    for page, text in pages.items():
        for example in extract(text, page):
            index = 0
            for call in find_calls(example):
                if _host(call.url) != host:
                    continue
                found.append((example, index, call))
                index += 1
    return found


def _counts(pages: dict[str, str], host: str) -> tuple[int, int, int]:
    """The number of examples, of calls to a host other than host, and of curl commands that could not be read."""
    examples = 0
    other_host = 0
    unparsed = 0
    for page, text in pages.items():
        for example in extract(text, page):
            examples += 1
            unparsed += len(unparsed_commands(example))
            for call in find_calls(example):
                if _host(call.url) != host:
                    other_host += 1
    return examples, other_host, unparsed


def _contains_unknown(value: object) -> bool:
    """Whether a JSON-like value contains UNKNOWN at any depth."""
    if value is UNKNOWN:
        return True
    if isinstance(value, dict):
        return any(_contains_unknown(item) for item in value.values())
    if isinstance(value, list | tuple):
        return any(_contains_unknown(item) for item in value)
    return False


def _partial(call: Call) -> bool:
    """Whether a call without problems still carries an uncheckable body."""
    if call.body_kind == "unparsed":
        return True
    return call.body_kind == "json" and _contains_unknown(call.body)


def scan(pages: dict[str, str], specs: dict, host: str = HOST) -> dict:
    """Check every call to host in every page against the operations the specs declare."""
    examples, other_host, unparsed = _counts(pages, host)
    ops = operations(list(specs.items()))
    rows = []
    for example, index, call in page_calls(pages, host):
        result = check_call(specs, ops, call)
        problems = [[code, where] for code, where in result["problems"]]
        if problems:
            verdict = "mismatch"
        elif _partial(call):
            verdict = "partial"
        else:
            verdict = "ok"
        rows.append(
            {
                "page": example.page,
                "line": example.line,
                "index": index,
                "language": example.language,
                "group": example.group,
                "tool": call.tool,
                "method": call.method,
                "url": call.url,
                "operation": result["operation"],
                "verdict": verdict,
                "problems": problems,
            }
        )
    return {"pages": len(pages), "examples": examples, "other_host": other_host, "unparsed": unparsed, "calls": rows}
