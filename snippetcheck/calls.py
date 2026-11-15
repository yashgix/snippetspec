"""Find the HTTP calls in docs code examples: curl, fetch and requests/httpx."""

from __future__ import annotations

import ast
import json
import re
import shlex
from dataclasses import dataclass
from urllib.parse import parse_qsl, urlsplit

from snippetcheck.jsread import UNKNOWN, property_source, read_object, skip, value_at
from snippetcheck.mdx import Example

SHELL = frozenset({"bash", "sh", "shell", "zsh", "console", "terminal"})
JAVASCRIPT = frozenset({"javascript", "js", "jsx", "typescript", "ts", "tsx"})
PYTHON = frozenset({"python", "py"})
CLIENTS = frozenset({"requests", "httpx"})
METHODS = frozenset({"get", "post", "put", "patch", "delete", "request"})


@dataclass(frozen=True)
class Call:
    """One HTTP call: what an example sends, in a normal form."""

    tool: str
    method: str
    url: str
    query: tuple[tuple[str, str], ...]
    body_kind: str
    body: object


def find_calls(example: Example) -> list[Call]:
    """Every http(s) call an example makes, in source order."""
    language = example.language.lower()
    if language in SHELL:
        return _shell(example.code)
    if language in JAVASCRIPT:
        return _javascript(example.code)
    if language in PYTHON:
        return _python(example.code)
    return []


def _call(tool, method, url, body_kind="none", body=None, extra=()):
    """A call for an absolute http(s) URL with a host, else None."""
    try:
        parts = urlsplit(url)
    except ValueError:
        return None
    if parts.scheme not in ("http", "https") or not parts.hostname:
        return None
    query = tuple(parse_qsl(parts.query, keep_blank_values=True)) + tuple(extra)
    return Call(tool, method.upper(), url, query, body_kind, body)


# --- curl -------------------------------------------------------------------

_SEPARATORS = frozenset(";&|<>\n")
_LONG_ARGUMENT = {
    "request",
    "header",
    "url",
    "data",
    "data-raw",
    "data-binary",
    "data-ascii",
    "json",
    "form",
    "form-string",
    "output",
    "user",
    "user-agent",
    "referer",
    "cookie",
    "cookie-jar",
    "write-out",
    "max-time",
    "connect-timeout",
    "retry",
    "upload-file",
    "config",
    "proxy",
    "range",
    "cacert",
    "cert",
}
_SHORT_ARGUMENT = frozenset("XHdFouAebcwmTKxr")
_SHORT_OPTION = {"X": "request", "H": "header", "d": "data", "F": "form", "G": "get", "I": "head"}


def _shell(code):
    """Every curl call of a shell block, in source order."""
    text = code.replace("\\\n", " ")
    calls = []
    for command in _commands(text):
        words = _words(command)
        if words is None:
            return []
        call = _curl(words)
        if call is not None:
            calls.append(call)
    return calls


def _commands(text):
    """Shell text split into commands at unquoted separators; quoted newlines stay put."""
    commands = []
    current = []
    quote = ""
    index, size = 0, len(text)
    while index < size:
        char = text[index]
        if quote:
            if char == "\\" and quote == '"' and index + 1 < size:
                current.append(text[index : index + 2])
                index += 2
                continue
            if char == quote:
                quote = ""
            current.append(char)
        elif char == "\\" and index + 1 < size:
            current.append(text[index : index + 2])
            index += 2
            continue
        elif char in "'\"":
            quote = char
            current.append(char)
        elif char in _SEPARATORS:
            commands.append("".join(current))
            current = []
        else:
            current.append(char)
        index += 1
    commands.append("".join(current))
    return commands


def _words(command):
    """The words of one command, or None when its quoting is unbalanced."""
    try:
        return shlex.split(command, comments=True, posix=True)
    except ValueError:
        return None


def _curl(words):
    """The call one curl command makes, or None when it is not a curl command."""
    if words and words[0] == "$":
        words = words[1:]
    if not words or words[0].lstrip("$") != "curl":
        return None
    state = {
        "method": None,
        "get": False,
        "head": False,
        "json": False,
        "headers": [],
        "data": [],
        "forms": [],
        "url": None,
        "positional": None,
    }
    index = 1
    while index < len(words):
        word = words[index]
        if word.startswith("--") and len(word) > 2:
            index = _long_option(state, words, index)
        elif word.startswith("-") and len(word) > 1:
            index = _short_option(state, words, index)
        else:
            if state["positional"] is None:
                state["positional"] = word
            index += 1
    return _curl_call(state)


def _assign(state, name, value=""):
    """Record one curl option's value in the parse state."""
    if name == "request":
        state["method"] = value
    elif name == "header":
        state["headers"].append(value)
    elif name == "url":
        state["url"] = value
    elif name == "json":
        state["json"] = True
        state["data"].append(value)
    elif name in ("data", "data-raw", "data-binary", "data-ascii"):
        state["data"].append(value)
    elif name in ("form", "form-string"):
        state["forms"].append(value)
    elif name == "get":
        state["get"] = True
    elif name == "head":
        state["head"] = True


def _long_option(state, words, index):
    """Read one --option, with an inline value or the next word, and return the next index."""
    name, equals, inline = words[index][2:].partition("=")
    if equals:
        if name in _LONG_ARGUMENT:
            _assign(state, name, inline)
        return index + 1
    if name in _LONG_ARGUMENT:
        _assign(state, name, words[index + 1] if index + 1 < len(words) else "")
        return index + 2
    _assign(state, name)
    return index + 1


def _short_option(state, words, index):
    """Read one -group letter by letter and return the next index."""
    word = words[index]
    position = 1
    while position < len(word):
        letter = word[position]
        name = _SHORT_OPTION.get(letter)
        if letter in _SHORT_ARGUMENT:
            if position + 1 < len(word):
                value = word[position + 1 :]
            else:
                value = words[index + 1] if index + 1 < len(words) else ""
                index += 1
            if name:
                _assign(state, name, value)
            break
        if name:
            _assign(state, name)
        position += 1
    return index + 1


def _curl_call(state):
    """The Call a parsed curl command makes, or None when it names no URL."""
    url = state["url"] or state["positional"]
    if url is None:
        return None
    data = "&".join(state["data"])
    if state["get"]:
        extra = parse_qsl(data, keep_blank_values=True) if data else ()
        return _call("curl", state["method"] or "GET", url, extra=extra)
    if state["method"]:
        method = state["method"]
    elif state["head"]:
        method = "HEAD"
    elif state["data"] or state["forms"]:
        method = "POST"
    else:
        method = "GET"
    kind, body = _curl_body(state, data)
    return _call("curl", method, url, kind, body)


def _curl_body(state, data):
    """The body kind and value curl would send."""
    if state["forms"]:
        return "form", dict(_form_field(item) for item in state["forms"])
    if not state["data"]:
        return "none", None
    if data.startswith("@"):
        return "unparsed", None
    if state["json"] or _wants_json(state["headers"]) or data.lstrip()[:1] in ("{", "["):
        try:
            return "json", json.loads(data)
        except ValueError:
            return "unparsed", None
    return "form", dict(parse_qsl(data))


def _form_field(item):
    """One -F name=value pair; an @file or <file value is unknown."""
    name, equals, value = item.partition("=")
    if not equals or value[:1] in ("@", "<"):
        return name, UNKNOWN
    return name, value


def _wants_json(headers):
    """Whether any Content-Type header announces JSON."""
    for header in headers:
        name, _, value = header.partition(":")
        if name.strip().lower() == "content-type" and "json" in value.lower():
            return True
    return False


# --- fetch ------------------------------------------------------------------

_FETCH = re.compile(r"(?<![\w.$])fetch\s*\(")
_MISSING = object()


def _javascript(code):
    """Every fetch(...) call of a JavaScript block, in source order."""
    calls = []
    for found in _FETCH.finditer(code):
        try:
            call = _fetch_call(code, found.end())
        except Exception:  # one unreadable call must not hide the rest of the block
            call = None
        if call is not None:
            calls.append(call)
    return calls


def _fetch_call(text, index):
    """The call one fetch(...) makes, or None when its arguments are not literals."""
    url, end = value_at(text, index)
    if not isinstance(url, str):
        return None
    position = skip(text, end)
    if position >= len(text) or text[position] != ",":
        return _call("fetch", "GET", url)
    position = skip(text, position + 1)
    options, _end = read_object(text, position)
    if not isinstance(options, dict):
        return None
    method = options.get("method", "GET")
    if not isinstance(method, str):
        return None
    kind, body = _fetch_body(text, position, options)
    return _call("fetch", method, url, kind, body)


def _fetch_body(text, position, options):
    """The body kind and value a fetch call's options give."""
    if "body" not in options:
        return "none", None
    value = options["body"]
    if value is None:
        return "none", None
    inner = _stringify(property_source(text, position, "body") or "")
    if inner is not _MISSING:
        return "json", inner
    if isinstance(value, str):
        try:
            return "json", json.loads(value)
        except ValueError:
            return "unparsed", None
    return "unparsed", None


def _stringify(source):
    """The literal inside JSON.stringify(...), UNKNOWN for a non-literal, else _MISSING."""
    if not source.startswith("JSON.stringify"):
        return _MISSING
    position = skip(source, len("JSON.stringify"))
    if position >= len(source) or source[position] != "(":
        return _MISSING
    return value_at(source, position + 1)[0]


# --- requests / httpx -------------------------------------------------------


def _python(code):
    """Every requests/httpx call of a Python block, in source order."""
    try:
        tree = ast.parse(code)
    except SyntaxError, ValueError:
        return []
    found = []
    for node in ast.walk(tree):
        call = _python_call(node)
        if call is not None:
            found.append((node.lineno, node.col_offset, call))
    found.sort(key=lambda item: (item[0], item[1]))
    return [item[2] for item in found]


def _python_call(node):
    """The call one requests/httpx expression makes, or None for anything else."""
    if not isinstance(node, ast.Call):
        return None
    func = node.func
    if not isinstance(func, ast.Attribute) or func.attr not in METHODS:
        return None
    owner = func.value
    if not isinstance(owner, ast.Name) or owner.id not in CLIENTS:
        return None
    if func.attr == "request":
        method = _string(_argument(node, "method", 0))
        url_node = _argument(node, "url", 1)
    else:
        method = func.attr.upper()
        url_node = _argument(node, "url", 0)
    if method is None:
        return None
    url = _string(url_node)
    if url is None:
        return None
    kind, body = _python_body(node)
    return _call("requests", method, url, kind, body, _python_query(node))


def _argument(node, name, position):
    """A call argument by keyword, else by position, else None."""
    for keyword in node.keywords:
        if keyword.arg == name:
            return keyword.value
    if position is not None and position < len(node.args):
        return node.args[position]
    return None


def _python_query(node):
    """The extra query pairs a params= dict literal sends."""
    params = _argument(node, "params", None)
    if not isinstance(params, ast.Dict):
        return ()
    pairs = []
    for key, value in zip(params.keys, params.values, strict=True):
        name = _string(key) if key is not None else None
        if name is not None:
            pairs.append((name, _query_text(value)))
    return tuple(pairs)


def _query_text(node):
    """A params value as query text; an unreadable one becomes {?}."""
    value = _literal(node)
    return "{?}" if value is UNKNOWN else str(value)


def _python_body(node):
    """The body kind and value a requests/httpx call sends."""
    payload = _argument(node, "json", None)
    if payload is not None:
        return "json", _literal(payload)
    for name in ("data", "files"):
        payload = _argument(node, name, None)
        if payload is not None:
            value = _literal(payload)
            return ("form", value) if isinstance(value, dict) else ("unparsed", None)
    return "none", None


def _string(node):
    """The text of a string literal or f-string, or None."""
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return node.value
    if isinstance(node, ast.JoinedStr):
        pieces = []
        for value in node.values:
            if isinstance(value, ast.FormattedValue):
                pieces.append("{" + ast.unparse(value.value) + "}")
            else:
                pieces.append(_string(value) or "")
        return "".join(pieces)
    return None


def _literal(node):
    """The JSON-like value of a literal expression, or UNKNOWN."""
    if isinstance(node, ast.Constant):
        if isinstance(node.value, str | int | float | bool) or node.value is None:
            return node.value
        return UNKNOWN
    if isinstance(node, ast.JoinedStr):
        text = _string(node)
        return UNKNOWN if text is None else text
    if isinstance(node, ast.List | ast.Tuple):
        return [_literal(item) for item in node.elts]
    if isinstance(node, ast.Dict):
        values = {}
        for key, item in zip(node.keys, node.values, strict=True):
            name = _string(key) if key is not None else None
            if name is None:
                return UNKNOWN
            values[name] = _literal(item)
        return values
    return UNKNOWN
