"""Fetch or verify the pinned data: Supermemory's docs pages and its two public OpenAPI specs.

python tools/fetch_data.py            fetch every file listed in data/MANIFEST.json, redact, then verify
python tools/fetch_data.py --verify   check every file's sha256 against the manifest (no network)
"""

import argparse
import hashlib
import json
import re
import sys
import urllib.request
from pathlib import Path

DATA = Path(__file__).resolve().parent.parent / "data"
MANIFEST = DATA / "MANIFEST.json"
# Credential-shaped text (docs placeholders that assign a value to a NAME_API_KEY variable, or AWS's example
# key id) is replaced on the same line, so no pinned file looks like a secret to a key scanner.
SECRET = re.compile(
    r"sk-[A-Za-z0-9_-]{20,}|gh[pousr]_[A-Za-z0-9]{30,}|xox[abpr]-[A-Za-z0-9-]{10,}|AKIA[0-9A-Z]{16}"
    r"|-----BEGIN [A-Z ]*PRIVATE KEY-----|[A-Z0-9_]*(?:TOKEN|SECRET|API_KEY|PASSWORD)=[^\s\"']{8,}"
)


def placeholder(found):
    text = found.group()
    if "=" in text and not text.startswith(("sk-", "AKIA")):
        return text.split("=", 1)[0] + "=<x>"
    return "AKIA-EXAMPLE" if text.startswith("AKIA") else "<redacted>"


def redact(data):
    """(bytes, number of replacements); line numbers never change."""
    text, count = SECRET.subn(placeholder, data.decode())
    return text.encode(), count


def sha256(data):
    return hashlib.sha256(data).hexdigest()


def fetch(manifest):
    for name, row in manifest["files"].items():
        target = DATA / name
        target.parent.mkdir(parents=True, exist_ok=True)
        with urllib.request.urlopen(row["url"], timeout=60) as response:
            target.write_bytes(redact(response.read())[0])


def verify(manifest):
    bad = [
        name
        for name, row in manifest["files"].items()
        if not (DATA / name).is_file() or sha256((DATA / name).read_bytes()) != row["sha256"]
    ]
    for name in bad:
        print(f"mismatch: {name}", file=sys.stderr)
    print(f"{len(manifest['files']) - len(bad)} of {len(manifest['files'])} files match the manifest")
    return not bad


def main():
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--verify", action="store_true", help="only check sha256, no network")
    args = parser.parse_args()
    manifest = json.loads(MANIFEST.read_text())
    if not args.verify:
        # The live specs change over time; a re-fetch that no longer matches is reported, not hidden.
        fetch(manifest)
    sys.exit(0 if verify(manifest) else 1)


if __name__ == "__main__":
    main()
