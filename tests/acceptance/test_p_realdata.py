import contextlib
import hashlib
import io
import json
import tempfile
import unittest
from pathlib import Path

from snippetcheck.__main__ import main as cli
from snippetcheck.data import DATA, HOST, ROOT, SPECS, STUDY, load_json, load_pages, load_specs
from snippetcheck.history import days_open, evaluate, problem_ids
from snippetcheck.metrics import findings
from snippetcheck.report import page_calls, scan
from snippetcheck.spec import operations

FINDINGS = [
    ("DELETE", "/auth/scoped-key/KEY_ID", "unknown_path", "/auth/scoped-key/KEY_ID"),
    ("GET", "/v3/analytics/errors", "unknown_path", "/v3/analytics/errors"),
    ("GET", "/v3/analytics/logs", "unknown_path", "/v3/analytics/logs"),
    ("GET", "/v3/analytics/usage", "unknown_path", "/v3/analytics/usage"),
    ("GET", "/v3/auth/billing", "unknown_path", "/v3/auth/billing"),
    ("GET", "/v3/auth/billing/usage", "unknown_path", "/v3/auth/billing/usage"),
    ("GET", "/v3/auth/billing/usage-events", "unknown_path", "/v3/auth/billing/usage-events"),
    ("GET", "/v3/container-tags/user_123/inferred", "unknown_path", "/v3/container-tags/user_123/inferred"),
    ("POST", "/auth/scoped-key", "unknown_path", "/auth/scoped-key"),
    (
        "POST",
        "/v3/container-tags/user_123/inferred/mem_abc123/review",
        "unknown_path",
        "/v3/container-tags/user_123/inferred/mem_abc123/review",
    ),
    ("POST", "/v3/documents/documents", "method_not_allowed", "DELETE,GET,PATCH"),
]
SCALARS = {
    "pages": 147,
    "examples": 1018,
    "examples_http": 117,
    "examples_validated": 95,
    "calls": 148,
    "calls_other_host": 11,
    "calls_curl": 134,
    "calls_fetch": 11,
    "calls_requests": 3,
    "calls_ok": 124,
    "calls_partial": 0,
    "calls_mismatch": 24,
    "problems_unknown_path": 21,
    "problems_method_not_allowed": 3,
    "problems_undocumented_param": 0,
    "problems_missing_param": 0,
    "problems_enum": 0,
    "problems_type": 0,
    "problems_undocumented_field": 0,
    "problems_missing_field": 0,
    "problems_unexpected_body": 0,
    "problems_missing_body": 0,
    "problems_content_type": 0,
    "spec_operations": 75,
    "spec_operations_with_example": 26,
    "mismatch_endpoints": 11,
    "findings": 11,
    "triage_spec_gap": 10,
    "triage_unconfirmed": 1,
    "triage_false_positive": 0,
    "triage_untriaged": 0,
    "ledger_cases": 15,
    "ledger_introduced_detected": 15,
    "ledger_detected": 15,
    "ledger_cleared": 15,
    "ledger_caught": 15,
    "ledger_recall": 1.0,
}
MUTATIONS = {
    "remove_operation": (124, 124),
    "rename_field": (80, 80),
    "add_required": (45, 45),
    "drop_enum_value": (25, 25),
    "rename_param": (34, 34),
    "add_optional": (57, 0),
    "add_enum_value": (42, 0),
}
DAYS = [124, 162, 9, 9, 9, 9, 9, 9, 9, 9, 9, 9, 9, 9, 9]
STATE = {}


def load_experiment():
    if "result" not in STATE:
        import importlib.util

        spec = importlib.util.spec_from_file_location("experiment_module", ROOT / "experiment.py")
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        STATE["module"] = module
        STATE["result"] = module.experiment()
    return STATE["module"], STATE["result"]


def today():
    if "scan" not in STATE:
        STATE["specs"] = load_specs()
        STATE["pages"] = load_pages(DATA / "docs")
        STATE["scan"] = scan(STATE["pages"], STATE["specs"])
    return STATE["scan"]


class Data(unittest.TestCase):
    def test_manifest_checksums(self):
        self.assertTrue(
            (DATA / "MANIFEST.json").is_file(), f"missing {DATA / 'MANIFEST.json'}: the pinned data is required"
        )
        manifest = load_json(DATA / "MANIFEST.json")
        self.assertEqual(len(manifest["files"]), 181)
        self.assertEqual(sum(row["bytes"] for row in manifest["files"].values()), 1592274)
        for name, row in manifest["files"].items():
            self.assertEqual(hashlib.sha256((DATA / name).read_bytes()).hexdigest(), row["sha256"], name)
        self.assertEqual(manifest["sources"]["docs"]["commit"], "03d9dd1c0ed35e35dfd57794c5440461d3c74f61")

    def test_study_files_are_pinned(self):
        digests = {
            "ledger.json": "374c6ff6a1f8fb76f67c788c99b0e547ce74c3dfeff8c51a779e0e00449a9d39",
            "triage.json": "ac442de5fe56e296b0483c7c3645bb5df487926251e0b1782837fba07d245eb8",
        }
        for name, digest in digests.items():
            self.assertEqual(hashlib.sha256((STUDY / name).read_bytes()).hexdigest(), digest, name)

    def test_loaders(self):
        specs = load_specs()
        self.assertEqual(list(specs), list(SPECS))
        self.assertEqual(SPECS, ("v4", "v5"))
        self.assertEqual(HOST, "api.supermemory.ai")
        self.assertEqual([len(operations([(n, s)])) for n, s in specs.items()], [42, 33])
        pages = load_pages(DATA / "docs")
        self.assertEqual(len(pages), 147)
        self.assertEqual(list(pages), sorted(pages))
        self.assertIn("v5/api-reference/ingest.mdx", pages)
        self.assertEqual(ROOT / "data", DATA)


class NoSecrets(unittest.TestCase):
    def test_no_repo_file_looks_like_a_secret(self):
        import importlib.util

        spec = importlib.util.spec_from_file_location("fetch_module", ROOT / "tools" / "fetch_data.py")
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        hits = []
        for path in sorted(ROOT.rglob("*")):
            if not path.is_file() or {".git", "__pycache__", ".ruff_cache", "node_modules"} & set(path.parts):
                continue
            text = path.read_text(errors="replace")
            texts = [text]
            if path.suffix == ".json":
                texts += strings(json.loads(text))
            hits += [str(path.relative_to(ROOT)) for t in texts if module.SECRET.search(t)]
        self.assertEqual(hits, [])
        manifest = load_json(DATA / "MANIFEST.json")
        self.assertEqual(sum(row["redactions"] for row in manifest["files"].values()), 30)


def strings(value):
    if isinstance(value, str):
        return [value]
    if isinstance(value, dict):
        return [s for k, v in value.items() for s in [k, *strings(v)]]
    return [s for v in value for s in strings(v)] if isinstance(value, list) else []


class TodayScan(unittest.TestCase):
    def test_headline_counts(self):
        report = today()
        rows = report["calls"]
        self.assertEqual((report["pages"], report["examples"], report["other_host"], len(rows)), (147, 1018, 11, 148))
        self.assertEqual([sum(r["verdict"] == v for r in rows) for v in ("ok", "partial", "mismatch")], [124, 0, 24])
        self.assertEqual([sum(r["tool"] == t for r in rows) for t in ("curl", "fetch", "requests")], [134, 11, 3])
        self.assertEqual(len(page_calls(STATE["pages"])), 148)

    def test_findings(self):
        self.assertEqual(findings(today()["calls"]), FINDINGS)

    def test_specific_rows(self):
        rows = {(r["page"], r["line"], r["index"]): r for r in today()["calls"]}
        graph = rows[("integrations/memory-graph.mdx", 85, 0)]
        self.assertEqual(
            (graph["tool"], graph["method"], graph["operation"], graph["verdict"], graph["problems"]),
            ("fetch", "POST", None, "mismatch", [["method_not_allowed", "DELETE,GET,PATCH"]]),
        )
        billing = [rows[("overview/billing.mdx", 308, i)]["url"] for i in range(3)]
        self.assertEqual(
            [u.rsplit("/v3/", 1)[1] for u in billing],
            ["auth/billing", "auth/billing/usage", "auth/billing/usage-events"],
        )
        listing = rows[("ingestion/document-operations.mdx", 35, 0)]
        self.assertEqual(
            (listing["operation"], listing["verdict"], listing["group"], listing["language"]),
            ("v5:POST /ns/{namespace}/list/{type}", "ok", 0, "bash"),
        )
        upload = [r for r in rows.values() if r["page"] == "ingestion/add-memories.mdx" and r["line"] == 168]
        self.assertEqual(
            [(r["operation"], r["verdict"]) for r in upload], [("v5:POST /ns/{namespace}/document/file", "ok")]
        )

    def test_operations_with_examples(self):
        matched = {r["operation"] for r in today()["calls"] if r["operation"]}
        self.assertEqual(len(matched), 26)
        self.assertIn("v5:POST /ns/{namespace}/search", matched)
        self.assertTrue(all(op.startswith("v5:") for op in matched))

    def test_cli_on_the_pinned_docs(self):
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            code = cli([])
        lines = out.getvalue().splitlines()
        self.assertEqual(code, 1)
        self.assertEqual(lines[-1], "148 calls: 124 ok, 0 partial, 24 mismatch")
        self.assertEqual(len(lines), 25)
        self.assertIn(
            "overview/billing.mdx:308 #2 GET /v3/auth/billing/usage-events mismatch unknown_path "
            "/v3/auth/billing/usage-events",
            lines,
        )
        with contextlib.redirect_stdout(io.StringIO()) as raw:
            cli(["--json", str(DATA / "docs" / "quickstart.mdx")])
        self.assertEqual(len(json.loads(raw.getvalue())["calls"]), 6)


class Ledger(unittest.TestCase):
    def test_every_case(self):
        ledger = load_json(STUDY / "ledger.json")
        specs = load_specs()
        self.assertEqual(len(ledger["cases"]), 15)
        self.assertEqual(len(ledger["excluded"]), 7)
        for case in ledger["cases"]:
            self.assertEqual(
                evaluate(case, DATA / "history", specs),
                {"id": case["id"], "introduced_detected": True, "detected": True, "cleared": True, "caught": True},
            )
        self.assertEqual([days_open(c, ledger["commits"]) for c in ledger["cases"]], DAYS)

    def test_problem_ids_at_a_buggy_commit(self):
        page = "concepts/container-tags.mdx"
        text = (DATA / "history" / "4347970" / page).read_text()
        ids = problem_ids(scan({page: text}, load_specs())["calls"])
        self.assertIn(("DELETE", "v5:DELETE /ns/{namespace}", "unexpected_body", "body"), ids)
        fixed = (DATA / "history" / "2197c04" / page).read_text()
        self.assertEqual(problem_ids(scan({page: fixed}, load_specs())["calls"]), set())
        old = (DATA / "history" / "7d1428e" / "memory-operations.mdx").read_text()
        ids = problem_ids(scan({"memory-operations.mdx": old}, load_specs())["calls"])
        self.assertIn(("POST", None, "unknown_path", "/v4/memories/mem_abc123/forget"), ids)

    def test_a_missed_case_is_reported(self):
        case = {
            "id": "x",
            "page": "connectors/s3.mdx",
            "introduced": "4850856",
            "buggy": "62ac31e",
            "fixed": "0b50816",
            "method": "POST",
            "operation": "v4:POST /v3/connections/{provider}",
            "code": "enum",
            "where": "$.x",
        }
        self.assertEqual(
            evaluate(case, DATA / "history", load_specs()),
            {"id": "x", "introduced_detected": False, "detected": False, "cleared": True, "caught": False},
        )
        unfixed = {**load_json(STUDY / "ledger.json")["cases"][0], "fixed": "62ac31e"}
        self.assertEqual(
            evaluate(unfixed, DATA / "history", load_specs()),
            {"id": "s3-config-shape", "introduced_detected": True, "detected": True, "cleared": False, "caught": False},
        )


class Experiment(unittest.TestCase):
    def test_metric_names_and_values(self):
        metrics, details = load_experiment()[1]
        self.assertEqual(len(metrics), 57)
        self.assertEqual(list(metrics), sorted(metrics))
        self.assertEqual({k: metrics[k] for k in SCALARS}, SCALARS)
        self.assertEqual(metrics["ledger_days_open"], DAYS)
        self.assertEqual(set(details), {"calls", "ledger", "mutations"})
        self.assertEqual(len(details["calls"]), 148)

    def test_mutation_counts(self):
        metrics = load_experiment()[1][0]
        for kind, (cases, hits) in MUTATIONS.items():
            suffix = "flagged" if kind.startswith("add_") and kind != "add_required" else "caught"
            self.assertEqual(
                (metrics[f"mutation_{kind}_cases"], metrics[f"mutation_{kind}_{suffix}"]), (cases, hits), kind
            )
        self.assertEqual(
            (
                metrics["mutation_breaking_cases"],
                metrics["mutation_breaking_caught"],
                metrics["mutation_breaking_recall"],
            ),
            (308, 308, 1.0),
        )
        self.assertEqual((metrics["mutation_neutral_cases"], metrics["mutation_neutral_flagged"]), (99, 0))

    def test_mutation_rows(self):
        rows = load_experiment()[1][1]["mutations"]
        self.assertEqual(len(rows), 407)
        self.assertEqual(rows[0]["operation"], "v5:POST /ns/{namespace}/search")
        renamed = [r for r in rows if r["mutation"] == "rename_param:limit"]
        self.assertEqual(
            {r["operation"] for r in renamed},
            {"v5:POST /ns/{namespace}/list/{type}"},
        )
        self.assertTrue(all(r["codes"] == ["undocumented_param"] for r in renamed))

    def test_main_is_byte_identical(self):
        module = load_experiment()[0]
        outputs = []
        for _ in range(2):
            with tempfile.TemporaryDirectory() as tmp:
                path = Path(tmp) / "deep" / "metrics.json"
                module.main(["--out", str(path)])
                outputs.append((path.read_bytes(), (path.parent / "details.json").read_bytes()))
        self.assertEqual(outputs[0], outputs[1])
        self.assertTrue(outputs[0][0].endswith(b"}\n"))
        self.assertEqual(json.loads(outputs[0][0]), load_experiment()[1][0])


if __name__ == "__main__":
    unittest.main()
