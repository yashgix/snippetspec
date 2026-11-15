"""Extract fenced code examples and their Margin-style alternatives groups from MDX text."""

from __future__ import annotations

import re
from dataclasses import dataclass

CONTAINERS = ("CodeBlockTabs", "Tabs", "CodeGroup", "CodeTabs", "ViewGroup")

FENCE = re.compile(r"^( *)(`{3,}|~{3,})(.*)$")
TITLE_DOUBLE = re.compile(r'title="([^"]*)"')
TITLE_SINGLE = re.compile(r"title='([^']*)'")
TITLE_BARE = re.compile(r"(?:^|\s)title=(\S+)")


@dataclass(frozen=True)
class Example:
    page: str
    line: int
    language: str
    title: str | None
    meta: str | None
    code: str
    group: int | None


def _title(meta: str | None) -> str | None:
    """Margin's rule: double-quoted title, then single-quoted, then a bare value."""
    if not meta:
        return None
    for pattern in (TITLE_DOUBLE, TITLE_SINGLE, TITLE_BARE):
        found = pattern.search(meta)
        if found:
            return found.group(1)
    return None


def _info(info: str) -> tuple[str, str | None, str | None]:
    """(language, meta, title) from a fence's info string."""
    info = info.strip()
    language, _, rest = info.partition(" ")
    meta = rest.strip() or None
    return (language or "text"), meta, _title(meta)


def _open(line: str) -> tuple[int, str, str] | None:
    """(indent, marker, info) when the line opens a fenced block."""
    found = FENCE.match(line)
    if not found:
        return None
    indent, marker, info = found.groups()
    if marker[0] == "`" and "`" in info:
        return None
    return len(indent), marker, info


def _closes(line: str, marker: str) -> bool:
    """A closing fence is optional whitespace around at least as many marker characters."""
    stripped = line.strip()
    return len(stripped) >= len(marker) and stripped == marker[0] * len(stripped)


def _dedent(line: str, indent: int) -> str:
    """Remove up to `indent` leading spaces from one content line."""
    cut = 0
    while cut < indent and line[cut : cut + 1] == " ":
        cut += 1
    return line[cut:]


def _container(line: str) -> tuple[str, str] | None:
    """("open"|"close", name) for an alternatives container line, else None."""
    for name in CONTAINERS:
        for kind, head in (("close", "</" + name), ("open", "<" + name)):
            if not line.startswith(head):
                continue
            rest = line[len(head) :]
            if rest[:1] not in ("", " ", "\t", ">"):
                continue
            if kind == "open" and line.endswith("/>"):
                continue
            return kind, name
    return None


def extract(text: str, page: str = "") -> list[Example]:
    """Every fenced code block of a page, in order, with its group number when inside a container."""
    lines = text.split("\n")
    examples: list[Example] = []
    stack: list[str] = []
    group: int | None = None
    groups = 0
    index = 0
    while index < len(lines):
        opening = _open(lines[index])
        if opening is not None:
            indent, marker, info = opening
            end = index + 1
            while end < len(lines) and not _closes(lines[end], marker):
                end += 1
            body = [_dedent(line, indent) for line in lines[index + 1 : end]]
            language, meta, title = _info(info)
            examples.append(Example(page, index + 1, language, title, meta, "\n".join(body), group))
            index = end + 1
            continue
        found = _container(lines[index].strip())
        if found is not None:
            kind, name = found
            if kind == "open":
                if not stack:
                    groups += 1
                    group = groups - 1
                stack.append(name)
            elif stack:
                stack.pop()
                if not stack:
                    group = None
        index += 1
    return examples
