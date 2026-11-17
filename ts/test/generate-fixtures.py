"""Capture reference results; run from the repository root with Python 3.14+."""

import importlib.util
import json
import os
import subprocess
import sys
import unittest
from dataclasses import asdict
from pathlib import Path

sys.dont_write_bytecode = True
sys.path.insert(0, str(Path.cwd()))
from snippetspec.holdout import _scan, load_holdout  # noqa: E402
from snippetspec.jsread import UNKNOWN  # noqa: E402

FIXTURES = Path("ts/test/fixtures")


def write(name, value):
    FIXTURES.joinpath(name).write_text(json.dumps(value, indent=1) + "\n")


def encode(value):
    if isinstance(value, type(UNKNOWN)):
        return {"$unknown": True}
    if isinstance(value, dict):
        return {key: encode(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [encode(item) for item in value]
    return value


def module(name):
    spec = importlib.util.spec_from_file_location(name, f"tests/{name}.py")
    result = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(result)
    return result


def run(tests):
    result = unittest.TextTestRunner().run(unittest.defaultTestLoader.loadTestsFromModule(tests))
    if not result.wasSuccessful():
        raise RuntimeError("Reference unit tests failed")


def capture_calls():
    tests = module("test_calls")
    original = tests.find_calls
    cases = {}

    def record(example):
        calls = original(example)
        cases[(example.code, example.language)] = {
            "code": example.code,
            "language": example.language,
            "calls": [encode(asdict(call)) for call in calls],
            "unparsed": tests.unparsed_commands(example),
        }
        return calls

    tests.find_calls = record
    run(tests)
    write("calls.json", list(cases.values()))


def capture_checks():
    tests = module("test_check")
    original_check = tests.check_call
    original_validate = tests.validate
    checks, validations = [], []

    def check(specs, ops, call):
        result = original_check(specs, ops, call)
        checks.append(encode({"specs": specs, "call": asdict(call), "result": result}))
        return result

    def validate(spec, schema, value, where="$"):
        result = original_validate(spec, schema, value, where)
        validations.append(encode({"spec": spec, "schema": schema, "value": value, "where": where, "result": result}))
        return result

    tests.check_call = check
    tests.validate = validate
    run(tests)
    write("checks.json", checks)
    write("validation.json", validations)


if __name__ == "__main__":
    FIXTURES.mkdir(exist_ok=True)
    result = subprocess.run(
        [sys.executable, "-m", "snippetspec", "--json"],
        capture_output=True,
        text=True,
        env={**os.environ, "PYTHONDONTWRITEBYTECODE": "1"},
    )
    if result.returncode != 1:
        raise RuntimeError(result.stderr or "Expected pinned docs mismatches")
    FIXTURES.joinpath("supermemory.json").write_text(result.stdout)
    write("meilisearch.json", _scan(*load_holdout()))
    capture_calls()
    capture_checks()
