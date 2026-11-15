import unittest
from urllib.parse import parse_qsl, urlsplit

from snippetcheck.calls import Call
from snippetcheck.check import check_call, is_placeholder, validate
from snippetcheck.jsread import UNKNOWN
from snippetcheck.spec import operations


def spec(paths=None, schemas=None):
    return {"paths": paths or {}, "components": {"schemas": schemas or {}}}


def call(method="GET", url="https://api.supermemory.ai/x", query=(), body_kind="none", body=None, media=None):
    query = tuple(query) or tuple(parse_qsl(urlsplit(url).query, keep_blank_values=True))
    return Call("curl", method, url, query, body_kind, body, media)


def check(specs, method="GET", url="https://api.supermemory.ai/x", query=(), body_kind="none", body=None, media=None):
    return check_call(specs, operations(list(specs.items())), call(method, url, query, body_kind, body, media))


def item_schemas():
    return {
        "Item": {
            "type": "object",
            "required": ["name"],
            "properties": {"name": {"type": "string"}, "size": {"type": "integer"}},
        }
    }


def pinned_paths():
    return {
        "/items": {
            "get": {
                "parameters": [
                    {"name": "limit", "in": "query", "required": True, "schema": {"type": "integer"}},
                    {"name": "mode", "in": "query", "schema": {"enum": ["fast", "slow"]}},
                ]
            },
            "post": {
                "requestBody": {
                    "required": True,
                    "content": {"application/json": {"schema": {"$ref": "#/components/schemas/Item"}}},
                }
            },
        },
        "/items/{id}": {
            "get": {"parameters": [{"name": "id", "in": "path", "required": True, "schema": {"type": "integer"}}]},
        },
        "/uploads": {
            "post": {
                "requestBody": {
                    "content": {
                        "multipart/form-data": {
                            "schema": {
                                "type": "object",
                                "required": ["file"],
                                "properties": {"file": {"type": "string"}, "note": {"type": "string"}},
                            }
                        }
                    }
                }
            }
        },
        "/plain": {"get": {}},
        "/sink": {"post": {}},
    }


def pinned_specs():
    return {"v5": spec(pinned_paths(), item_schemas())}


class TypeTest(unittest.TestCase):
    def test_string(self):
        self.assertEqual(validate({}, {"type": "string"}, "a"), [])
        self.assertEqual(validate({}, {"type": "string"}, 1), [("type", "$")])

    def test_integer_rejects_booleans(self):
        self.assertEqual(validate({}, {"type": "integer"}, 3), [])
        self.assertEqual(validate({}, {"type": "integer"}, True), [("type", "$")])

    def test_number_accepts_integers_and_floats(self):
        self.assertEqual(validate({}, {"type": "number"}, 1), [])
        self.assertEqual(validate({}, {"type": "number"}, 1.5), [])
        self.assertEqual(validate({}, {"type": "number"}, False), [("type", "$")])

    def test_boolean(self):
        self.assertEqual(validate({}, {"type": "boolean"}, True), [])
        self.assertEqual(validate({}, {"type": "boolean"}, "true"), [("type", "$")])

    def test_null(self):
        self.assertEqual(validate({}, {"type": "null"}, None), [])
        self.assertEqual(validate({}, {"type": "null"}, 0), [("type", "$")])

    def test_array_and_object(self):
        self.assertEqual(validate({}, {"type": "array"}, [1]), [])
        self.assertEqual(validate({}, {"type": "array"}, {}), [("type", "$")])
        self.assertEqual(validate({}, {"type": "object"}, {}), [])
        self.assertEqual(validate({}, {"type": "object"}, []), [("type", "$")])

    def test_type_list(self):
        schema = {"type": ["string", "null"]}
        self.assertEqual(validate({}, schema, None), [])
        self.assertEqual(validate({}, schema, "x"), [])
        self.assertEqual(validate({}, schema, 1), [("type", "$")])

    def test_missing_type_fits_everything(self):
        self.assertEqual(validate({}, {}, 1), [])
        self.assertEqual(validate({}, {}, None), [])

    def test_type_mismatch_hides_deeper_problems(self):
        schema = {"type": "object", "required": ["a"], "properties": {"a": {"type": "string"}}}
        self.assertEqual(validate({}, schema, []), [("type", "$")])


class EnumTest(unittest.TestCase):
    def test_enum(self):
        schema = {"enum": ["a", "b"]}
        self.assertEqual(validate({}, schema, "a"), [])
        self.assertEqual(validate({}, schema, "c"), [("enum", "$")])

    def test_const(self):
        self.assertEqual(validate({}, {"const": 3}, 3), [])
        self.assertEqual(validate({}, {"const": 3}, 4), [("enum", "$")])

    def test_enum_reports_the_nested_where(self):
        schema = {"type": "object", "properties": {"state": {"enum": ["on"]}}}
        self.assertEqual(validate({}, schema, {"state": "off"}), [("enum", "$.state")])


class ObjectTest(unittest.TestCase):
    schema = {
        "type": "object",
        "required": ["a", "b"],
        "properties": {"a": {"type": "string"}, "b": {"type": "integer"}},
        "additionalProperties": False,
    }

    def test_missing_fields_in_required_order(self):
        self.assertEqual(validate({}, self.schema, {}), [("missing_field", "$.a"), ("missing_field", "$.b")])

    def test_undocumented_field(self):
        self.assertEqual(validate({}, self.schema, {"a": "x", "b": 1, "c": 2}), [("undocumented_field", "$.c")])

    def test_additional_properties_absent_reports_undocumented(self):
        schema = {"type": "object", "properties": {"a": {"type": "string"}}}
        self.assertEqual(validate({}, schema, {"a": "x", "b": 1}), [("undocumented_field", "$.b")])

    def test_additional_properties_true_allows_extra_keys(self):
        schema = {"type": "object", "properties": {}, "additionalProperties": True}
        self.assertEqual(validate({}, schema, {"c": 2}), [])

    def test_property_problems_come_in_value_order(self):
        self.assertEqual(validate({}, self.schema, {"b": "no", "a": 1}), [("type", "$.b"), ("type", "$.a")])

    def test_dict_without_properties_is_not_checked(self):
        self.assertEqual(validate({}, {"type": "object"}, {"anything": 1}), [])

    def test_array_items(self):
        schema = {"type": "array", "items": {"type": "integer"}}
        self.assertEqual(validate({}, schema, [1, "x"]), [("type", "$[1]")])

    def test_nested_where(self):
        schema = {
            "type": "object",
            "properties": {
                "rows": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "required": ["id"],
                        "properties": {"id": {"type": "string"}},
                    },
                }
            },
        }
        self.assertEqual(validate({}, schema, {"rows": [{"id": 1}]}), [("type", "$.rows[0].id")])


class ChoiceTest(unittest.TestCase):
    def test_any_of_accepts_a_fitting_branch(self):
        schema = {"anyOf": [{"type": "string"}, {"type": "integer"}]}
        self.assertEqual(validate({}, schema, 3), [])
        self.assertEqual(validate({}, schema, "x"), [])

    def test_any_of_without_a_fitting_branch_is_a_type_problem(self):
        schema = {"anyOf": [{"type": "string"}, {"type": "integer"}]}
        self.assertEqual(validate({}, schema, []), [("type", "$")])

    def test_one_of_is_read_when_any_of_is_absent(self):
        schema = {"oneOf": [{"type": "string"}]}
        self.assertEqual(validate({}, schema, "x"), [])
        self.assertEqual(validate({}, schema, 1), [("type", "$")])

    def test_any_of_wins_over_one_of(self):
        schema = {"anyOf": [{"type": "string"}], "oneOf": [{"type": "integer"}]}
        self.assertEqual(validate({}, schema, "x"), [])
        self.assertEqual(validate({}, schema, 1), [("type", "$")])

    def test_fewest_problems_wins(self):
        schema = {
            "anyOf": [
                {"type": "object", "required": ["a", "b"], "properties": {}},
                {"type": "object", "required": ["a"], "properties": {}},
            ]
        }
        self.assertEqual(validate({}, schema, {}), [("missing_field", "$.a")])

    def test_ties_go_to_the_earliest_branch(self):
        schema = {
            "anyOf": [
                {"type": "object", "required": ["a"], "properties": {}},
                {"type": "object", "required": ["b"], "properties": {}},
            ]
        }
        self.assertEqual(validate({}, schema, {}), [("missing_field", "$.a")])

    def test_branches_are_dereferenced(self):
        specs = {"components": {"schemas": {"Text": {"type": "string"}}}}
        schema = {"anyOf": [{"$ref": "#/components/schemas/Text"}]}
        self.assertEqual(validate(specs, schema, "x"), [])
        self.assertEqual(validate(specs, schema, 1), [("type", "$")])


class PlaceholderTest(unittest.TestCase):
    def test_unknown_is_a_placeholder(self):
        self.assertTrue(is_placeholder(UNKNOWN))
        self.assertEqual(validate({}, {"type": "integer"}, UNKNOWN), [])

    def test_special_characters_make_a_placeholder(self):
        for value in ("$ID", "{id}", "<id>", "a>b"):
            with self.subTest(value=value):
                self.assertTrue(is_placeholder(value))
                self.assertEqual(validate({}, {"type": "integer"}, value), [])

    def test_plain_text_is_not_a_placeholder(self):
        self.assertFalse(is_placeholder("plain"))
        self.assertFalse(is_placeholder(3))

    def test_placeholder_inside_a_body_passes(self):
        schema = {"type": "object", "required": ["content"], "properties": {"content": {"type": "string"}}}
        self.assertEqual(validate({}, schema, {"content": "${CONTENT}"}), [])


class MatchTest(unittest.TestCase):
    def test_unknown_path(self):
        result = check(pinned_specs(), url="https://api.supermemory.ai/nope")
        self.assertEqual(result, {"operation": None, "problems": [("unknown_path", "/nope")]})

    def test_method_not_allowed(self):
        result = check(pinned_specs(), method="PATCH", url="https://api.supermemory.ai/plain")
        self.assertEqual(result, {"operation": None, "problems": [("method_not_allowed", "GET")]})

    def test_operation_name_includes_the_spec(self):
        result = check(pinned_specs(), url="https://api.supermemory.ai/plain")
        self.assertEqual(result, {"operation": "v5:GET /plain", "problems": []})

    def test_problems_are_code_and_where_tuples(self):
        result = check(pinned_specs(), url="https://api.supermemory.ai/items?limit=x")
        self.assertIsInstance(result["problems"], list)
        self.assertIsInstance(result["problems"][0], tuple)


class PathTest(unittest.TestCase):
    def test_path_value_is_checked(self):
        result = check(pinned_specs(), url="https://api.supermemory.ai/items/abc")
        self.assertEqual(result["problems"], [("type", "path:id")])

    def test_path_value_passes(self):
        self.assertEqual(check(pinned_specs(), url="https://api.supermemory.ai/items/7")["problems"], [])

    def test_path_value_is_url_decoded(self):
        self.assertEqual(check(pinned_specs(), url="https://api.supermemory.ai/items/%37")["problems"], [])

    def test_placeholder_path_segment_skips_checks(self):
        self.assertEqual(check(pinned_specs(), url="https://api.supermemory.ai/items/{itemId}")["problems"], [])

    def test_undeclared_path_parameter_is_not_checked(self):
        paths = {"/x/{id}": {"get": {}}}
        self.assertEqual(check({"v5": spec(paths)}, url="https://api.supermemory.ai/x/abc")["problems"], [])


class MediaTypeTest(unittest.TestCase):
    URL = "https://api.supermemory.ai/items"

    def test_explicit_text_plain_to_a_json_operation_is_a_content_type_problem(self):
        result = check(pinned_specs(), "POST", self.URL, body_kind="json", body={"name": "n"}, media="text/plain")
        self.assertEqual(result["problems"], [("content_type", "body:text/plain")])

    def test_explicit_json_media_type_is_validated_as_json(self):
        result = check(pinned_specs(), "POST", self.URL, body_kind="json", body={"size": 1}, media="application/json")
        self.assertEqual(result["problems"], [("missing_field", "$.name")])

    def test_json_suffix_media_type_counts_as_json(self):
        result = check(
            pinned_specs(), "POST", self.URL, body_kind="json", body={"name": "n"}, media="application/vnd.x+json"
        )
        self.assertEqual(result["problems"], [])


class QueryTest(unittest.TestCase):
    def test_missing_required_parameter(self):
        result = check(pinned_specs(), url="https://api.supermemory.ai/items")
        self.assertEqual(result["problems"], [("missing_param", "query:limit")])

    def test_undocumented_parameter(self):
        result = check(pinned_specs(), url="https://api.supermemory.ai/items?limit=1&extra=2")
        self.assertEqual(result["problems"], [("undocumented_param", "query:extra")])

    def test_parameter_value_is_checked(self):
        result = check(pinned_specs(), url="https://api.supermemory.ai/items?limit=many")
        self.assertEqual(result["problems"], [("type", "query:limit")])

    def test_enum_parameter(self):
        result = check(pinned_specs(), url="https://api.supermemory.ai/items?limit=1&mode=medium")
        self.assertEqual(result["problems"], [("enum", "query:mode")])

    def test_order_is_missing_then_documented(self):
        result = check(pinned_specs(), url="https://api.supermemory.ai/items?extra=1")
        self.assertEqual(result["problems"], [("missing_param", "query:limit"), ("undocumented_param", "query:extra")])

    def test_pairs_may_be_passed_explicitly(self):
        result = check(pinned_specs(), url="https://api.supermemory.ai/items", query=(("limit", "5"),))
        self.assertEqual(result["problems"], [])

    def test_path_problems_come_before_query_problems(self):
        result = check(pinned_specs(), url="https://api.supermemory.ai/items/abc?limit=1")
        self.assertEqual(result["problems"], [("type", "path:id"), ("undocumented_param", "query:limit")])


class BodyTest(unittest.TestCase):
    def test_missing_body_when_required(self):
        result = check(pinned_specs(), method="POST", url="https://api.supermemory.ai/items")
        self.assertEqual(result["problems"], [("missing_body", "body")])

    def test_no_body_when_not_required(self):
        self.assertEqual(check(pinned_specs(), method="POST", url="https://api.supermemory.ai/uploads")["problems"], [])

    def test_empty_json_body_to_a_bodyless_operation_is_nothing(self):
        result = check(pinned_specs(), method="POST", url="https://api.supermemory.ai/sink", body_kind="json", body={})
        self.assertEqual(result["problems"], [])

    def test_json_body_to_a_bodyless_operation_is_unexpected(self):
        result = check(
            pinned_specs(), method="POST", url="https://api.supermemory.ai/sink", body_kind="json", body={"a": 1}
        )
        self.assertEqual(result["problems"], [("unexpected_body", "body")])

    def test_form_body_to_a_bodyless_operation_is_unexpected(self):
        result = check(
            pinned_specs(), method="POST", url="https://api.supermemory.ai/sink", body_kind="form", body={"a": "1"}
        )
        self.assertEqual(result["problems"], [("unexpected_body", "body")])

    def test_json_body_is_validated(self):
        result = check(
            pinned_specs(), method="POST", url="https://api.supermemory.ai/items", body_kind="json", body={"size": 3}
        )
        self.assertEqual(result["problems"], [("missing_field", "$.name")])

    def test_json_body_value_is_checked(self):
        result = check(
            pinned_specs(),
            method="POST",
            url="https://api.supermemory.ai/items",
            body_kind="json",
            body={"name": "x", "size": "big"},
        )
        self.assertEqual(result["problems"], [("type", "$.size")])

    def test_json_body_to_a_form_operation_is_a_content_type_problem(self):
        result = check(
            pinned_specs(),
            method="POST",
            url="https://api.supermemory.ai/uploads",
            body_kind="json",
            body={"file": "x"},
        )
        self.assertEqual(result["problems"], [("content_type", "body:json")])

    def test_form_body_to_a_json_operation_is_a_content_type_problem(self):
        result = check(
            pinned_specs(), method="POST", url="https://api.supermemory.ai/items", body_kind="form", body={"name": "x"}
        )
        self.assertEqual(result["problems"], [("content_type", "body:form")])

    def test_form_body_checks_names_only(self):
        result = check(
            pinned_specs(),
            method="POST",
            url="https://api.supermemory.ai/uploads",
            body_kind="form",
            body={"note": "x"},
        )
        self.assertEqual(result["problems"], [("missing_field", "$.file")])

    def test_form_body_reports_undocumented_field(self):
        result = check(
            pinned_specs(),
            method="POST",
            url="https://api.supermemory.ai/uploads",
            body_kind="form",
            body={"file": "x", "extra": "y"},
        )
        self.assertEqual(result["problems"], [("undocumented_field", "$.extra")])

    def test_form_body_accepts_unknown_field_values(self):
        result = check(
            pinned_specs(),
            method="POST",
            url="https://api.supermemory.ai/uploads",
            body_kind="form",
            body={"file": UNKNOWN},
        )
        self.assertEqual(result["problems"], [])

    def test_unparsed_body_needs_json(self):
        result = check(pinned_specs(), method="POST", url="https://api.supermemory.ai/uploads", body_kind="unparsed")
        self.assertEqual(result["problems"], [("content_type", "body:json")])

    def test_unparsed_body_to_a_json_operation_passes(self):
        self.assertEqual(
            check(pinned_specs(), method="POST", url="https://api.supermemory.ai/items", body_kind="unparsed")[
                "problems"
            ],
            [],
        )


class ParameterTextTest(unittest.TestCase):
    def spec_for(self, schema):
        paths = {"/x": {"get": {"parameters": [{"name": "v", "in": "query", "schema": schema}]}}}
        return {"v5": spec(paths)}

    def problems(self, schema, url):
        return check(self.spec_for(schema), url=url)["problems"]

    def test_boolean(self):
        schema = {"type": "boolean"}
        self.assertEqual(self.problems(schema, "https://api.supermemory.ai/x?v=true"), [])
        self.assertEqual(self.problems(schema, "https://api.supermemory.ai/x?v=yes"), [("type", "query:v")])

    def test_number(self):
        schema = {"type": "number"}
        self.assertEqual(self.problems(schema, "https://api.supermemory.ai/x?v=1.5"), [])
        self.assertEqual(self.problems(schema, "https://api.supermemory.ai/x?v=1e5"), [("type", "query:v")])

    def test_array_checks_its_items(self):
        schema = {"type": "array", "items": {"type": "integer"}}
        self.assertEqual(self.problems(schema, "https://api.supermemory.ai/x?v=12"), [])
        self.assertEqual(self.problems(schema, "https://api.supermemory.ai/x?v=abc"), [("type", "query:v")])

    def test_array_without_items_passes(self):
        self.assertEqual(self.problems({"type": "array"}, "https://api.supermemory.ai/x?v=abc"), [])

    def test_any_of_branches(self):
        schema = {"anyOf": [{"type": "integer"}, {"enum": ["all"]}]}
        self.assertEqual(self.problems(schema, "https://api.supermemory.ai/x?v=all"), [])
        self.assertEqual(self.problems(schema, "https://api.supermemory.ai/x?v=z"), [("type", "query:v")])

    def test_const_is_compared_as_text(self):
        schema = {"const": 2}
        self.assertEqual(self.problems(schema, "https://api.supermemory.ai/x?v=2"), [])
        self.assertEqual(self.problems(schema, "https://api.supermemory.ai/x?v=3"), [("enum", "query:v")])

    def test_placeholder_passes(self):
        self.assertEqual(self.problems({"type": "integer"}, "https://api.supermemory.ai/x?v=${N}"), [])

    def test_type_list_passes_on_any_member(self):
        schema = {"type": ["integer", "boolean"]}
        self.assertEqual(self.problems(schema, "https://api.supermemory.ai/x?v=true"), [])
        self.assertEqual(self.problems(schema, "https://api.supermemory.ai/x?v=z"), [("type", "query:v")])

    def test_parameter_schema_ref(self):
        paths = {
            "/x": {
                "get": {"parameters": [{"name": "v", "in": "query", "schema": {"$ref": "#/components/schemas/Count"}}]}
            }
        }
        specs = {"v5": spec(paths, {"Count": {"type": "integer"}})}
        self.assertEqual(check(specs, url="https://api.supermemory.ai/x?v=abc")["problems"], [("type", "query:v")])


if __name__ == "__main__":
    unittest.main()
