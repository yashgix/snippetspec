import unittest

from snippetspec.calls import Call
from snippetspec.mutate import BREAKING, NEUTRAL, apply, mutations, run
from snippetspec.spec import operations


def spec() -> dict:
    return {
        "paths": {
            "/items/{id}": {
                "get": {
                    "parameters": [
                        {
                            "name": "id",
                            "in": "path",
                            "required": True,
                            "schema": {"type": "string", "enum": ["a", "b"]},
                        },
                        {"name": "mode", "in": "query", "schema": {"type": "string", "enum": ["fast", "slow"]}},
                        {"name": "limit", "in": "query", "schema": {"type": "integer"}},
                    ]
                }
            },
            "/items": {
                "post": {
                    "requestBody": {
                        "required": True,
                        "content": {"application/json": {"schema": {"$ref": "#/components/schemas/Item"}}},
                    }
                }
            },
        },
        "components": {
            "schemas": {
                "Item": {
                    "type": "object",
                    "required": ["name"],
                    "properties": {
                        "name": {"type": "string"},
                        "kind": {"type": "string", "enum": ["x", "y"]},
                    },
                }
            }
        },
    }


def operation(model: dict, method: str, template: str):
    return next(item for item in operations([("v5", model)]) if item.method == method and item.template == template)


def call(method: str, url: str, query=(), body_kind="none", body=None) -> Call:
    return Call("curl", method, url, tuple(query), body_kind, body)


class MutationListTest(unittest.TestCase):
    def test_post_body_mutations_in_order(self):
        model = spec()
        found = mutations(
            model,
            operation(model, "POST", "/items"),
            call("POST", "https://api.supermemory.ai/items", body_kind="json", body={"name": "n", "kind": "x"}),
        )
        self.assertEqual(
            found,
            [
                "remove_operation",
                "rename_field:name",
                "rename_field:kind",
                "add_required",
                "drop_enum_value:body:kind=x",
                "add_optional",
                "add_enum_value",
            ],
        )

    def test_get_parameters_and_enum_mutations(self):
        model = spec()
        found = mutations(
            model,
            operation(model, "GET", "/items/{id}"),
            call(
                "GET",
                "https://api.supermemory.ai/items/a",
                query=(("mode", "fast"), ("limit", "1")),
            ),
        )
        self.assertEqual(
            found,
            [
                "remove_operation",
                "drop_enum_value:path:id=a",
                "drop_enum_value:query:mode=fast",
                "rename_param:mode",
                "rename_param:limit",
                "add_enum_value",
            ],
        )

    def test_rename_param_is_distinct(self):
        model = spec()
        found = mutations(
            model,
            operation(model, "GET", "/items/{id}"),
            call(
                "GET",
                "https://api.supermemory.ai/items/a",
                query=(("mode", "fast"), ("mode", "slow"), ("limit", "1")),
            ),
        )
        self.assertEqual(found.count("rename_param:mode"), 1)

    def test_constants(self):
        self.assertEqual(BREAKING["remove_operation"], ("unknown_path", "method_not_allowed"))
        self.assertEqual(NEUTRAL, ("add_optional", "add_enum_value"))


class ApplyTest(unittest.TestCase):
    def test_remove_operation_leaves_the_original_alone(self):
        model = spec()
        changed = apply(model, operation(model, "POST", "/items"), "remove_operation")
        self.assertNotIn("post", changed["paths"]["/items"])
        self.assertIn("post", model["paths"]["/items"])

    def test_rename_field_edits_only_the_inlined_copy(self):
        model = spec()
        changed = apply(model, operation(model, "POST", "/items"), "rename_field:kind")
        schema = changed["paths"]["/items"]["post"]["requestBody"]["content"]["application/json"]["schema"]
        self.assertIn("kind_renamed", schema["properties"])
        self.assertNotIn("kind", schema["properties"])
        self.assertEqual(schema["properties"]["kind_renamed"], {"type": "string", "enum": ["x", "y"]})
        self.assertIn("kind", model["components"]["schemas"]["Item"]["properties"])

    def test_rename_field_also_renames_required(self):
        model = spec()
        changed = apply(model, operation(model, "POST", "/items"), "rename_field:name")
        schema = changed["paths"]["/items"]["post"]["requestBody"]["content"]["application/json"]["schema"]
        self.assertEqual(schema["required"], ["name_renamed"])
        self.assertIn("name_renamed", schema["properties"])

    def test_add_required(self):
        model = spec()
        changed = apply(model, operation(model, "POST", "/items"), "add_required")
        schema = changed["paths"]["/items"]["post"]["requestBody"]["content"]["application/json"]["schema"]
        self.assertEqual(schema["required"], ["name", "addedField"])
        self.assertEqual(schema["properties"]["addedField"], {"type": "string"})

    def test_add_optional(self):
        model = spec()
        changed = apply(model, operation(model, "POST", "/items"), "add_optional")
        schema = changed["paths"]["/items"]["post"]["requestBody"]["content"]["application/json"]["schema"]
        self.assertEqual(schema["properties"]["addedOptional"], {"type": "string"})
        self.assertEqual(schema["required"], ["name"])

    def test_drop_enum_value_from_body(self):
        model = spec()
        changed = apply(model, operation(model, "POST", "/items"), "drop_enum_value:body:kind=x")
        schema = changed["paths"]["/items"]["post"]["requestBody"]["content"]["application/json"]["schema"]
        self.assertEqual(schema["properties"]["kind"]["enum"], ["y"])
        self.assertEqual(model["components"]["schemas"]["Item"]["properties"]["kind"]["enum"], ["x", "y"])

    def test_drop_enum_value_from_path_parameter(self):
        model = spec()
        changed = apply(model, operation(model, "GET", "/items/{id}"), "drop_enum_value:path:id=a")
        parameter = changed["paths"]["/items/{id}"]["get"]["parameters"][0]
        self.assertEqual(parameter["schema"]["enum"], ["b"])
        self.assertEqual(model["paths"]["/items/{id}"]["get"]["parameters"][0]["schema"]["enum"], ["a", "b"])

    def test_drop_enum_value_from_query_parameter(self):
        model = spec()
        changed = apply(model, operation(model, "GET", "/items/{id}"), "drop_enum_value:query:mode=fast")
        parameter = changed["paths"]["/items/{id}"]["get"]["parameters"][1]
        self.assertEqual(parameter["schema"]["enum"], ["slow"])

    def test_rename_param(self):
        model = spec()
        changed = apply(model, operation(model, "GET", "/items/{id}"), "rename_param:mode")
        parameters = changed["paths"]["/items/{id}"]["get"]["parameters"]
        self.assertEqual(parameters[1]["name"], "mode_renamed")
        self.assertEqual(model["paths"]["/items/{id}"]["get"]["parameters"][1]["name"], "mode")

    def test_add_enum_value(self):
        model = spec()
        get_changed = apply(model, operation(model, "GET", "/items/{id}"), "add_enum_value")
        parameters = get_changed["paths"]["/items/{id}"]["get"]["parameters"]
        self.assertEqual(parameters[0]["schema"]["enum"], ["a", "b", "added-value"])
        self.assertEqual(parameters[1]["schema"]["enum"], ["fast", "slow", "added-value"])
        post_changed = apply(model, operation(model, "POST", "/items"), "add_enum_value")
        schema = post_changed["paths"]["/items"]["post"]["requestBody"]["content"]["application/json"]["schema"]
        self.assertEqual(schema["properties"]["kind"]["enum"], ["x", "y", "added-value"])


class RunTest(unittest.TestCase):
    def test_rows_name_the_operation_and_sorted_distinct_codes(self):
        model = spec()
        target = call("GET", "https://api.supermemory.ai/items/a", query=(("mode", "fast"), ("limit", "1")))
        rows = run({"v5": model}, [target])
        self.assertEqual(
            [row["mutation"] for row in rows],
            [
                "remove_operation",
                "drop_enum_value:path:id=a",
                "drop_enum_value:query:mode=fast",
                "rename_param:mode",
                "rename_param:limit",
                "add_enum_value",
            ],
        )
        by_mutation = {row["mutation"]: row for row in rows}
        self.assertEqual(by_mutation["remove_operation"]["operation"], "v5:GET /items/{id}")
        self.assertEqual(by_mutation["remove_operation"]["codes"], ["unknown_path"])
        self.assertEqual(by_mutation["drop_enum_value:path:id=a"]["codes"], ["enum"])
        self.assertEqual(by_mutation["rename_param:mode"]["codes"], ["undocumented_param"])
        self.assertEqual(by_mutation["add_enum_value"]["codes"], [])

    def test_calls_with_problems_are_skipped(self):
        model = spec()
        self.assertEqual(run({"v5": model}, [call("GET", "https://api.supermemory.ai/nope")]), [])

    def test_page_calls_triples_are_accepted(self):
        model = spec()
        target = call("GET", "https://api.supermemory.ai/items/a", query=(("limit", "1"),))
        rows = run({"v5": model}, [(None, 0, target)])
        self.assertEqual(rows[0]["mutation"], "remove_operation")


if __name__ == "__main__":
    unittest.main()
