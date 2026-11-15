"""Seed API drift into a spec and check that the calls which used it are flagged."""

from __future__ import annotations

import copy
from urllib.parse import unquote, urlsplit

from snippetcheck.calls import Call
from snippetcheck.check import check_call
from snippetcheck.spec import Operation, body_schemas, deref, operations, params, segments

BREAKING = {
    "remove_operation": ("unknown_path", "method_not_allowed"),
    "rename_field": ("undocumented_field",),
    "add_required": ("missing_field",),
    "drop_enum_value": ("enum",),
    "rename_param": ("undocumented_param",),
}
NEUTRAL = ("add_optional", "add_enum_value")


def _text(value: object) -> str:
    """A schema constant as the text a URL or body value would carry."""
    if value is True:
        return "true"
    if value is False:
        return "false"
    if value is None:
        return "null"
    return str(value)


def _in_enum(value: str, enum: list) -> bool:
    """Whether a sent string equals one of an enum's values as text."""
    return any(_text(item) == value for item in enum)


def _enum_of(spec: dict, schema: object) -> list | None:
    """The schema's own top-level enum after dereferencing, when it has one."""
    resolved = deref(spec, schema)
    if isinstance(resolved, dict) and isinstance(resolved.get("enum"), list):
        return resolved["enum"]
    return None


def _object_bodies(spec: dict, operation: Operation) -> list[dict]:
    """The operation's dereferenced request body schemas that declare properties."""
    bodies = []
    for schema in body_schemas(operation).values():
        resolved = deref(spec, schema)
        if isinstance(resolved, dict) and isinstance(resolved.get("properties"), dict):
            bodies.append(resolved)
    return bodies


def _property_names(bodies: list[dict]) -> set[str]:
    """Every top-level property name declared by any object body."""
    names: set[str] = set()
    for body in bodies:
        names.update(body.get("properties", {}))
    return names


def _property_enum(spec: dict, bodies: list[dict], key: str) -> list | None:
    """The enum of the first object body property named key, if it has one."""
    for body in bodies:
        properties = body.get("properties", {})
        if key in properties:
            return _enum_of(spec, properties[key])
    return None


def _placeholder_name(segment: str) -> str | None:
    """The name of a {placeholder} template segment, else None."""
    if len(segment) > 2 and segment[0] == "{" and segment[-1] == "}":
        return segment[1:-1]
    return None


def _url_segments(url: str) -> list[str]:
    """The URL-decoded non-empty path segments of a URL."""
    try:
        path = urlsplit(url).path
    except ValueError:
        return []
    return [unquote(part) for part in segments(path)]


def _drop_enum_mutations(spec: dict, operation: Operation, call: Call, bodies: list[dict]) -> list[str]:
    """The drop_enum_value mutations for the values a call sends."""
    found = []
    path_parameters = params(operation, "path")
    template = segments(operation.template)
    actual = _url_segments(call.url)
    for index, segment in enumerate(template):
        name = _placeholder_name(segment)
        if name is None or name not in path_parameters or index >= len(actual):
            continue
        enum = _enum_of(spec, path_parameters[name].get("schema"))
        if enum is not None and len(enum) >= 2 and _in_enum(actual[index], enum):
            found.append(f"drop_enum_value:path:{name}={actual[index]}")
    query_parameters = params(operation, "query")
    for name, value in call.query:
        parameter = query_parameters.get(name)
        if parameter is None:
            continue
        enum = _enum_of(spec, parameter.get("schema"))
        if enum is not None and len(enum) >= 2 and _in_enum(value, enum):
            found.append(f"drop_enum_value:query:{name}={value}")
    if call.body_kind == "json" and isinstance(call.body, dict):
        for name, value in call.body.items():
            if not isinstance(value, str):
                continue
            enum = _property_enum(spec, bodies, name)
            if enum is not None and len(enum) >= 2 and _in_enum(value, enum):
                found.append(f"drop_enum_value:body:{name}={value}")
    return found


def _has_enum(spec: dict, operation: Operation, bodies: list[dict]) -> bool:
    """Whether a path or query parameter or body property declares an enum."""
    for where in ("path", "query"):
        for parameter in params(operation, where).values():
            if _enum_of(spec, parameter.get("schema")) is not None:
                return True
    for body in bodies:
        for schema in body.get("properties", {}).values():
            if _enum_of(spec, schema) is not None:
                return True
    return False


def mutations(spec: dict, operation: Operation, call: Call) -> list[str]:
    """Every seeded mutation that applies to one call of one operation, in a stable order."""
    found = ["remove_operation"]
    bodies = _object_bodies(spec, operation)
    body = call.body if call.body_kind in ("json", "form") and isinstance(call.body, dict) else None
    if body:
        properties = _property_names(bodies)
        for key in body:
            if key in properties:
                found.append(f"rename_field:{key}")
    if body and bodies:
        found.append("add_required")
    found.extend(_drop_enum_mutations(spec, operation, call, bodies))
    declared = params(operation, "query")
    seen: set[str] = set()
    for name, _value in call.query:
        if name in declared and name not in seen:
            seen.add(name)
            found.append(f"rename_param:{name}")
    if bodies:
        found.append("add_optional")
    if _has_enum(spec, operation, bodies):
        found.append("add_enum_value")
    return found


def _path_item(spec: dict, operation: Operation) -> dict | None:
    """The path item an operation lives under."""
    paths = spec.get("paths")
    if not isinstance(paths, dict):
        return None
    item = paths.get(operation.template)
    return item if isinstance(item, dict) else None


def _operation_detail(path_item: dict | None, operation: Operation) -> dict | None:
    """The operation object under a path item, matched without regard to method case."""
    if path_item is None:
        return None
    for method, detail in path_item.items():
        if isinstance(method, str) and method.lower() == operation.method.lower() and isinstance(detail, dict):
            return detail
    return None


def _inline_schemas(spec: dict, detail: dict) -> None:
    """Replace this operation's body and parameter schemas with independent dereferenced copies."""
    body = detail.get("requestBody")
    if isinstance(body, dict):
        content = body.get("content")
        if isinstance(content, dict):
            for entry in content.values():
                if not isinstance(entry, dict) or "schema" not in entry:
                    continue
                resolved = copy.deepcopy(deref(spec, entry["schema"]))
                if isinstance(resolved, dict) and isinstance(resolved.get("properties"), dict):
                    for name, schema in list(resolved["properties"].items()):
                        resolved["properties"][name] = copy.deepcopy(deref(spec, schema))
                entry["schema"] = resolved
    parameters = detail.get("parameters")
    if isinstance(parameters, list):
        for parameter in parameters:
            if isinstance(parameter, dict) and "schema" in parameter:
                parameter["schema"] = copy.deepcopy(deref(spec, parameter["schema"]))


def _detail_object_bodies(detail: dict) -> list[dict]:
    """An inlined operation's body schemas that declare properties."""
    bodies = []
    body = detail.get("requestBody")
    if not isinstance(body, dict):
        return bodies
    content = body.get("content")
    if not isinstance(content, dict):
        return bodies
    for entry in content.values():
        if not isinstance(entry, dict):
            continue
        schema = entry.get("schema")
        if isinstance(schema, dict) and isinstance(schema.get("properties"), dict):
            bodies.append(schema)
    return bodies


def _parameters(detail: dict) -> list[dict]:
    """The dict parameters of an inlined operation."""
    parameters = detail.get("parameters")
    if not isinstance(parameters, list):
        return []
    return [parameter for parameter in parameters if isinstance(parameter, dict)]


def _rename_field(bodies: list[dict], name: str) -> None:
    """Rename one body property, and its required entry, in every object body."""
    renamed = name + "_renamed"
    for body in bodies:
        properties = body.get("properties", {})
        body["properties"] = {renamed if key == name else key: value for key, value in properties.items()}
        required = body.get("required")
        if isinstance(required, list):
            body["required"] = [renamed if item == name else item for item in required]


def _add_required(bodies: list[dict]) -> None:
    """Add a new required field to every object body."""
    for body in bodies:
        body["properties"]["addedField"] = {"type": "string"}
        required = body.get("required")
        if not isinstance(required, list):
            required = []
        if "addedField" not in required:
            required.append("addedField")
        body["required"] = required


def _add_optional(bodies: list[dict]) -> None:
    """Add a new optional field to every object body."""
    for body in bodies:
        body["properties"]["addedOptional"] = {"type": "string"}


def _parse_drop(rest: str) -> tuple[str, str, str] | None:
    """The location, name and value encoded in a drop_enum_value mutation."""
    left, separator, value = rest.partition("=")
    if not separator:
        return None
    if ":" in left:
        parts = left.split(":")
        if len(parts) >= 2:
            return parts[0], parts[1], value
    if left.startswith("body."):
        return "body", left[5:], value
    return None


def _drop_enum(detail: dict, bodies: list[dict], location: str, name: str, value: str) -> None:
    """Remove a value from a parameter or body-property enum."""
    if location == "body":
        for body in bodies:
            schema = body.get("properties", {}).get(name)
            if isinstance(schema, dict) and isinstance(schema.get("enum"), list):
                schema["enum"] = [item for item in schema["enum"] if _text(item) != value]
        return
    for parameter in _parameters(detail):
        if parameter.get("in") != location or parameter.get("name") != name:
            continue
        schema = parameter.get("schema")
        if isinstance(schema, dict) and isinstance(schema.get("enum"), list):
            schema["enum"] = [item for item in schema["enum"] if _text(item) != value]


def _rename_param(detail: dict, name: str) -> None:
    """Rename a declared query parameter."""
    for parameter in _parameters(detail):
        if parameter.get("in") == "query" and parameter.get("name") == name:
            parameter["name"] = name + "_renamed"


def _add_enum_value(detail: dict, bodies: list[dict]) -> None:
    """Append a value to every parameter enum and body-property enum."""
    for parameter in _parameters(detail):
        schema = parameter.get("schema")
        if isinstance(schema, dict) and isinstance(schema.get("enum"), list):
            schema["enum"].append("added-value")
    for body in bodies:
        for schema in body.get("properties", {}).values():
            if isinstance(schema, dict) and isinstance(schema.get("enum"), list):
                schema["enum"].append("added-value")


def apply(spec: dict, operation: Operation, mutation: str) -> dict:
    """A deep copy of spec with one mutation applied to one operation."""
    changed = copy.deepcopy(spec)
    path_item = _path_item(changed, operation)
    if mutation == "remove_operation":
        if path_item is not None:
            for method in list(path_item):
                if isinstance(method, str) and method.lower() == operation.method.lower():
                    del path_item[method]
        return changed
    detail = _operation_detail(path_item, operation)
    if detail is None:
        return changed
    _inline_schemas(changed, detail)
    bodies = _detail_object_bodies(detail)
    kind, _separator, rest = mutation.partition(":")
    if kind == "rename_field":
        _rename_field(bodies, rest)
    elif kind == "add_required":
        _add_required(bodies)
    elif kind == "add_optional":
        _add_optional(bodies)
    elif kind == "rename_param":
        _rename_param(detail, rest)
    elif kind == "add_enum_value":
        _add_enum_value(detail, bodies)
    elif kind == "drop_enum_value":
        parsed = _parse_drop(rest)
        if parsed is not None:
            _drop_enum(detail, bodies, *parsed)
    return changed


def _call_of(item: object) -> Call | None:
    """A Call from either a Call or a page_calls-style (example, index, call) triple."""
    if isinstance(item, Call):
        return item
    if isinstance(item, tuple | list) and len(item) == 3 and isinstance(item[2], Call):
        return item[2]
    return None


def run(specs: dict, calls: list) -> list[dict]:
    """Seeded-drift rows for every clean call, with the problem codes each mutation causes."""
    ops = operations(list(specs.items()))
    by_name = {f"{operation.spec}:{operation.name}": operation for operation in ops}
    rows = []
    for item in calls:
        call = _call_of(item)
        if call is None:
            continue
        result = check_call(specs, ops, call)
        if result["problems"]:
            continue
        operation = by_name.get(result["operation"])
        if operation is None:
            continue
        spec = specs[operation.spec]
        for mutation in mutations(spec, operation, call):
            changed = dict(specs)
            changed[operation.spec] = apply(spec, operation, mutation)
            changed_ops = operations(list(changed.items()))
            checked = check_call(changed, changed_ops, call)
            codes = sorted({code for code, _where in checked["problems"]})
            rows.append({"mutation": mutation, "operation": result["operation"], "codes": codes})
    return rows
