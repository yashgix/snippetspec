import unittest

from snippetspec.metrics import CODES, findings, ratio


class FindingsTest(unittest.TestCase):
    def test_paths_lose_the_query_and_duplicates_are_removed(self):
        rows = [
            {"method": "GET", "url": "https://api.supermemory.ai/a?x=1", "problems": [["type", "body.a"]]},
            {"method": "GET", "url": "https://api.supermemory.ai/a?x=1", "problems": [["type", "body.a"]]},
            {"method": "POST", "url": "https://api.supermemory.ai/b", "problems": [["unknown_path", "/b"]]},
            {"method": "GET", "url": "https://api.supermemory.ai/a", "problems": []},
        ]
        self.assertEqual(
            findings(rows),
            [
                ("GET", "/a", "type", "body.a"),
                ("POST", "/b", "unknown_path", "/b"),
            ],
        )

    def test_unparseable_urls_use_an_empty_path(self):
        self.assertEqual(
            findings([{"method": "GET", "url": "http://[", "problems": [["type", "x"]]}]),
            [("GET", "", "type", "x")],
        )


class RatioTest(unittest.TestCase):
    def test_rounding_and_empty_wholes(self):
        self.assertEqual(ratio(1, 3), 0.333333)
        self.assertEqual(ratio(2, 3), 0.666667)
        self.assertEqual(ratio(0, 0), 0.0)
        self.assertEqual(ratio(1, 0), 0.0)


class CodesTest(unittest.TestCase):
    def test_codes_are_the_documented_vocabulary_in_order(self):
        self.assertEqual(
            CODES,
            (
                "unknown_path",
                "method_not_allowed",
                "undocumented_param",
                "missing_param",
                "enum",
                "type",
                "undocumented_field",
                "missing_field",
                "unexpected_body",
                "missing_body",
                "content_type",
            ),
        )


if __name__ == "__main__":
    unittest.main()
