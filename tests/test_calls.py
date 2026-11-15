import unittest
from dataclasses import FrozenInstanceError

from snippetcheck.calls import Call, find_calls, unparsed_commands
from snippetcheck.jsread import UNKNOWN
from snippetcheck.mdx import Example


def example(code, language="bash"):
    return Example("page.mdx", 1, language, None, None, code, None)


def calls(code, language="bash"):
    return find_calls(example(code, language))


class CallTest(unittest.TestCase):
    def test_fields_and_frozen(self):
        call = Call("curl", "GET", "https://api.supermemory.ai/v3/documents", (), "none", None)
        self.assertEqual(call.tool, "curl")
        self.assertEqual(call.query, ())
        self.assertIsNone(call.body)
        with self.assertRaises(FrozenInstanceError):
            call.method = "POST"


class DispatchTest(unittest.TestCase):
    def test_other_languages_have_no_calls(self):
        self.assertEqual(calls("curl https://x/a", "json"), [])
        self.assertEqual(calls("fetch('https://x/a')", "text"), [])
        self.assertEqual(calls("requests.get('https://x/a')", "yaml"), [])

    def test_language_is_lower_cased(self):
        self.assertEqual(len(calls("curl https://x/a", "Bash")), 1)

    def test_shell_languages(self):
        for language in ("bash", "sh", "shell", "zsh", "console", "terminal"):
            with self.subTest(language=language):
                self.assertEqual(len(calls("curl https://x/a", language)), 1)

    def test_javascript_languages(self):
        for language in ("javascript", "js", "jsx", "typescript", "ts", "tsx"):
            with self.subTest(language=language):
                self.assertEqual(len(calls('fetch("https://x/a")', language)), 1)

    def test_python_languages(self):
        for language in ("python", "py"):
            with self.subTest(language=language):
                self.assertEqual(len(calls('requests.get("https://x/a")', language)), 1)


class ShellTest(unittest.TestCase):
    def test_simple_get(self):
        found = calls("curl https://api.supermemory.ai/v3/documents")
        self.assertEqual(len(found), 1)
        call = found[0]
        self.assertEqual(call.tool, "curl")
        self.assertEqual(call.method, "GET")
        self.assertEqual(call.url, "https://api.supermemory.ai/v3/documents")
        self.assertEqual(call.query, ())
        self.assertEqual((call.body_kind, call.body), ("none", None))

    def test_only_curl_commands_are_calls(self):
        code = "echo hi\ncurl https://api.supermemory.ai/a\nls -l"
        self.assertEqual([call.url for call in calls(code)], ["https://api.supermemory.ai/a"])

    def test_dollar_prompt_is_ignored(self):
        self.assertEqual(len(calls("$ curl -s https://api.supermemory.ai/v3/health")), 1)

    def test_command_without_a_url_is_not_a_call(self):
        self.assertEqual(calls("curl --help"), [])

    def test_non_http_url_is_dropped(self):
        self.assertEqual(calls("curl ftp://x/a"), [])

    def test_several_commands(self):
        code = "curl https://x/a; curl https://x/b && curl https://x/c"
        self.assertEqual([call.url for call in calls(code)], ["https://x/a", "https://x/b", "https://x/c"])

    def test_backslash_continuation_joins_lines(self):
        code = "curl https://api.supermemory.ai/a \\\n  -H 'Accept: application/json'"
        found = calls(code)
        self.assertEqual([call.url for call in found], ["https://api.supermemory.ai/a"])

    def test_quoting_error_gives_no_calls(self):
        self.assertEqual(calls("curl https://x/a 'unterminated"), [])

    def test_request_option_sets_the_method(self):
        self.assertEqual(calls("curl -X DELETE https://x/a")[0].method, "DELETE")

    def test_short_group_takes_the_rest_as_its_argument(self):
        self.assertEqual(calls("curl -sSL -XPOST https://api.supermemory.ai/v3/documents")[0].method, "POST")

    def test_short_argument_takes_the_next_word(self):
        self.assertEqual(calls("curl -X PUT https://x/a")[0].method, "PUT")

    def test_long_option_with_inline_value(self):
        self.assertEqual(calls("curl --request=PATCH https://x/a")[0].method, "PATCH")

    def test_long_option_takes_the_next_word(self):
        self.assertEqual(calls("curl --request PUT https://x/a")[0].method, "PUT")

    def test_head(self):
        self.assertEqual(calls("curl -I https://x/a")[0].method, "HEAD")

    def test_url_option(self):
        call = calls("curl --url https://api.supermemory.ai/v3/documents")[0]
        self.assertEqual(call.url, "https://api.supermemory.ai/v3/documents")

    def test_url_query_pairs_are_kept_including_blanks(self):
        call = calls("curl 'https://x/a?page=1&q='")[0]
        self.assertEqual(call.query, (("page", "1"), ("q", "")))

    def test_data_is_joined_and_parsed_as_json(self):
        code = "curl -d '{\"a\": 1}' https://x/a"
        call = calls(code)[0]
        self.assertEqual(call.method, "POST")
        self.assertEqual((call.body_kind, call.body), ("json", {"a": 1}))

    def test_data_starting_with_a_bracket_is_json(self):
        call = calls("curl -d '[1, 2]' https://x/a")[0]
        self.assertEqual((call.body_kind, call.body), ("json", [1, 2]))

    def test_json_header_parses_the_data_as_json(self):
        code = "curl -H 'Content-Type: application/json' -d '{\"a\": 1}' https://x/a"
        call = calls(code)[0]
        self.assertEqual((call.method, call.body_kind, call.body), ("POST", "json", {"a": 1}))

    def test_json_header_case_is_ignored(self):
        code = "curl -H 'content-type: application/json' -d 'a=1' https://x/a"
        self.assertEqual(calls(code)[0].body_kind, "unparsed")

    def test_other_data_is_a_form(self):
        call = calls("curl -d 'a=1&b=two' https://x/a")[0]
        self.assertEqual((call.body_kind, call.body), ("form", {"a": "1", "b": "two"}))

    def test_file_data_is_unparsed(self):
        self.assertEqual(calls("curl -d @payload.json https://x/a")[0].body_kind, "unparsed")

    def test_form_field_with_a_file_is_unknown(self):
        call = calls("curl -F 'file=@report.pdf' https://x/a")[0]
        self.assertEqual(call.method, "POST")
        self.assertEqual(call.body_kind, "form")
        self.assertIs(call.body["file"], UNKNOWN)

    def test_get_moves_data_into_the_query_after_the_url_pairs(self):
        call = calls("curl -G -d 'q=hi' 'https://x/a?page=2'")[0]
        self.assertEqual(call.method, "GET")
        self.assertEqual(call.body_kind, "none")
        self.assertEqual(call.query, (("page", "2"), ("q", "hi")))

    def test_no_data_and_no_form_is_no_body(self):
        call = calls("curl -H 'Accept: application/json' https://x/a")[0]
        self.assertEqual((call.method, call.body_kind, call.body), ("GET", "none", None))


class DoubleQuoteTest(unittest.TestCase):
    def test_separators_inside_double_quotes_do_not_split(self):
        url = "https://api.supermemory.ai/v3/search?q=a&limit=3"
        [call] = calls(f'curl "{url}"')
        self.assertEqual(call.query, (("q", "a"), ("limit", "3")))

    def test_newline_and_escaped_quote_inside_double_quotes(self):
        [call] = calls('curl -X POST https://api.supermemory.ai/v3/x -d "{\\"a\\":\n \\"b\\"}"')
        self.assertEqual((call.body_kind, call.body), ("json", {"a": "b"}))


class ShellRobustnessTest(unittest.TestCase):
    def test_ansi_c_string_is_decoded(self):
        [call] = calls('curl -X POST https://api.supermemory.ai/v3/x -d $\'{"a": "b\\\\nc", "q": "it\\\'s"}\'')
        self.assertEqual(call.body, {"a": "b\nc", "q": "it's"})

    def test_get_with_data_urlencode_becomes_query(self):
        [call] = calls("curl -G https://api.supermemory.ai/v3/x --data-urlencode 'q=a b&c' --data-urlencode limit=3")
        self.assertEqual(call.query, (("q", "a b&c"), ("limit", "3")))

    def test_post_with_data_urlencode_is_a_form_body(self):
        [call] = calls("curl https://api.supermemory.ai/v3/x --data-urlencode 'q=a b'")
        self.assertEqual((call.body_kind, call.body), ("form", {"q": "a b"}))

    def test_one_bad_command_does_not_drop_the_block(self):
        code = "curl https://api.supermemory.ai/a 'oops\ncurl https://api.supermemory.ai/b"
        self.assertEqual(calls(code), [])
        code = "curl https://api.supermemory.ai/a\ncurl https://api.supermemory.ai/b 'oops"
        self.assertEqual([call.url for call in calls(code)], ["https://api.supermemory.ai/a"])

    def test_bad_curl_command_is_reported_as_unparsed(self):
        code = "curl https://api.supermemory.ai/a\n$ curl https://api.supermemory.ai/b 'oops"
        self.assertEqual(unparsed_commands(example(code)), ["$ curl https://api.supermemory.ai/b 'oops"])


class FetchTest(unittest.TestCase):
    def test_simple_call(self):
        call = calls('fetch("https://api.supermemory.ai/v3/search")', "javascript")[0]
        self.assertEqual((call.tool, call.method), ("fetch", "GET"))
        self.assertEqual((call.body_kind, call.body), ("none", None))

    def test_options_and_json_stringify_body(self):
        code = (
            'fetch("https://api.supermemory.ai/ns/user/search", {method: "POST", body: JSON.stringify({query: "hi"})})'
        )
        call = calls(code, "typescript")[0]
        self.assertEqual(call.method, "POST")
        self.assertEqual((call.body_kind, call.body), ("json", {"query": "hi"}))

    def test_string_body_is_parsed_as_json(self):
        call = calls('fetch("https://x/a", {method: "POST", body: \'{"a": 1}\'})', "js")[0]
        self.assertEqual((call.body_kind, call.body), ("json", {"a": 1}))

    def test_string_body_that_is_not_json_is_unparsed(self):
        call = calls('fetch("https://x/a", {body: "hello"})', "js")[0]
        self.assertEqual((call.method, call.body_kind, call.body), ("GET", "unparsed", None))

    def test_null_body_is_no_body(self):
        call = calls('fetch("https://x/a", {method: "DELETE", body: null})', "js")[0]
        self.assertEqual((call.method, call.body_kind), ("DELETE", "none"))

    def test_non_literal_body_is_unparsed(self):
        call = calls('fetch("https://x/a", {method: "POST", body: payload})', "js")[0]
        self.assertEqual(call.body_kind, "unparsed")

    def test_template_url_keeps_placeholders(self):
        code = "fetch(`https://api.supermemory.ai/v3/documents/${docId}`)"
        self.assertEqual(calls(code, "js")[0].url, "https://api.supermemory.ai/v3/documents/{docId}")

    def test_non_literal_url_is_dropped(self):
        self.assertEqual(calls("fetch(baseUrl)", "js"), [])

    def test_non_literal_options_are_dropped(self):
        self.assertEqual(calls('fetch("https://x/a", options)', "js"), [])

    def test_non_literal_method_is_dropped(self):
        self.assertEqual(calls('fetch("https://x/a", {method: verb})', "js"), [])

    def test_only_a_bare_fetch_is_a_call(self):
        code = 'prefetch("https://x/a"); client.fetch("https://x/b"); fetch("https://x/c")'
        self.assertEqual([call.url for call in calls(code, "js")], ["https://x/c"])


class FetchSpreadTest(unittest.TestCase):
    def test_stringified_object_with_spread_is_json_of_unknown_value(self):
        [call] = calls(
            "fetch('https://api.supermemory.ai/e', { method: 'PUT', body: JSON.stringify({ ...rest, a: 1 }) })", "js"
        )
        self.assertEqual((call.body_kind, call.body), ("json", UNKNOWN))


class PythonTest(unittest.TestCase):
    def test_get_with_params(self):
        code = 'requests.get("https://api.supermemory.ai/v3/documents/list", params={"page": 1})'
        call = calls(code, "python")[0]
        self.assertEqual((call.tool, call.method), ("requests", "GET"))
        self.assertEqual(call.query, (("page", "1"),))

    def test_params_after_the_url_query(self):
        code = 'requests.get("https://x/a?page=2", params={"limit": 5})'
        self.assertEqual(calls(code, "py")[0].query, (("page", "2"), ("limit", "5")))

    def test_params_value_that_is_not_a_literal_is_a_placeholder(self):
        code = 'requests.get("https://x/a", params={"q": query})'
        self.assertEqual(calls(code, "py")[0].query, (("q", "{?}"),))

    def test_json_body(self):
        code = 'requests.post("https://api.supermemory.ai/v3/documents", json={"content": "hi"})'
        call = calls(code, "py")[0]
        self.assertEqual((call.method, call.body_kind, call.body), ("POST", "json", {"content": "hi"}))

    def test_json_body_from_a_variable_is_unknown(self):
        call = calls('requests.post("https://x/a", json=payload)', "py")[0]
        self.assertEqual(call.body_kind, "json")
        self.assertIs(call.body, UNKNOWN)

    def test_data_dict_is_a_form(self):
        call = calls('requests.post("https://x/a", data={"a": "1"})', "py")[0]
        self.assertEqual((call.body_kind, call.body), ("form", {"a": "1"}))

    def test_data_string_is_unparsed(self):
        self.assertEqual(calls('requests.post("https://x/a", data=body)', "py")[0].body_kind, "unparsed")

    def test_files_dict_is_a_form(self):
        call = calls('httpx.post("https://x/a", files={"file": handle})', "py")[0]
        self.assertEqual(call.body_kind, "form")
        self.assertIs(call.body["file"], UNKNOWN)

    def test_no_body(self):
        call = calls('requests.delete("https://x/a")', "py")[0]
        self.assertEqual((call.method, call.body_kind, call.body), ("DELETE", "none", None))

    def test_f_string_url_keeps_placeholders(self):
        code = 'requests.delete(f"https://api.supermemory.ai/v3/documents/{doc_id}")'
        self.assertEqual(calls(code, "py")[0].url, "https://api.supermemory.ai/v3/documents/{doc_id}")

    def test_request_takes_the_method_first(self):
        code = 'requests.request("PATCH", "https://api.supermemory.ai/v3/documents/doc_1", json={"a": 1})'
        call = calls(code, "py")[0]
        self.assertEqual(call.method, "PATCH")
        self.assertEqual(call.body, {"a": 1})

    def test_keyword_url(self):
        self.assertEqual(calls('requests.get(url="https://x/a")', "py")[0].url, "https://x/a")

    def test_syntax_error_gives_no_calls(self):
        self.assertEqual(calls("requests.get(", "py"), [])

    def test_calls_are_sorted_by_position(self):
        code = 'requests.get("https://x/b")\nrequests.get("https://x/a")'
        self.assertEqual([call.url for call in calls(code, "py")], ["https://x/b", "https://x/a"])

    def test_other_urls_are_dropped(self):
        self.assertEqual(calls('requests.get("localhost:6767/x")', "py"), [])
        self.assertEqual(calls('requests.get(base_url + "/x")', "py"), [])

    def test_other_objects_are_not_calls(self):
        self.assertEqual(calls('session.get("https://x/a")', "py"), [])
        self.assertEqual(calls('requests.head("https://x/a")', "py"), [])


if __name__ == "__main__":
    unittest.main()
