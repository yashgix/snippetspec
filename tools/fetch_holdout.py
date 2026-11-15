"""Fetch or verify the hold-out data: Meilisearch's public OpenAPI spec and its docs code samples, both MIT.

python tools/fetch_holdout.py --build   list the sample pages, fetch everything and write data/holdout/MANIFEST.json
python tools/fetch_holdout.py           fetch every file listed in the manifest, then verify
python tools/fetch_holdout.py --verify  check every file's sha256 against the manifest (no network)
"""

import argparse
import json
import sys
import urllib.request
from pathlib import Path

from fetch_data import redact, sha256

HOLDOUT = Path(__file__).resolve().parent.parent / "data" / "holdout"
MANIFEST = HOLDOUT / "MANIFEST.json"
SPEC_REPO, SPEC_COMMIT = "meilisearch/open-api", "0b0b0fdbb9d5821ec018a3db2777986a231eec37"
DOCS_REPO, DOCS_COMMIT = "meilisearch/documentation", "0d5f1df19e581c57981b37e3e7333080ac5ede0f"
SAMPLES = "snippets/samples/"


def raw(repo, commit, path):
    return f"https://raw.githubusercontent.com/{repo}/{commit}/{path}"


def download(url):
    with urllib.request.urlopen(url, timeout=60) as response:
        return response.read()


def sample_pages():
    url = f"https://api.github.com/repos/{DOCS_REPO}/git/trees/{DOCS_COMMIT}?recursive=1"
    tree = json.loads(download(url))["tree"]
    return sorted(item["path"] for item in tree if item["path"].startswith(SAMPLES) and item["path"].endswith(".mdx"))


def planned():
    """{local name: url}: both licenses, the spec and every sample page."""
    files = {
        "spec/LICENSE": raw(SPEC_REPO, SPEC_COMMIT, "LICENSE"),
        "spec/openapi.json": raw(SPEC_REPO, SPEC_COMMIT, "open-api.json"),
        "docs/LICENSE": raw(DOCS_REPO, DOCS_COMMIT, "LICENSE"),
    }
    files.update({f"docs/{path.removeprefix(SAMPLES)}": raw(DOCS_REPO, DOCS_COMMIT, path) for path in sample_pages()})
    return files


def fetch(urls):
    """Download, redact and write each file; the rows describe what was written."""
    rows = {}
    for name, url in urls.items():
        data, redactions = redact(download(url))
        (HOLDOUT / name).parent.mkdir(parents=True, exist_ok=True)
        (HOLDOUT / name).write_bytes(data)
        rows[name] = {"url": url, "bytes": len(data), "sha256": sha256(data), "redactions": redactions}
    return rows


def verify(manifest):
    bad = [
        name
        for name, row in manifest["files"].items()
        if not (HOLDOUT / name).is_file() or sha256((HOLDOUT / name).read_bytes()) != row["sha256"]
    ]
    for name in bad:
        print(f"mismatch: {name}", file=sys.stderr)
    print(f"{len(manifest['files']) - len(bad)} of {len(manifest['files'])} files match the manifest")
    return not bad


def main():
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--build", action="store_true", help="write the manifest from the pinned commits")
    parser.add_argument("--verify", action="store_true", help="only check sha256, no network")
    args = parser.parse_args()
    if args.build:
        files = fetch(planned())
        note = (
            "Both repositories are MIT licensed (see spec/LICENSE and docs/LICENSE). Pinned to commits from June 2025."
        )
        MANIFEST.write_text(json.dumps({"note": note, "files": files}, indent=1, sort_keys=True) + "\n")
    manifest = json.loads(MANIFEST.read_text())
    if not (args.verify or args.build):
        fetch({name: row["url"] for name, row in manifest["files"].items()})
    sys.exit(0 if verify(manifest) else 1)


if __name__ == "__main__":
    main()
