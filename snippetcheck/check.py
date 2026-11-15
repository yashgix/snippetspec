"""Check one HTTP call against the operation and schemas an OpenAPI spec declares."""

from __future__ import annotations

import re
from urllib.parse import unquote, urlsplit

from snippetcheck.calls import Call
from snippetcheck.jsread import UNKNOWN
from snippetcheck.spec import Operation, body_schemas, deref, match, params, segments

PLACEHOLDER_CHARACTERS = frozenset("${}<>")
INTEGER = re.compile(r"-?[0-9]+")
NUMBER = re.compile(r"-?[0-9]+(?:[.][0-9]+)?")
JSON = "application/json"
FORM_TYPES = ("multipart/form-data", "application/x-www-form-urlencoded")


def check_call(specs: dict, ops: list[Operation], call: Call) -> dict:
    """The operation a call reaches, named "spec:METHOD /template", and every problem with it."""
    path = _path_of(call.url)
    operation, problem = match(ops, call.method, path)
    if operation is None:
        return {"operation": None, "problems": [problem]}
    spec = specs[operation.spec]
    problems = [
        *_path_problems(spec, operation, path),
        *_query_problems(spec, operation, call.query),
        *_body_problems(spec, operation, call),
    ]
    return {"operation": f"{operation.spec}:{operation.name}", "problems": problems}


def validate(spec: dict, schema: object, value: object, where: str = "$") -> list[tuple[str, str]]:
    """Every problem a JSON value has with a schema, each as a (code, where) pair."""
    if is_placeholder(value):
        return []
    resolved = deref(spec, schema)
    if not isinstance(resolved, dict):
        return []
    branches = _branches(resolved)
    if branches is not None:
        return _choice_problems(spec, branches, value, where)
    if not _type_fits(resolved.get("type"), value):
        return [("type", where)]
    if "const" in resolved and value != resolved["const"]:
        return [("enum", where)]
    enum = resolved.get("enum")
    if isinstance(enum, list) and value not in enum:
        return [("enum", where)]
    if isinstance(value, list) and "items" in resolved:
        return [
            problem
            for index, item in enumerate(value)
            for problem in validate(spec, resolved["items"], item, f"{where}[{index}]")
        ]
    if isinstance(value, dict) and isinstance(resolved.get("properties"), dict):
        return _object_problems(spec, resolved, value, where)
    return []


def is_placeholder(value: object) -> bool:
    """Whether a value stands for something the spec cannot know, so every schema accepts it."""
    if value is UNKNOWN:
        return True
    return isinstance(value, str) and any(character in PLACEHOLDER_CHARACTERS for character in value)


def _path_of(url: str) -> str:
    """The path part of a URL, still percent-encoded."""
    try:
        return urlsplit(url).path
    except ValueError:
        return ""


def _branches(schema: dict) -> list | None:
    """A schema's anyOf branches, else its oneOf branches, else None."""
    for key in ("anyOf", "oneOf"):
        branches = schema.get(key)
        if isinstance(branches, list) and branches:
            return branches
    return None


def _choice_problems(spec: dict, branches: list, value: object, where: str) -> list[tuple[str, str]]:
    """The fewest problems among the branches whose own type fits the value."""
    problems = [validate(spec, branch, value, where) for branch in branches]
    if any(not found for found in problems):
        return []
    fitting = [
        (len(found), index)
        for index, (branch, found) in enumerate(zip(branches, problems, strict=True))
        if _branch_fits(spec, branch, value)
    ]
    if not fitting:
        return [("type", where)]
    return problems[min(fitting)[1]]


def _branch_fits(spec: dict, branch: object, value: object) -> bool:
    """Whether a choice branch's declared type accepts a value."""
    resolved = deref(spec, branch)
    if not isinstance(resolved, dict):
        return True
    return _type_fits(resolved.get("type"), value)


def _type_fits(declared: object, value: object) -> bool:
    """Whether a schema's type, list of types or absent type accepts a JSON value."""
    if declared is None:
        return True
    if isinstance(declared, list):
        return any(_one_type_fits(name, value) for name in declared)
    return _one_type_fits(declared, value)


def _one_type_fits(name: object, value: object) -> bool:
    """Whether one JSON type name accepts a value; an unknown name constrains nothing."""
    if name == "string":
        return isinstance(value, str)
    if name == "boolean":
        return isinstance(value, bool)
    if name == "integer":
        return isinstance(value, int) and not isinstance(value, bool)
    if name == "number":
        return isinstance(value, int | float) and not isinstance(value, bool)
    if name == "array":
        return isinstance(value, list)
    if name == "object":
        return isinstance(value, dict)
    if name == "null":
        return value is None
    return True


def _object_problems(spec: dict, schema: dict, value: dict, where: str) -> list[tuple[str, str]]:
    """Missing required keys, then each sent key's problems or its undocumented complaint."""
    properties = schema["properties"]
    required = schema.get("required")
    problems = []
    for key in required if isinstance(required, list) else []:
        if key not in value:
            problems.append(("missing_field", f"{where}.{key}"))
    additional = schema.get("additionalProperties")
    for key, item in value.items():
        if key in properties:
            problems.extend(validate(spec, properties[key], item, f"{where}.{key}"))
        elif additional is not True and not isinstance(additional, dict):
            problems.append(("undocumented_field", f"{where}.{key}"))
    return problems


def _path_problems(spec: dict, operation: Operation, path: str) -> list[tuple[str, str]]:
    """Problems with the URL-decoded value of each declared path parameter."""
    declared = params(operation, "path")
    problems = []
    for template, actual in zip(segments(operation.template), segments(path), strict=False):
        name = _parameter_name(template)
        parameter = declared.get(name) if name is not None else None
        if parameter is None:
            continue
        problems.extend(_parameter_problems(spec, parameter.get("schema"), unquote(actual), f"path:{name}"))
    return problems


def _parameter_name(segment: str) -> str | None:
    """The name of a {placeholder} template segment, else None."""
    if len(segment) > 2 and segment[0] == "{" and segment[-1] == "}":
        return segment[1:-1]
    return None


def _query_problems(spec: dict, operation: Operation, query: tuple) -> list[tuple[str, str]]:
    """Missing required parameters first, then each sent pair in order."""
    declared = params(operation, "query")
    sent = {name for name, _value in query}
    problems = []
    for name, parameter in declared.items():
        if parameter.get("required") is True and name not in sent:
            problems.append(("missing_param", f"query:{name}"))
    for name, value in query:
        parameter = declared.get(name)
        if parameter is None:
            problems.append(("undocumented_param", f"query:{name}"))
            continue
        problems.extend(_parameter_problems(spec, parameter.get("schema"), value, f"query:{name}"))
    return problems


def _parameter_problems(spec: dict, schema: object, value: str, where: str) -> list[tuple[str, str]]:
    """Problems with a parameter's text value, which is never parsed as JSON."""
    if is_placeholder(value):
        return []
    resolved = deref(spec, schema)
    if not isinstance(resolved, dict):
        return []
    branches = _branches(resolved)
    if branches is not None:
        if any(not _parameter_problems(spec, branch, value, where) for branch in branches):
            return []
        return [("type", where)]
    if resolved.get("type") == "array" and "items" in resolved:
        return _parameter_problems(spec, resolved["items"], value, where)
    if "const" in resolved:
        return [] if _text(resolved["const"]) == value else [("enum", where)]
    enum = resolved.get("enum")
    if isinstance(enum, list):
        return [] if value in [_text(item) for item in enum] else [("enum", where)]
    types = resolved.get("type")
    if types is None:
        return []
    if isinstance(types, list):
        return [] if any(_text_fits(name, value) for name in types) else [("type", where)]
    return [] if _text_fits(types, value) else [("type", where)]


def _text_fits(name: object, value: str) -> bool:
    """Whether a parameter's text is a valid instance of one schema type; other types pass."""
    if name == "integer":
        return INTEGER.fullmatch(value) is not None
    if name == "number":
        return NUMBER.fullmatch(value) is not None
    if name == "boolean":
        return value in ("true", "false")
    return True


def _text(value: object) -> str:
    """A schema constant as the text a path or query string would carry."""
    if value is True:
        return "true"
    if value is False:
        return "false"
    if value is None:
        return "null"
    return str(value)


def _body_problems(spec: dict, operation: Operation, call: Call) -> list[tuple[str, str]]:
    """Problems with the request body the call sends, if the operation takes one."""
    schemas = body_schemas(operation)
    if call.body_kind == "none":
        return [("missing_body", "body")] if _body_required(operation) else []
    if not schemas:
        if call.body_kind == "json" and call.body == {}:
            return []
        return [("unexpected_body", "body")]
    media, missing = _media_type(schemas, call.body_kind)
    if media is None:
        return [missing]
    schema = deref(spec, schemas[media])
    if call.body_kind == "form":
        return _form_problems(schema, call.body)
    if call.body_kind == "json":
        return validate(spec, schema, call.body)
    return []


def _body_required(operation: Operation) -> bool:
    """Whether the operation marks its request body required."""
    body = operation.op.get("requestBody")
    return isinstance(body, dict) and body.get("required") is True


def _media_type(schemas: dict, kind: str) -> tuple[str | None, tuple[str, str] | None]:
    """The media type a body kind may use, or None and the problem to report instead."""
    if kind == "form":
        for name in FORM_TYPES:
            if name in schemas:
                return name, None
        return None, ("content_type", "body:form")
    if JSON in schemas:
        return JSON, None
    return None, ("content_type", "body:json")


def _form_problems(schema: object, body: object) -> list[tuple[str, str]]:
    """Missing required and undocumented field names of a form body; values are not checked."""
    if not isinstance(schema, dict) or not isinstance(schema.get("properties"), dict):
        return []
    if not isinstance(body, dict):
        return []
    properties = schema["properties"]
    required = schema.get("required")
    problems = []
    for name in required if isinstance(required, list) else []:
        if name not in body:
            problems.append(("missing_field", f"$.{name}"))
    additional = schema.get("additionalProperties")
    for name in body:
        if name not in properties and additional is not True and not isinstance(additional, dict):
            problems.append(("undocumented_field", f"$.{name}"))
    return problems
