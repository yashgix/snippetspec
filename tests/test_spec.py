import unittest
from dataclasses import FrozenInstanceError

from snippetspec.spec import Operation, body_schemas, deref, match, operations, params, segments


def spec(paths, schemas=None):
    return {"paths": paths, "components": {"schemas": schemas or {}}}


def operation(detail=None, method="GET", template="/x", name="v5"):
    return Operation(name, method, template, detail or {})


def lookup(specs, method, path):
    return match(operations(specs), method, path)


class OperationTest(unittest.TestCase):
    def test_name_is_method_and_template(self):
        op = operation(method="POST", template="/ns/{namespace}/document")
        self.assertEqual(op.name, "POST /ns/{namespace}/document")

    def test_fields_are_kept(self):
        detail = {"summary": "Add a document"}
        op = Operation("v4", "GET", "/a", detail)
        self.assertEqual((op.spec, op.method, op.template, op.op), ("v4", "GET", "/a", detail))

    def test_operation_is_frozen(self):
        op = operation()
        with self.assertRaises(FrozenInstanceError):
            op.method = "POST"


class OperationsTest(unittest.TestCase):
    def test_specs_paths_and_methods_follow_file_order(self):
        paths = {
            "/a": {"get": {"summary": "a"}, "head": {"summary": "head"}, "parameters": []},
            "/b": {"delete": {"summary": "d"}, "post": {"summary": "p"}},
        }
        specs = [("v4", spec(paths)), ("v5", spec({"/c": {"patch": {}, "put": {}, "options": {}}}))]

        found = operations(specs)

        self.assertEqual([op.name for op in found], ["GET /a", "DELETE /b", "POST /b", "PATCH /c", "PUT /c"])
        self.assertEqual([op.spec for op in found], ["v4", "v4", "v4", "v5", "v5"])
        self.assertEqual(found[0].op, {"summary": "a"})

    def test_paths_that_are_not_operations_are_skipped(self):
        specs = [("v5", {"paths": {"/a": {"summary": "not an operation"}, "/b": {"get": {"x": 1}}}})]
        self.assertEqual([op.name for op in operations(specs)], ["GET /b"])

    def test_a_spec_without_paths_has_no_operations(self):
        self.assertEqual(operations([("v5", {})]), [])


class SegmentsTest(unittest.TestCase):
    def test_segments_drop_empty_parts(self):
        self.assertEqual(segments("/a/b/c"), ["a", "b", "c"])
        self.assertEqual(segments("a/b/"), ["a", "b"])
        self.assertEqual(segments("/a//b"), ["a", "b"])
        self.assertEqual(segments("/"), [])
        self.assertEqual(segments(""), [])


class MatchTest(unittest.TestCase):
    def setUp(self):
        paths = {
            "/ns/{namespace}/search": {"post": {"summary": "search"}},
            "/namespaces": {"get": {"summary": "list"}},
        }
        self.specs = [("v5", spec(paths))]

    def test_template_fits_any_segment(self):
        found, problem = lookup(self.specs, "POST", "/ns/user_1/search")
        self.assertIsNone(problem)
        self.assertEqual(found.name, "POST /ns/{namespace}/search")
        self.assertEqual(found.op["summary"], "search")

    def test_exact_path(self):
        found, problem = lookup(self.specs, "GET", "/namespaces")
        self.assertIsNone(problem)
        self.assertEqual(found.name, "GET /namespaces")

    def test_trailing_slash_is_ignored(self):
        found, problem = lookup(self.specs, "GET", "/namespaces/")
        self.assertIsNone(problem)
        self.assertEqual(found.name, "GET /namespaces")

    def test_unknown_path_reports_the_path_as_given(self):
        found, problem = lookup(self.specs, "GET", "/v3//documents/")
        self.assertIsNone(found)
        self.assertEqual(problem, ("unknown_path", "/v3//documents/"))

    def test_extra_segment_does_not_fit(self):
        found, problem = lookup(self.specs, "POST", "/ns/user_1/search/extra")
        self.assertIsNone(found)
        self.assertEqual(problem, ("unknown_path", "/ns/user_1/search/extra"))

    def test_method_not_allowed_lists_the_distinct_methods_sorted(self):
        paths = {"/a/{id}": {"patch": {}, "get": {}, "delete": {}}}
        found, problem = lookup([("v5", spec(paths))], "POST", "/a/1")
        self.assertIsNone(found)
        self.assertEqual(problem, ("method_not_allowed", "DELETE,GET,PATCH"))

    def test_method_comparison_is_case_insensitive(self):
        found, problem = lookup(self.specs, "get", "/namespaces")
        self.assertIsNone(problem)
        self.assertEqual(found.method, "GET")

    def test_most_literal_template_wins(self):
        paths = {
            "/a/{id}": {"get": {"summary": "template"}},
            "/a/special": {"get": {"summary": "literal"}},
        }
        found, _ = lookup([("v5", spec(paths))], "GET", "/a/special")
        self.assertEqual(found.op["summary"], "literal")

    def test_literal_wins_even_when_it_comes_first(self):
        paths = {
            "/a/special": {"get": {"summary": "literal"}},
            "/a/{id}": {"get": {"summary": "template"}},
        }
        found, _ = lookup([("v5", spec(paths))], "GET", "/a/special")
        self.assertEqual(found.op["summary"], "literal")

    def test_ties_go_to_the_earliest_operation(self):
        paths = {
            "/a/{x}": {"get": {"summary": "first"}},
            "/a/{y}": {"get": {"summary": "second"}},
        }
        found, _ = lookup([("v5", spec(paths))], "GET", "/a/z")
        self.assertEqual(found.op["summary"], "first")

    def test_two_placeholders(self):
        paths = {"/ns/{namespace}/document/{id}": {"get": {}}}
        found, problem = lookup([("v5", spec(paths))], "GET", "/ns/u/document/doc_1")
        self.assertIsNone(problem)
        self.assertEqual(found.template, "/ns/{namespace}/document/{id}")

    def test_empty_path_matches_nothing(self):
        found, problem = lookup(self.specs, "GET", "")
        self.assertIsNone(found)
        self.assertEqual(problem, ("unknown_path", ""))


class DerefTest(unittest.TestCase):
    def setUp(self):
        base = {"type": "object", "required": ["a"], "properties": {"a": {"type": "string"}}}
        schemas = {
            "Base": base,
            "Alias": {"$ref": "#/components/schemas/Base"},
            "LoopA": {"$ref": "#/components/schemas/LoopB"},
            "LoopB": {"$ref": "#/components/schemas/LoopA"},
        }
        self.spec = spec({}, schemas)

    def test_schema_without_a_ref_is_returned_unchanged(self):
        schema = {"type": "string"}
        self.assertIs(deref(self.spec, schema), schema)

    def test_follows_a_ref(self):
        self.assertEqual(deref(self.spec, {"$ref": "#/components/schemas/Base"})["type"], "object")

    def test_follows_a_chain(self):
        result = deref(self.spec, {"$ref": "#/components/schemas/Alias"})
        self.assertEqual(result["properties"], {"a": {"type": "string"}})

    def test_sibling_keys_override_the_target(self):
        result = deref(self.spec, {"$ref": "#/components/schemas/Base", "description": "own", "required": []})
        self.assertEqual(result["description"], "own")
        self.assertEqual(result["required"], [])
        self.assertEqual(result["properties"], {"a": {"type": "string"}})

    def test_resolving_does_not_change_the_spec(self):
        deref(self.spec, {"$ref": "#/components/schemas/Base", "description": "own"})
        base = self.spec["components"]["schemas"]["Base"]
        self.assertEqual(base["required"], ["a"])
        self.assertNotIn("description", base)

    def test_unknown_ref_is_left_alone(self):
        schema = {"$ref": "#/components/schemas/Missing"}
        self.assertEqual(deref(self.spec, schema), schema)

    def test_a_cycle_stops_at_the_depth_cap(self):
        result = deref(self.spec, {"$ref": "#/components/schemas/LoopA"})
        self.assertEqual(result, {"$ref": "#/components/schemas/LoopA"})

    def test_external_refs_are_left_alone(self):
        schema = {"$ref": "https://example.com/schemas/thing.json"}
        self.assertEqual(deref(self.spec, schema), schema)

    def test_pointer_escapes_are_unescaped(self):
        spec_with_slash = spec({}, {"a/b": {"type": "integer"}})
        self.assertEqual(deref(spec_with_slash, {"$ref": "#/components/schemas/a~1b"}), {"type": "integer"})


class BodySchemasTest(unittest.TestCase):
    def test_schemas_by_content_type(self):
        content = {
            "application/json": {"schema": {"type": "object"}},
            "multipart/form-data": {"schema": {"$ref": "#/components/schemas/File"}},
        }
        op = Operation("v5", "POST", "/x", {"requestBody": {"content": content}})
        found = body_schemas(op)
        self.assertEqual(list(found), ["application/json", "multipart/form-data"])
        self.assertEqual(found["application/json"], {"type": "object"})
        self.assertEqual(found["multipart/form-data"], {"$ref": "#/components/schemas/File"})

    def test_operation_without_a_body(self):
        self.assertEqual(body_schemas(operation()), {})

    def test_request_body_without_content(self):
        op = Operation("v5", "POST", "/x", {"requestBody": {"required": True}})
        self.assertEqual(body_schemas(op), {})

    def test_entries_without_a_schema_are_skipped(self):
        content = {
            "application/json": {},
            "text/plain": "nope",
            "application/xml": {"schema": {}},
        }
        op = Operation("v5", "POST", "/x", {"requestBody": {"content": content}})
        self.assertEqual(body_schemas(op), {"application/xml": {}})


class ParamsTest(unittest.TestCase):
    def setUp(self):
        parameters = [
            {"name": "page", "in": "query", "schema": {"type": "integer"}},
            {"name": "namespace", "in": "path", "required": True, "schema": {"type": "string"}},
            {"name": "page", "in": "header", "schema": {"type": "string"}},
            {"in": "query", "schema": {"type": "string"}},
            "not a parameter",
        ]
        self.operation = Operation("v5", "GET", "/ns/{namespace}/list", {"parameters": parameters})

    def test_query_parameters_by_name(self):
        found = params({}, self.operation, "query")
        self.assertEqual(list(found), ["page"])
        self.assertEqual(found["page"]["schema"], {"type": "integer"})

    def test_path_parameters(self):
        found = params({}, self.operation, "path")
        self.assertEqual(list(found), ["namespace"])
        self.assertTrue(found["namespace"]["required"])

    def test_a_where_without_parameters(self):
        self.assertEqual(params({}, self.operation, "cookie"), {})

    def test_operation_without_parameters(self):
        self.assertEqual(params({}, operation(), "query"), {})


if __name__ == "__main__":
    unittest.main()
