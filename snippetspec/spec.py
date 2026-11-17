"""Match HTTP calls to OpenAPI operations and read the pieces a check needs."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any
from urllib.parse import urlsplit

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
        prefix = base_path(spec)
        for template, item in paths.items():
            if not isinstance(item, dict):
                continue
            for method, detail in item.items():
                if method in METHODS and isinstance(detail, dict):
                    found.append(
                        Operation(name, method.upper(), prefix + template, _with_path_parameters(item, detail))
                    )
    return found


def base_path(spec: dict[str, Any]) -> str:
    """The first server URL's path (e.g. "/v2"), which the docs write in front of every spec path."""
    servers = spec.get("servers")
    url = servers[0].get("url") if isinstance(servers, list) and servers and isinstance(servers[0], dict) else None
    if not isinstance(url, str) or "{" in url:
        return ""
    try:
        return urlsplit(url).path.rstrip("/")
    except ValueError:
        return ""


def _with_path_parameters(item: dict[str, Any], detail: dict[str, Any]) -> dict[str, Any]:
    """The operation with its path item's shared parameters added; the operation's own win."""
    shared = item.get("parameters")
    if not isinstance(shared, list) or not shared:
        return detail
    own = detail.get("parameters") if isinstance(detail.get("parameters"), list) else []
    return {**detail, "parameters": [*shared, *own]}


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
    found, problem = candidates(ops, method, path)
    return (found[0] if found else None), problem


def candidates(ops: list[Operation], method: str, path: str) -> tuple[list[Operation], tuple[str, str] | None]:
    """The most specific operations a method and path reach, earliest first, or the reason none does."""
    parts = segments(path)
    fitting = [operation for operation in ops if _fits(operation.template, parts)]
    if not fitting:
        return [], ("unknown_path", path)
    wanted = method.upper()
    allowed = [operation for operation in fitting if operation.method.upper() == wanted]
    if not allowed:
        methods = ",".join(sorted({operation.method.upper() for operation in fitting}))
        return [], ("method_not_allowed", methods)
    most = max(_literal_segments(operation.template) for operation in allowed)
    return [operation for operation in allowed if _literal_segments(operation.template) == most], None


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


def merge_all_of(spec: dict[str, Any], schema: Any, depth: int = 0) -> Any:
    """A schema with its allOf parts folded in: properties and required lists combined, its own keys winning."""
    if not isinstance(schema, dict) or not isinstance(schema.get("allOf"), list) or depth > MAX_REF_DEPTH:
        return schema
    merged: dict[str, Any] = {}
    properties: dict[str, Any] = {}
    required: list[str] = []
    for part in schema["allOf"]:
        part = merge_all_of(spec, deref(spec, part), depth + 1)
        if not isinstance(part, dict):
            continue
        properties.update(part.get("properties") or {})
        required += [name for name in part.get("required") or [] if name not in required]
        merged.update({key: value for key, value in part.items() if key not in ("properties", "required")})
    own = {key: value for key, value in schema.items() if key != "allOf"}
    properties.update(own.pop("properties", None) or {})
    required += [name for name in own.pop("required", None) or [] if name not in required]
    merged.update(own)
    if properties:
        merged["properties"] = properties
    if required:
        merged["required"] = required
    return merged


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


def params(spec: dict[str, Any], operation: Operation, where: str) -> dict[str, dict[str, Any]]:
    """The operation's parameters with `in` equal to where, keyed by name, with $refs followed."""
    declared = operation.op.get("parameters")
    if not isinstance(declared, list):
        return {}
    found: dict[str, dict[str, Any]] = {}
    for parameter in (deref(spec, item) for item in declared):
        if not isinstance(parameter, dict) or parameter.get("in") != where:
            continue
        name = parameter.get("name")
        if isinstance(name, str):
            found[name] = parameter
    return found
