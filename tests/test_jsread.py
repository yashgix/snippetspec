import unittest

from snippetcheck.jsread import (
    UNKNOWN,
    body,
    literal_at,
    method,
    parse,
    property,
    property_source,
    read_object,
    read_object_with_spans,
    skip,
    value_at,
)


class UnknownTest(unittest.TestCase):
    def test_unknown_is_one_shared_object_with_a_readable_repr(self):
        self.assertIs(UNKNOWN, UNKNOWN)
        self.assertEqual(repr(UNKNOWN), "UNKNOWN")
        self.assertNotEqual(UNKNOWN, object())


class SkipTest(unittest.TestCase):
    def test_skips_whitespace_and_comments(self):
        self.assertEqual(skip("  // c\n\tx", 0), 8)
        self.assertEqual(skip("/* a\n b */ value", 0), 11)
        self.assertEqual(skip("/* never closed", 0), len("/* never closed"))

    def test_division_is_not_a_comment(self):
        self.assertEqual(skip("a / b", 1), 2)


class StringTest(unittest.TestCase):
    def test_single_and_double_quotes(self):
        self.assertEqual(parse('"hello"'), "hello")
        self.assertEqual(parse("'hello'"), "hello")

    def test_escapes(self):
        self.assertEqual(parse('"a\\n b\\t c"'), "a\n b\t c")
        self.assertEqual(parse('"\\u0041\\x42"'), "AB")
        self.assertEqual(parse('"\\q"'), "q")

    def test_template_substitutions(self):
        self.assertEqual(parse("`a${name}b`"), "a{name}b")
        self.assertEqual(parse("`a${ {b: 1} }c`"), "a{{b: 1}}c")
        self.assertEqual(parse("`a\\${name}`"), "a${name}")

    def test_unterminated_string_is_unknown(self):
        self.assertIs(parse('"abc'), UNKNOWN)
        self.assertIs(parse("`abc"), UNKNOWN)


class NumberTest(unittest.TestCase):
    def test_integers_and_floats(self):
        self.assertEqual(parse("42"), 42)
        self.assertEqual(parse("-42"), -42)
        self.assertEqual(parse("1_000"), 1000)
        self.assertEqual(parse("1.5"), 1.5)
        self.assertEqual(parse(".5"), 0.5)
        self.assertEqual(parse("1e3"), 1000.0)
        self.assertEqual(parse("1E-3"), 0.001)
        self.assertEqual(parse("0x10"), 16)
        self.assertEqual(parse("0b101"), 5)
        self.assertEqual(parse("0o17"), 15)

    def test_bad_numbers_are_unknown(self):
        self.assertIs(parse("1e"), UNKNOWN)
        self.assertIs(parse("0x"), UNKNOWN)
        self.assertIs(parse("-"), UNKNOWN)


class LiteralTest(unittest.TestCase):
    def test_booleans_and_null(self):
        self.assertIs(parse("true"), True)
        self.assertIs(parse("false"), False)
        self.assertIsNone(parse("null"))

    def test_arrays(self):
        self.assertEqual(parse('[1, "two", [true, null]]'), [1, "two", [True, None]])
        self.assertEqual(parse("[]"), [])
        self.assertEqual(parse("[1,]"), [1])

    def test_objects(self):
        self.assertEqual(parse('{a: 1, "b": "x", 3: false}'), {"a": 1, "b": "x", "3": False})
        self.assertEqual(parse("{}"), {})

    def test_shorthand_property_is_unknown(self):
        self.assertEqual(parse("{a}"), {"a": UNKNOWN})

    def test_spread_makes_the_whole_object_unknown(self):
        self.assertIs(parse("{a: 1, ...b}"), UNKNOWN)

    def test_comments_inside_literals(self):
        self.assertEqual(parse("/* x */ {a: // y\n 1}"), {"a": 1})

    def test_non_literals_are_unknown(self):
        self.assertIs(parse("foo"), UNKNOWN)
        self.assertIs(parse('"a" + b'), UNKNOWN)
        self.assertIs(parse("1 + 2"), UNKNOWN)
        self.assertIs(parse("some.call"), UNKNOWN)
        self.assertIs(parse(""), UNKNOWN)

    def test_trailing_expression_makes_a_literal_unknown(self):
        self.assertIs(parse('{"a": 1}.b'), UNKNOWN)

    def test_unterminated_objects_are_unknown(self):
        self.assertIs(parse("{a: 1"), UNKNOWN)


class PositionTest(unittest.TestCase):
    def test_value_at_returns_the_end_position(self):
        value, end = value_at('xx "a", yy', 3)
        self.assertEqual(value, "a")
        self.assertEqual(end, 6)

    def test_literal_followed_by_an_operator_is_not_a_literal(self):
        value, end = value_at('xx "a" + b', 3)
        self.assertIs(value, UNKNOWN)
        self.assertEqual(end, 6)

    def test_literal_at_is_an_alias(self):
        self.assertEqual(literal_at("[1, 2]", 0), ([1, 2], 6))

    def test_non_literal_value_ends_after_the_token(self):
        value, end = value_at("foo bar", 0)
        self.assertIs(value, UNKNOWN)
        self.assertEqual(end, 3)


class ObjectHelpersTest(unittest.TestCase):
    def setUp(self):
        self.text = '{method: "POST", body: JSON.stringify({a: 1})}'

    def test_read_object(self):
        value, end = read_object(self.text)
        self.assertEqual(value["method"], "POST")
        self.assertIs(value["body"], UNKNOWN)
        self.assertEqual(end, len(self.text))

    def test_read_object_with_spans(self):
        value, end, spans = read_object_with_spans(self.text)
        self.assertEqual(value["method"], "POST")
        self.assertEqual(end, len(self.text))
        start, stop = spans["body"]
        self.assertEqual(self.text[start:stop], "JSON.stringify({a: 1})")

    def test_property_source(self):
        self.assertEqual(property_source(self.text, 0, "method"), '"POST"')
        self.assertEqual(property_source(self.text, 0, "body"), "JSON.stringify({a: 1})")
        self.assertIsNone(property_source(self.text, 0, "missing"))

    def test_property_method_and_body(self):
        options = parse('{method: "PATCH", body: {a: 1}}')
        self.assertEqual(property(options, "method"), "PATCH")
        self.assertEqual(method(options), "PATCH")
        self.assertEqual(body(options), {"a": 1})
        self.assertIs(property(options, "missing"), UNKNOWN)
        self.assertEqual(method({}), "GET")
        self.assertIs(body({}), UNKNOWN)


if __name__ == "__main__":
    unittest.main()
