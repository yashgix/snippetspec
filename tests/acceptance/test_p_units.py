import contextlib
import io
import tempfile
import unittest
from pathlib import Path

from snippetspec.__main__ import main as cli
from snippetspec.calls import find_calls
from snippetspec.check import check_call, validate
from snippetspec.data import ROOT
from snippetspec.jsread import UNKNOWN
from snippetspec.mdx import extract
from snippetspec.mutate import apply, mutations, run
from snippetspec.report import scan
from snippetspec.spec import deref, match, operations

DEMO = None


def demo_render():
    global DEMO
    if DEMO is None:
        import importlib.util

        spec = importlib.util.spec_from_file_location("demo_module", ROOT / "demo.py")
        DEMO = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(DEMO)
    return DEMO.render


def ex(code, language="bash"):
    return extract(f"```{language}\n{code}\n```")[0]


def calls(code, language="bash"):
    return find_calls(ex(code, language))


SPEC = {
    "paths": {
        "/items": {
            "get": {
                "parameters": [
                    {"in": "query", "name": "limit", "schema": {"type": "integer"}},
                    {"in": "query", "name": "sort", "schema": {"type": "string", "enum": ["asc", "desc"]}},
                    {"in": "query", "name": "tag", "required": True, "schema": {"type": "string"}},
                    {"in": "query", "name": "flag", "schema": {"type": "boolean"}},
                    {"in": "query", "name": "kinds", "schema": {"type": "array", "items": {"enum": ["a", "b"]}}},
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
            "get": {"parameters": [{"in": "path", "name": "id", "schema": {"type": "string"}}]},
            "delete": {"parameters": [{"in": "path", "name": "id", "schema": {"type": "string"}}]},
            "patch": {
                "requestBody": {"content": {"application/json": {"schema": {"$ref": "#/components/schemas/Item"}}}}
            },
        },
        "/items/search": {"post": {"requestBody": {"content": {"application/json": {"schema": {"type": "object"}}}}}},
        "/list/{type}": {
            "post": {"parameters": [{"in": "path", "name": "type", "schema": {"enum": ["docs", "chunks"]}}]}
        },
        "/upload": {
            "post": {
                "requestBody": {
                    "content": {
                        "multipart/form-data": {
                            "schema": {
                                "type": "object",
                                "properties": {"file": {"type": "string"}, "tags": {"type": "string"}},
                                "required": ["file"],
                            }
                        }
                    }
                }
            }
        },
    },
    "components": {
        "schemas": {
            "Item": {
                "type": "object",
                "required": ["name", "mode"],
                "properties": {
                    "name": {"type": "string"},
                    "mode": {"type": "string", "enum": ["fast", "slow"]},
                    "count": {"type": ["integer", "null"]},
                    "meta": {"type": "object", "additionalProperties": True, "properties": {}},
                    "tags": {"type": "array", "items": {"type": "string"}},
                    "kind": {"const": "item"},
                    "nested": {"type": "object", "properties": {"x": {"type": "number"}}},
                },
            }
        }
    },
}
SPECS = {"a": SPEC}
OPS = operations([("a", SPEC)])
BASE = "https://api.test"


def check(code, language="bash"):
    return check_call(SPECS, OPS, calls(code, language)[0])


class Extraction(unittest.TestCase):
    def test_fences_lines_language_meta_title(self):
        text = '# T\n\n```bash title="Run it" extra\ncurl x\n```\n\n~~~\nplain\n~~~\n````ts cURL\na\n```\nb\n````\n'
        got = extract(text, "p.mdx")
        self.assertEqual(
            [(e.line, e.language, e.meta, e.title) for e in got],
            [(3, "bash", 'title="Run it" extra', "Run it"), (7, "text", None, None), (10, "ts", "cURL", None)],
        )
        self.assertEqual(got[2].code, "a\n```\nb")
        self.assertEqual(got[0].page, "p.mdx")
        self.assertEqual(extract("```py title='x y'\n```\n```py a title=z\n```")[0].title, "x y")
        self.assertEqual(extract("```py title='x y'\n```\n```py a title=z\n```")[1].title, "z")

    def test_groups_and_dedent(self):
        text = (
            '<Tabs>\n  <Tab title="A">\n    ```bash\n    curl a\n      -x\n    ```\n  </Tab>\n'
            "  <CodeGroup>\n```js\nb\n```\n  </CodeGroup>\n</Tabs>\n```py\nc\n```\n<CodeGroup/>\n"
            "<CodeGroup>\n```sh\nd\n```\n</CodeGroup>\n"
        )
        got = extract(text)
        self.assertEqual([e.group for e in got], [0, 0, None, 1])
        self.assertEqual(got[0].code, "curl a\n  -x")

    def test_unclosed_and_backtick_info(self):
        self.assertEqual(extract("```bash\ncurl a\n``\nmore")[0].code, "curl a\n``\nmore")
        self.assertEqual([(e.line, e.code) for e in extract("``` a`b\nx\n```")], [(3, "")])
        self.assertEqual(extract("<Tabs>\n```\n</Tabs>\n```\n```x\ny\n```")[1].group, 0)


class CurlCalls(unittest.TestCase):
    def test_methods(self):
        cases = {
            f'curl -X PUT "{BASE}/a"': "PUT",
            f"curl --request=PATCH {BASE}/a": "PATCH",
            f"curl -sXDELETE {BASE}/a": "DELETE",
            f"curl {BASE}/a -d '{{}}'": "POST",
            f"curl -I {BASE}/a": "HEAD",
            f"curl -fsSL {BASE}/a": "GET",
            f"curl -F file=@x.pdf {BASE}/a": "POST",
        }
        for code, method in cases.items():
            self.assertEqual(calls(code)[0].method, method, code)

    def test_get_flag_moves_data_to_query(self):
        call = calls(f'curl -G "{BASE}/a?x=1" -d y=2 --data-raw "z=3"')[0]
        self.assertEqual(
            (call.method, call.query, call.body_kind, call.body),
            ("GET", (("x", "1"), ("y", "2"), ("z", "3")), "none", None),
        )

    def test_body_kinds(self):
        multi = f"curl -X POST {BASE}/a \\\n  -H 'Content-Type: application/json' \\\n  -d '{{\n  \"a\": [1, 2.5]\n}}'"
        self.assertEqual((calls(multi)[0].body_kind, calls(multi)[0].body), ("json", {"a": [1, 2.5]}))
        self.assertEqual(calls(f"curl {BASE}/a -d '{{\"a\": ...}}'")[0].body_kind, "unparsed")
        self.assertEqual(calls(f"curl {BASE}/a -d @body.json")[0].body_kind, "unparsed")
        self.assertEqual(calls(f"curl {BASE}/a -H 'content-type: application/json' -d 'x=1'")[0].body_kind, "unparsed")
        form = calls(f"curl {BASE}/a -F 'file=@doc.pdf' -F tags=x")[0]
        self.assertEqual((form.body_kind, form.body), ("form", {"file": UNKNOWN, "tags": "x"}))
        self.assertEqual(calls(f"curl {BASE}/a -d a=1 -d b=2")[0].body, {"a": "1", "b": "2"})
        self.assertEqual(calls(f"curl {BASE}/a --json '[1]'")[0].body, [1])

    def test_commands_prompts_pipes_comments(self):
        code = (
            f"# list\n$ curl {BASE}/one | jq .\nexport A=1; curl --url {BASE}/two -o out.json\n"
            f"echo curl\ncurl https://other.example/x && curl not-a-url\n"
        )
        self.assertEqual([c.url for c in calls(code)], [f"{BASE}/one", f"{BASE}/two", "https://other.example/x"])
        self.assertEqual(calls("curl 'unterminated"), [])
        self.assertEqual(calls(f"curl {BASE}/a", "json"), [])


class ScriptCalls(unittest.TestCase):
    def test_fetch_literals(self):
        code = (
            f'const r = await fetch("{BASE}/a?x=1", {{\n  method: "post", // why\n  headers: {{}},\n'
            '  body: JSON.stringify({ name: "n", n: 3, f: 1.5, e: 1e3, big: 1_000, ok: true, no: null, '
            "list: [1, 'two'], id, other: value + 1, inner: { a: `t` } }),\n});"
        )
        call = calls(code, "ts")[0]
        self.assertEqual((call.tool, call.method, call.query, call.body_kind), ("fetch", "POST", (("x", "1"),), "json"))
        self.assertEqual(
            call.body,
            {
                "name": "n",
                "n": 3,
                "f": 1.5,
                "e": 1000.0,
                "big": 1000,
                "ok": True,
                "no": None,
                "list": [1, "two"],
                "id": UNKNOWN,
                "other": UNKNOWN,
                "inner": {"a": "t"},
            },
        )
        self.assertIsInstance(call.body["big"], int)

    def test_fetch_templates_and_dropped_calls(self):
        code = (
            "fetch(`" + BASE + "/items/${ id }`)\nfetch(url)\nfetch('" + BASE + "/b', opts)\n"
            "container.fetch('" + BASE + "/c')\nfetch('" + BASE + "/d', { method: m })\n"
            "fetch('" + BASE + "/e', { method: 'PUT', body: JSON.stringify({ ...rest, a: 1 }) })\n"
            "fetch('" + BASE + "/f', { body: '{\"a\": 1}' })\nfetch('" + BASE + "/g', { body: form })\n"
            "fetch('" + BASE + "/h', { body: JSON.stringify(payload) })"
        )
        got = [(c.url.removeprefix(BASE), c.method, c.body_kind, c.body) for c in calls(code, "javascript")]
        self.assertEqual(
            got,
            [
                ("/items/{id}", "GET", "none", None),
                ("/e", "PUT", "json", UNKNOWN),
                ("/f", "GET", "json", {"a": 1}),
                ("/g", "GET", "unparsed", None),
                ("/h", "GET", "json", UNKNOWN),
            ],
        )

    def test_python_calls(self):
        code = (
            f"import requests, httpx\nr = requests.post('{BASE}/a', json={{'a': 1, 'b': x}}, params={{'p': 2}})\n"
            f"requests.get(f'{BASE}/items/{{doc_id}}?q=1')\n"
            f"requests.request('put', url='{BASE}/c', data={{'k': 'v'}})\n"
            f"httpx.delete('{BASE}/d', json=payload)\nrequests.post(url, json={{}})\n"
            f"requests.post('{BASE}/e', files=f)\n"
        )
        got = [
            (c.tool, c.method, c.url.removeprefix(BASE), c.query, c.body_kind, c.body) for c in calls(code, "python")
        ]
        self.assertEqual(
            got,
            [
                ("requests", "POST", "/a", (("p", "2"),), "json", {"a": 1, "b": UNKNOWN}),
                ("requests", "GET", "/items/{doc_id}?q=1", (("q", "1"),), "none", None),
                ("requests", "PUT", "/c", (), "form", {"k": "v"}),
                ("requests", "DELETE", "/d", (), "json", UNKNOWN),
                ("requests", "POST", "/e", (), "unparsed", None),
            ],
        )
        self.assertEqual(calls("requests.get('x'", "python"), [])
        varied = calls(f"requests.get('{BASE}/x', params={{'a': v, 'b': True}})", "python")[0]
        self.assertEqual(varied.query, (("a", "{?}"), ("b", "True")))


class Matching(unittest.TestCase):
    def test_match_rules(self):
        self.assertEqual(match(OPS, "POST", "/items/search")[0].name, "POST /items/search")
        self.assertEqual(match(OPS, "GET", "/items/search/")[0].name, "GET /items/{id}")
        self.assertEqual(match(OPS, "PUT", "/items/7"), (None, ("method_not_allowed", "DELETE,GET,PATCH")))
        self.assertEqual(match(OPS, "GET", "/nope/7"), (None, ("unknown_path", "/nope/7")))
        x = {"paths": {"/{a}/b": {"get": {}}, "/a/{b}": {"get": {}}, "/c/{d}": {"put": {}}, "/{c}/d": {"put": {}}}}
        tie = operations([("x", x), ("y", {"paths": {"/a/b": {"post": {}, "get": {}}}})])
        self.assertEqual((match(tie, "GET", "/a/b")[0].template, match(tie, "GET", "/a/b")[0].spec), ("/a/b", "y"))
        self.assertEqual(match(tie, "PUT", "/c/d")[0].template, "/c/{d}")
        self.assertEqual(match(tie, "PATCH", "/a/b")[1], ("method_not_allowed", "GET,POST"))

    def test_deref_keeps_siblings(self):
        self.assertEqual(deref(SPEC, {"$ref": "#/components/schemas/Item", "description": "d"})["description"], "d")
        self.assertEqual(deref(SPEC, {"$ref": "#/components/schemas/Item"})["required"], ["name", "mode"])


class Checking(unittest.TestCase):
    def test_query_and_path(self):
        got = check(f"curl '{BASE}/items?limit=ten&sort=up&flag=yes&kinds=a&kinds=c&extra=1&limit=$N&sort={{s}}'")
        self.assertEqual(
            got,
            {
                "operation": "a:GET /items",
                "problems": [
                    ("missing_param", "query:tag"),
                    ("type", "query:limit"),
                    ("enum", "query:sort"),
                    ("type", "query:flag"),
                    ("enum", "query:kinds"),
                    ("undocumented_param", "query:extra"),
                ],
            },
        )
        self.assertEqual(check(f"curl '{BASE}/items?tag=t&limit=-3&flag=true&kinds=b'")["problems"], [])
        self.assertEqual(check(f"curl -X POST {BASE}/list/doc%73")["problems"], [])
        self.assertEqual(check(f"curl -X POST {BASE}/list/pages")["problems"], [("enum", "path:type")])
        self.assertEqual(check(f"curl -X POST '{BASE}/list/<type>'")["problems"], [])

    def test_body_validation(self):
        body = (
            '{"mode": "medium", "count": "3", "meta": {"any": 1}, "tags": ["a", 2], "kind": "x", '
            '"nested": {"x": 1, "y": 2}, "extra": true}'
        )
        got = check(f"curl -X POST {BASE}/items -d '{body}'")["problems"]
        self.assertEqual(
            got,
            [
                ("missing_field", "$.name"),
                ("enum", "$.mode"),
                ("type", "$.count"),
                ("type", "$.tags[1]"),
                ("enum", "$.kind"),
                ("undocumented_field", "$.nested.y"),
                ("undocumented_field", "$.extra"),
            ],
        )
        ok = check(f'curl -X PATCH {BASE}/items/1 -d \'{{"name": "$NAME", "mode": "<mode>", "count": null}}\'')
        self.assertEqual(ok, {"operation": "a:PATCH /items/{id}", "problems": []})

    def test_any_of_fewest_problems(self):
        spec = {
            "x": {"type": "object", "properties": {"a": {"type": "string"}}},
            "y": {"type": "object", "properties": {"b": {"type": "string"}, "c": {"type": "string"}}},
        }
        schema = {"anyOf": [spec["x"], spec["y"], {"type": "string"}]}
        self.assertEqual(validate({}, schema, {"b": 1, "c": "z"}), [("type", "$.b")])
        self.assertEqual(
            validate({}, schema, {"a": 1, "z": 2, "q": 3}),
            [("type", "$.a"), ("undocumented_field", "$.z"), ("undocumented_field", "$.q")],
        )
        self.assertEqual(validate({}, schema, 5), [("type", "$")])
        self.assertEqual(validate({}, {"oneOf": [{"type": "integer"}, {"type": "boolean"}]}, True), [])
        self.assertEqual(validate({}, {"type": "integer"}, True), [("type", "$")])
        self.assertEqual(validate({}, {"type": "number"}, 2), [])

    def test_body_kinds(self):
        self.assertEqual(check(f"curl -X POST {BASE}/items")["problems"], [("missing_body", "body")])
        self.assertEqual(check(f"curl -X PATCH {BASE}/items/1")["problems"], [])
        self.assertEqual(check(f"curl -X DELETE {BASE}/items/1 -d '{{}}'")["problems"], [])
        self.assertEqual(
            check(f"curl -X DELETE {BASE}/items/1 -d '{{\"a\": 1}}'")["problems"], [("unexpected_body", "body")]
        )
        self.assertEqual(check(f"curl -X POST {BASE}/items -F name=x")["problems"], [("content_type", "body:form")])
        self.assertEqual(check(f"curl {BASE}/upload -d '{{\"file\": 1}}'")["problems"], [("content_type", "body:json")])
        self.assertEqual(
            check(f"curl {BASE}/upload -F tags=1 -F other=@x")["problems"],
            [("missing_field", "$.file"), ("undocumented_field", "$.other")],
        )
        self.assertEqual(check(f"curl -X POST {BASE}/items -d '{{bad'")["problems"], [])
        self.assertEqual(check(f"curl -X POST {BASE}/items/search -d '{{\"x\": 1}}'")["problems"], [])


class Scanning(unittest.TestCase):
    def test_rows_and_verdicts(self):
        page = (
            f"```bash\ncurl {BASE}/items?tag=a\ncurl https://other.test/x\ncurl {BASE}/nope\n```\n"
            f"<CodeGroup>\n```ts\nfetch('{BASE}/items', {{ method: 'POST', "
            f"body: JSON.stringify({{ name: n, mode: 'fast' }}) }})\n```\n"
            "</CodeGroup>\n```json\n{}\n```\n"
        )
        got = scan({"p.mdx": page}, SPECS, "api.test")
        self.assertEqual((got["pages"], got["examples"], got["other_host"]), (1, 3, 1))
        self.assertEqual(
            [(r["line"], r["index"], r["tool"], r["verdict"], r["group"], r["operation"]) for r in got["calls"]],
            [
                (1, 0, "curl", "ok", None, "a:GET /items"),
                (1, 1, "curl", "mismatch", None, None),
                (7, 0, "fetch", "partial", 0, "a:POST /items"),
            ],
        )
        self.assertEqual(got["calls"][1]["problems"], [["unknown_path", "/nope"]])
        self.assertEqual(
            set(got["calls"][0]),
            {"page", "line", "index", "language", "group", "tool", "method", "url", "operation", "verdict", "problems"},
        )


class Drift(unittest.TestCase):
    def test_mutation_order(self):
        call = calls(f'curl -X POST {BASE}/items -d \'{{"name": "a", "mode": "fast", "zzz": 1}}\'')[0]
        self.assertEqual(
            mutations(SPEC, match(OPS, "POST", "/items")[0], call),
            [
                "remove_operation",
                "rename_field:name",
                "rename_field:mode",
                "add_required",
                "drop_enum_value:body:mode=fast",
                "add_optional",
                "add_enum_value",
            ],
        )
        call = calls(f"curl '{BASE}/items?tag=t&sort=asc&sort=desc&tag=u&other=1'")[0]
        self.assertEqual(
            mutations(SPEC, match(OPS, "GET", "/items")[0], call),
            [
                "remove_operation",
                "drop_enum_value:query:sort=asc",
                "drop_enum_value:query:sort=desc",
                "rename_param:tag",
                "rename_param:sort",
                "add_enum_value",
            ],
        )
        call = calls(f"curl -X POST {BASE}/list/docs")[0]
        self.assertEqual(
            mutations(SPEC, match(OPS, "POST", "/list/docs")[0], call),
            ["remove_operation", "drop_enum_value:path:type=docs", "add_enum_value"],
        )

    def test_apply_changes_one_operation_only(self):
        post = match(OPS, "POST", "/items")[0]
        changed = apply(SPEC, post, "rename_field:name")
        props = changed["paths"]["/items"]["post"]["requestBody"]["content"]["application/json"]["schema"]
        self.assertEqual(list(props["properties"])[:2], ["name_renamed", "mode"])
        self.assertEqual(props["required"], ["name_renamed", "mode"])
        self.assertIn("name", changed["components"]["schemas"]["Item"]["properties"])
        self.assertIn("$ref", SPEC["paths"]["/items"]["post"]["requestBody"]["content"]["application/json"]["schema"])
        self.assertNotIn("post", apply(SPEC, post, "remove_operation")["paths"]["/items"])
        get = match(OPS, "GET", "/items")[0]
        params = apply(SPEC, get, "add_enum_value")["paths"]["/items"]["get"]["parameters"]
        self.assertEqual(params[1]["schema"]["enum"], ["asc", "desc", "added-value"])
        self.assertEqual(
            apply(SPEC, get, "rename_param:tag")["paths"]["/items"]["get"]["parameters"][2]["name"], "tag_renamed"
        )
        dropped = apply(SPEC, post, "drop_enum_value:body:mode=fast")["paths"]["/items"]["post"]
        self.assertEqual(
            dropped["requestBody"]["content"]["application/json"]["schema"]["properties"]["mode"]["enum"], ["slow"]
        )
        req = apply(SPEC, post, "add_required")["paths"]["/items"]["post"]["requestBody"]["content"]["application/json"]
        self.assertEqual(
            (req["schema"]["required"], req["schema"]["properties"]["addedField"]),
            (["name", "mode", "addedField"], {"type": "string"}),
        )

    def test_run_rows(self):
        found = [
            calls(f'curl -X POST {BASE}/items -d \'{{"name": "a", "mode": "fast"}}\'')[0],
            calls(f"curl {BASE}/nope")[0],
            calls(f"curl '{BASE}/items?tag=t'")[0],
        ]
        rows = run(SPECS, found)
        self.assertEqual(
            [(r["mutation"], r["operation"], r["codes"]) for r in rows],
            [
                ("remove_operation", "a:POST /items", ["method_not_allowed"]),
                ("rename_field:name", "a:POST /items", ["missing_field", "undocumented_field"]),
                ("rename_field:mode", "a:POST /items", ["missing_field", "undocumented_field"]),
                ("add_required", "a:POST /items", ["missing_field"]),
                ("drop_enum_value:body:mode=fast", "a:POST /items", ["enum"]),
                ("add_optional", "a:POST /items", []),
                ("add_enum_value", "a:POST /items", []),
                ("remove_operation", "a:GET /items", ["method_not_allowed"]),
                ("rename_param:tag", "a:GET /items", ["missing_param", "undocumented_param"]),
                ("add_enum_value", "a:GET /items", []),
            ],
        )


class Outputs(unittest.TestCase):
    def test_render(self):
        render = demo_render()
        metrics = {
            k: 1
            for k in (
                "pages",
                "examples",
                "examples_http",
                "calls",
                "calls_mismatch",
                "findings",
                "triage_spec_gap",
                "triage_unconfirmed",
                "triage_false_positive",
                "ledger_cases",
                "ledger_caught",
                "mutation_breaking_cases",
                "mutation_breaking_caught",
                "mutation_neutral_cases",
                "mutation_neutral_flagged",
                "spec_operations",
                "spec_operations_with_example",
            )
        }
        metrics["ledger_recall"] = 0.5
        out = render("# R\n<!-- snippetspec:results -->\nold\n<!-- /snippetspec:results -->\ntail\n", metrics)
        lines = out.splitlines()
        self.assertEqual(lines[:4], ["# R", "<!-- snippetspec:results -->", "| metric | value |", "|---|---|"])
        self.assertEqual(lines[4], "| pages | 1 |")
        self.assertEqual(lines[15], "| ledger_recall | 0.5 |")
        self.assertEqual(lines[-2:], ["<!-- /snippetspec:results -->", "tail"])
        self.assertEqual(len(lines), 24)
        for bad in (
            "no markers",
            "<!-- /snippetspec:results --><!-- snippetspec:results -->",
            "<!-- snippetspec:results --><!-- snippetspec:results --><!-- /snippetspec:results -->",
        ):
            with self.assertRaises(ValueError):
                render(bad, metrics)

    def test_cli(self):
        with tempfile.TemporaryDirectory() as tmp:
            page = Path(tmp) / "p.mdx"
            page.write_text(
                "```bash\ncurl https://api.supermemory.ai/v3/settings\ncurl https://api.supermemory.ai/v3/nope\n```\n"
            )
            out = io.StringIO()
            with contextlib.redirect_stdout(out):
                code = cli([str(page)])
            self.assertEqual(code, 1)
            self.assertEqual(
                out.getvalue().splitlines(),
                [
                    f"{page.as_posix()}:1 #1 GET /v3/nope mismatch unknown_path /v3/nope",
                    "2 calls: 1 ok, 0 partial, 1 mismatch",
                ],
            )
            page.write_text("```bash\ncurl https://api.supermemory.ai/v3/settings\n```\n")
            with contextlib.redirect_stdout(io.StringIO()):
                self.assertEqual(cli([str(page)]), 0)


if __name__ == "__main__":
    unittest.main()
