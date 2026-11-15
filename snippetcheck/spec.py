"""Match HTTP calls to OpenAPI operations and read the pieces a check needs."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

METHODS = ("get", "post", "put", "patch", "delete")
MAX_REF_DEPTH = 12


@dataclass(frozen=True)
class Operation:
    """One OpenAPI operation, tagged with the spec it was read from."""

    spec: str
    method: str
    template: str
    op: dict[str, Any]

    @property
    def name(self) -> str:
        """The operation as reports name it, e.g. "POST /ns/{namespace}/search"."""
        return f"{self.method} {self.template}"


def operations(specs: list[tuple[str, dict[str, Any]]]) -> list[Operation]:
    """Every get, post, put, patch and delete operation, specs, paths and methods in file order."""
    found: list[Operation] = []
    for name, spec in specs:
        paths = spec.get("paths")
        if not isinstance(paths, dict):
            continue
        for template, item in paths.items():
            if not isinstance(item, dict):
                continue
            for method, detail in item.items():
                if method in METHODS and isinstance(detail, dict):
                    found.append(Operation(name, method.upper(), template, detail))
    return found


def segments(path: str) -> list[str]:
    """The non-empty parts of a path."""
    return [part for part in path.split("/") if part]


def _placeholder(segment: str) -> bool:
    """Whether one template segment is a {name} placeholder."""
    return len(segment) > 2 and segment[0] == "{" and segment[-1] == "}"


def _fits(template: str, parts: list[str]) -> bool:
    """Whether a template has the same segment count and matches every segment."""
    template_parts = segments(template)
    if len(template_parts) != len(parts):
        return False
    return all(_placeholder(segment) or segment == part for segment, part in zip(template_parts, parts, strict=True))


def _literal_segments(template: str) -> int:
    """How many template segments are literals rather than placeholders."""
    return sum(1 for segment in segments(template) if not _placeholder(segment))


def match(ops: list[Operation], method: str, path: str) -> tuple[Operation | None, tuple[str, str] | None]:
    """The operation a method and path reach, or the reason none does."""
    parts = segments(path)
    fitting = [operation for operation in ops if _fits(operation.template, parts)]
    if not fitting:
        return None, ("unknown_path", path)
    wanted = method.upper()
    allowed = [operation for operation in fitting if operation.method.upper() == wanted]
    if not allowed:
        methods = ",".join(sorted({operation.method.upper() for operation in fitting}))
        return None, ("method_not_allowed", methods)
    best, best_literals = allowed[0], _literal_segments(allowed[0].template)
    for operation in allowed[1:]:
        literals = _literal_segments(operation.template)
        if literals > best_literals:
            best, best_literals = operation, literals
    return best, None


def _resolve(spec: dict[str, Any], ref: str) -> Any:
    """The node a local JSON pointer names, or None when the pointer does not resolve."""
    if not ref.startswith("#/"):
        return None
    node: Any = spec
    for raw in ref[2:].split("/"):
        key = raw.replace("~1", "/").replace("~0", "~")
        if not isinstance(node, dict) or key not in node:
            return None
        node = node[key]
    return node


def deref(spec: dict[str, Any], schema: Any) -> Any:
    """Follow local $ref chains, the ref node's sibling keys winning over the target's."""
    current = schema
    for _ in range(MAX_REF_DEPTH):
        if not isinstance(current, dict):
            break
        ref = current.get("$ref")
        if not isinstance(ref, str):
            break
        target = _resolve(spec, ref)
        if target is None:
            break
        if not isinstance(target, dict):
            return target
        merged = dict(target)
        merged.update({key: value for key, value in current.items() if key != "$ref"})
        current = merged
    return current


def body_schemas(operation: Operation) -> dict[str, Any]:
    """The operation's request body schemas by content type; empty when it takes no body."""
    body = operation.op.get("requestBody")
    if not isinstance(body, dict):
        return {}
    content = body.get("content")
    if not isinstance(content, dict):
        return {}
    schemas: dict[str, Any] = {}
    for media, entry in content.items():
        if isinstance(entry, dict) and "schema" in entry:
            schemas[media] = entry["schema"]
    return schemas


def params(operation: Operation, where: str) -> dict[str, dict[str, Any]]:
    """The operation's parameters with `in` equal to where, keyed by name."""
    declared = operation.op.get("parameters")
    if not isinstance(declared, list):
        return {}
    found: dict[str, dict[str, Any]] = {}
    for parameter in declared:
        if not isinstance(parameter, dict) or parameter.get("in") != where:
            continue
        name = parameter.get("name")
        if isinstance(name, str):
            found[name] = parameter
    return found
