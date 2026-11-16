"""Read the JavaScript literal values used by the fetch call parser.

A literal is a string, number, boolean, null, array or object. Anything else (an
identifier, a call, an arithmetic expression, a spread property) is UNKNOWN.
"""

from __future__ import annotations


class _Unknown:
    __slots__ = ()

    def __repr__(self) -> str:
        return "UNKNOWN"

    __str__ = __repr__


UNKNOWN = _Unknown()


class ParseError(ValueError):
    """The text at the current position is not a complete JavaScript literal."""


_SIMPLE_ESCAPES = {
    "0": "\0",
    "b": "\b",
    "f": "\f",
    "n": "\n",
    "r": "\r",
    "t": "\t",
    "v": "\v",
}
_HEX = set("0123456789abcdefABCDEF")


def skip(text: str, index: int = 0) -> int:
    """Skip whitespace and JavaScript // and /* */ comments."""
    i, size = index, len(text)
    while i < size:
        char = text[i]
        if char.isspace():
            i += 1
            continue
        if char == "/" and i + 1 < size:
            following = text[i + 1]
            if following == "/":
                i += 2
                while i < size and text[i] not in "\r\n":
                    i += 1
                continue
            if following == "*":
                end = text.find("*/", i + 2)
                if end < 0:
                    return size
                i = end + 2
                continue
        break
    return i


def _read_escape(text: str, index: int) -> tuple[str, int]:
    """The character(s) after a backslash, and the position after them."""
    size = len(text)
    if index >= size:
        return "", index
    char = text[index]
    if char in _SIMPLE_ESCAPES:
        return _SIMPLE_ESCAPES[char], index + 1
    if char == "\n":
        return "", index + 1
    if char == "\r":
        return "", index + 2 if index + 1 < size and text[index + 1] == "\n" else index + 1
    if char == "x":
        digits = text[index + 1 : index + 3]
        if len(digits) == 2 and all(digit in _HEX for digit in digits):
            return chr(int(digits, 16)), index + 3
        return "x", index + 1
    if char == "u":
        if index + 1 < size and text[index + 1] == "{":
            end = text.find("}", index + 2)
            if end >= 0:
                digits = text[index + 2 : end]
                try:
                    return chr(int(digits, 16)), end + 1
                except ValueError, OverflowError:
                    pass
            return "u", index + 1
        digits = text[index + 1 : index + 5]
        if len(digits) == 4 and all(digit in _HEX for digit in digits):
            return chr(int(digits, 16)), index + 5
        return "u", index + 1
    return char, index + 1


def _read_quoted(text: str, index: int) -> tuple[str, int]:
    quote, i, size = text[index], index + 1, len(text)
    pieces: list[str] = []
    while i < size:
        char = text[i]
        if char == quote:
            return "".join(pieces), i + 1
        if char == "\\":
            piece, i = _read_escape(text, i + 1)
            pieces.append(piece)
        else:
            pieces.append(char)
            i += 1
    raise ParseError("unterminated string")


def _skip_quoted(text: str, index: int) -> int:
    quote, i, size = text[index], index + 1, len(text)
    while i < size:
        char = text[i]
        if char == "\\":
            i += 2
        elif char == quote:
            return i + 1
        else:
            i += 1
    raise ParseError("unterminated string")


def _template_expr_end(text: str, index: int) -> int:
    """Index of the closing brace that ends a ${...} expression."""
    i, size, depth = index, len(text), 1
    while i < size:
        char = text[i]
        if char in "'\"`":
            i = _skip_js_string(text, i)
        elif char == "/" and i + 1 < size and text[i + 1] in "/*":
            i = skip(text, i)
        elif char == "{":
            depth += 1
            i += 1
        elif char == "}":
            depth -= 1
            if depth == 0:
                return i
            i += 1
        else:
            i += 1
    raise ParseError("unterminated template expression")


def _read_template(text: str, index: int) -> tuple[str, int]:
    i, size = index + 1, len(text)
    pieces: list[str] = []
    while i < size:
        char = text[i]
        if char == "`":
            return "".join(pieces), i + 1
        if char == "\\":
            piece, i = _read_escape(text, i + 1)
            pieces.append(piece)
        elif char == "$" and i + 1 < size and text[i + 1] == "{":
            start = i + 2
            end = _template_expr_end(text, start)
            pieces.append("{" + text[start:end].strip() + "}")
            i = end + 1
        else:
            pieces.append(char)
            i += 1
    raise ParseError("unterminated template literal")


def _skip_template(text: str, index: int) -> int:
    i, size = index + 1, len(text)
    while i < size:
        char = text[i]
        if char == "\\":
            i += 2
        elif char == "`":
            return i + 1
        elif char == "$" and i + 1 < size and text[i + 1] == "{":
            i = _template_expr_end(text, i + 2) + 1
        else:
            i += 1
    raise ParseError("unterminated template literal")


def _skip_js_string(text: str, index: int) -> int:
    if text[index] == "`":
        return _skip_template(text, index)
    return _skip_quoted(text, index)


def _read_identifier(text: str, index: int) -> tuple[str, int]:
    i, size = index, len(text)
    if i >= size or not (text[i].isalpha() or text[i] in "_$"):
        raise ParseError("not an identifier")
    i += 1
    while i < size and (text[i].isalnum() or text[i] in "_$"):
        i += 1
    return text[index:i], i


def _read_number(text: str, index: int) -> tuple[int | float, int]:
    start = i = index
    size = len(text)
    if text[i] in "+-":
        i += 1
    if i + 1 < size and text[i] == "0" and text[i + 1] in "xX":
        i += 2
        digits = i
        while i < size and (text[i] in _HEX or text[i] == "_"):
            i += 1
        if i == digits:
            raise ParseError("bad hexadecimal number")
        try:
            return int(text[start:i].replace("_", ""), 16), i
        except ValueError as error:
            raise ParseError("bad hexadecimal number") from error
    if i + 1 < size and text[i] == "0" and text[i + 1] in "bB":
        i += 2
        digits = i
        while i < size and (text[i] in "01_"):
            i += 1
        if i == digits:
            raise ParseError("bad binary number")
        try:
            return int(text[start:i].replace("_", ""), 2), i
        except ValueError as error:
            raise ParseError("bad binary number") from error
    if i + 1 < size and text[i] == "0" and text[i + 1] in "oO":
        i += 2
        digits = i
        while i < size and (text[i] in "01234567_"):
            i += 1
        if i == digits:
            raise ParseError("bad octal number")
        try:
            return int(text[start:i].replace("_", ""), 8), i
        except ValueError as error:
            raise ParseError("bad octal number") from error
    has_digits = False
    while i < size and (text[i].isdigit() or text[i] == "_"):
        has_digits = has_digits or text[i].isdigit()
        i += 1
    is_float = False
    if i < size and text[i] == ".":
        is_float = True
        i += 1
        while i < size and (text[i].isdigit() or text[i] == "_"):
            has_digits = has_digits or text[i].isdigit()
            i += 1
    if i < size and text[i] in "eE":
        is_float = True
        i += 1
        if i < size and text[i] in "+-":
            i += 1
        exponent_digits = False
        while i < size and (text[i].isdigit() or text[i] == "_"):
            exponent_digits = exponent_digits or text[i].isdigit()
            i += 1
        if not exponent_digits:
            raise ParseError("bad exponent")
    if not has_digits:
        raise ParseError("bad number")
    token = text[start:i].replace("_", "")
    try:
        return (float(token) if is_float else int(token)), i
    except ValueError as error:
        raise ParseError("bad number") from error


def _expression_end(text: str, start: int, stops: tuple[str, ...]) -> int:
    """End of an expression at top level, just before a stop character."""
    i, size, depth = start, len(text), 0
    while i < size:
        i = skip(text, i)
        if i >= size:
            break
        char = text[i]
        if char in "'\"`":
            i = _skip_js_string(text, i)
        elif char in "([{":
            depth += 1
            i += 1
        elif char in ")]}":
            if depth == 0 and char in stops:
                return i
            depth = max(0, depth - 1)
            i += 1
        elif char == "," and depth == 0 and char in stops:
            return i
        else:
            i += 1
    return i


def _read_array(text: str, index: int) -> tuple[list, int]:
    i, size = index + 1, len(text)
    values: list = []
    while True:
        i = skip(text, i)
        if i >= size:
            raise ParseError("unterminated array")
        if text[i] == "]":
            return values, i + 1
        end = _expression_end(text, i, (",", "]"))
        if end == i:
            raise ParseError("empty array item")
        values.append(parse(text[i:end]))
        i = skip(text, end)
        if i < size and text[i] == ",":
            i += 1
        elif i < size and text[i] == "]":
            return values, i + 1
        else:
            raise ParseError("bad array")


def _read_object(text: str, index: int) -> tuple[object, int, dict[str, tuple[int, int]]]:
    i, size = index + 1, len(text)
    values: dict[str, object] = {}
    spans: dict[str, tuple[int, int]] = {}
    spread = False
    while True:
        i = skip(text, i)
        if i >= size:
            raise ParseError("unterminated object")
        if text[i] == "}":
            return (UNKNOWN if spread else values), i + 1, spans
        if text.startswith("...", i):
            spread = True
            i = skip(text, _expression_end(text, i + 3, (",", "}")))
            if i < size and text[i] == ",":
                i += 1
                continue
            if i < size and text[i] == "}":
                return UNKNOWN, i + 1, spans
            raise ParseError("bad spread")
        key_start = i
        char = text[i]
        if char in "'\"":
            key, key_end = _read_quoted(text, i)
        elif char == "`":
            key, key_end = _read_template(text, i)
        elif char.isdigit() or (char in "+-" and i + 1 < size and (text[i + 1].isdigit() or text[i + 1] == ".")):
            key_number, key_end = _read_number(text, i)
            key = str(key_number)
        elif char.isalpha() or char in "_$":
            key, key_end = _read_identifier(text, i)
        else:
            raise ParseError("bad object key")
        i = skip(text, key_end)
        if i < size and text[i] == ":":
            value_start = skip(text, i + 1)
            value_end = _expression_end(text, value_start, (",", "}"))
            value = UNKNOWN if value_end == value_start else parse(text[value_start:value_end])
            values[str(key)] = value
            spans[str(key)] = (value_start, value_end)
            i = value_end
        else:
            values[str(key)] = UNKNOWN
            spans[str(key)] = (key_start, key_end)
            i = key_end
        i = skip(text, i)
        if i < size and text[i] == ",":
            i += 1
        elif i < size and text[i] == "}":
            return (UNKNOWN if spread else values), i + 1, spans
        else:
            raise ParseError("bad object")


def _read_value(text: str, index: int = 0) -> tuple[object, int]:
    i = skip(text, index)
    if i >= len(text):
        return UNKNOWN, i
    char = text[i]
    try:
        if char in "'\"":
            value, i = _read_quoted(text, i)
        elif char == "`":
            value, i = _read_template(text, i)
        elif char == "[":
            value, i = _read_array(text, i)
        elif char == "{":
            value, i, _spans = _read_object(text, i)
        elif char in "+-." or char.isdigit():
            value, i = _read_number(text, i)
        elif char.isalpha() or char in "_$":
            word, i = _read_identifier(text, i)
            if word == "true":
                value = True
            elif word == "false":
                value = False
            elif word == "null":
                value = None
            else:
                return UNKNOWN, i
        else:
            return UNKNOWN, i
    except ParseError:
        return UNKNOWN, index
    following = skip(text, i)
    if following < len(text) and text[following] not in ",)]}":
        return UNKNOWN, i
    return value, i


def value_at(text: str, index: int = 0) -> tuple[object, int]:
    """Read a literal starting at index, returning (value or UNKNOWN, end)."""
    return _read_value(text, index)


literal_at = value_at
read_value = value_at


def parse(text: str, index: int = 0) -> object:
    """Parse all of text (from index) as one JavaScript literal, or UNKNOWN."""
    value, end = _read_value(text, index)
    if skip(text, end) < len(text):
        return UNKNOWN
    return value


def parse_literal(text: str, index: int = 0) -> object:
    """A value-only alias for parse."""
    return parse(text, index)


parse_value = parse_literal


def read_object(text: str, index: int = 0) -> tuple[object, int]:
    """Read an object literal at index, returning (value or UNKNOWN, end)."""
    i = skip(text, index)
    if i >= len(text) or text[i] != "{":
        return UNKNOWN, i
    try:
        value, end, _spans = _read_object(text, i)
        return value, end
    except ParseError:
        return UNKNOWN, i


def read_object_with_spans(text: str, index: int = 0) -> tuple[object, int, dict[str, tuple[int, int]]]:
    """Read an object, also returning each property's raw value span."""
    i = skip(text, index)
    if i >= len(text) or text[i] != "{":
        return UNKNOWN, i, {}
    try:
        return _read_object(text, i)
    except ParseError:
        return UNKNOWN, i, {}


object_spans = read_object_with_spans


def property(obj: object, name: str, default: object = UNKNOWN) -> object:
    """A dict property, or default when obj is not a dict or lacks the key."""
    if isinstance(obj, dict) and name in obj:
        return obj[name]
    return default


get_property = property


def method(obj: object, default: object = "GET") -> object:
    """The method property of a parsed options object, or default."""
    return property(obj, "method", default)


def body(obj: object) -> object:
    """The body property of a parsed options object, or UNKNOWN."""
    return property(obj, "body")


def property_source(text: str, index: int, name: str) -> str | None:
    """The raw value expression for one property of an object literal, if present."""
    _value, _end, spans = read_object_with_spans(text, index)
    span = spans.get(name)
    if span is None:
        return None
    return text[span[0] : span[1]].strip()


object_property_source = property_source
