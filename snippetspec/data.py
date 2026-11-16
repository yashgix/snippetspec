"""Pinned data locations and loaders used by snippetspec."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data"
STUDY = ROOT / "study"
SPECS = ("v4", "v5")
HOST = "api.supermemory.ai"


def load_json(path: str | Path) -> Any:
    """Parse a JSON file as UTF-8."""
    return json.loads(Path(path).read_text(encoding="utf-8"))


def load_specs(data: str | Path = DATA) -> dict[str, Any]:
    """Load the pinned OpenAPI specs in SPECS order."""
    folder = Path(data)
    return {name: load_json(folder / "openapi" / f"{name}.json") for name in SPECS}


def load_pages(folder: str | Path) -> dict[str, str]:
    """Return every .mdx file under folder, keyed by its '/'-joined relative path."""
    base = Path(folder)
    paths = sorted(base.rglob("*.mdx"), key=lambda path: path.relative_to(base).as_posix())
    return {path.relative_to(base).as_posix(): path.read_text(encoding="utf-8") for path in paths}
