# snippetcheck

Checks every HTTP call in a docs site's code examples against the site's OpenAPI spec: offline, with no API calls
and no model.

It reads MDX pages the way Margin's extractor groups them, finds the curl commands, JavaScript `fetch` calls and
Python `requests`/`httpx` calls inside each code example, matches each call to a spec operation by method and path
template, and then checks what the example actually sends: path values, query parameters, and the request body's
field names, required fields, types and enum values. Every call gets a verdict with the exact problems behind it,
in a shape that can sit next to a docs code example record and gate a docs build: `python -m snippetcheck` exits
non-zero as soon as one example contradicts the spec.

## Why this exists

Margin's public code-example extractor (https://github.com/maniculehq/margin/blob/main/src/ingest/code-examples.ts) says `runnable` is "deliberately NOT emitted (it would be an unvalidated author claim)".

Supermemory's own docs history shows a failure of this shape, in its own words: one commit (short sha `1af9dbc`)
says the old docs "described a route that has never existed", and a docs PR (#1811) reports that a namespace-move
example sent `moveTo` in a body the route ignores, "so following the docs permanently deleted the namespace".

So: from the published spec alone, can every HTTP call in a docs site be checked automatically, and would that have
caught the drift bugs the docs team later fixed? This milestone answers with three measurements, and it states its
limits rather than modelling them away.

## What it measures

1. **Today's report.** Every call to the pinned docs' API host, checked against the pinned v4 and v5 specs, with
   each finding hand-triaged as a spec gap, unconfirmed, or false positive (`study/triage.json`).
2. **Ledger replay.** Real fix commits from the docs repo: each case must be flagged at the buggy version and clean
   at the fixed version (`study/ledger.json`, replayed from `data/history/`).
3. **Seeded drift.** The spec is changed one thing at a time (an operation removed, a field or parameter renamed, a
   field made required, an enum value dropped) and each real clean example is re-checked; neutral changes (an
   optional field added, an enum value added) must flag nothing.

## Results

<!-- snippetcheck:results -->
| metric | value |
|---|---|
| pages | 147 |
| examples | 1018 |
| examples_http | 117 |
| calls | 148 |
| calls_mismatch | 24 |
| findings | 11 |
| triage_spec_gap | 10 |
| triage_unconfirmed | 1 |
| triage_false_positive | 0 |
| ledger_cases | 15 |
| ledger_caught | 15 |
| ledger_recall | 1.0 |
| mutation_breaking_cases | 308 |
| mutation_breaking_caught | 308 |
| mutation_neutral_cases | 99 |
| mutation_neutral_flagged | 0 |
| spec_operations | 75 |
| spec_operations_with_example | 26 |
<!-- /snippetcheck:results -->

That table is generated: `experiment.py` writes `results/metrics.json`, then `demo.py --readme README.md` replaces
the block between the two markers. No result number in this file is typed by hand.

## Running it

The Makefile calls the system `python3`. Run it inside the `ml-py314` environment (Python 3.14), or with any
Python 3.14 interpreter on `PATH`.

```bash
make test         # own tests (tests/) and v1 acceptance tests (tests/acceptance/)
make lint         # ruff check + format check
make data-check   # sha256 of every pinned file against data/MANIFEST.json
make experiment   # python3 experiment.py --out results/metrics.json
make readme       # python3 demo.py --readme README.md --out README.md
make check        # python3 -m snippetcheck over data/docs
```

Directly:

```bash
python -m snippetcheck                     # every page under data/docs
python -m snippetcheck path/to/page.mdx    # just these pages
python -m snippetcheck --docs DIR --json   # another folder, machine-readable
python demo.py                             # scan size, findings, ledger results
python demo.py --readme README.md --out OUT.md
```

Output is one line per call that is not ok, `page:line #index METHOD /path verdict`, then its problems as
`code where` pairs joined by `; `, then a summary line of `N calls: A ok, B partial, C mismatch`. Exit status is 1
when anything mismatches, so docs CI can gate on it.

## What the three verdicts mean

- `ok` — the call matches an operation and everything the checker can see agrees with the spec.
- `partial` — nothing contradicts the spec, but part of the call could not be read: an unparsed body, or a body
  holding a value that is not a literal (a variable, a call). Partial is not a pass.
- `mismatch` — at least one problem: an unknown path, a method the path does not allow, an undocumented or missing
  query parameter, an enum or type violation, an undocumented or missing body field, an unexpected or missing body,
  or a body sent as the wrong content type.

Values that stand for something the spec cannot know are placeholders (`${BASE}`, `{docId}`, `<id>`, `$ID`, or a
non-literal expression) and match every schema. That is deliberately permissive: it keeps false positives down at
the cost of not checking those values at all.

## The ledger selection rule

`study/ledger.json` records the rule under `about`. In short: a case is a docs example whose HTTP call was wrong
before a fix commit and right after it, where the difference is the call itself (method, path, query or body) and
the spec explains it — the buggy version contradicts the pinned spec, the fixed version agrees with it. Fixes that
only changed prose, and bugs that would need the live API to confirm, are excluded with their reasons. Each case
carries `introduced`/`buggy`/`fixed` commits, the page, the expected problem `code` and `where`, and a quote from
the commit.

Replay scans the single page at each of those commits (`data/history/<sha>/<page>`, ten pages in all) and asks
whether the case's exact `(method, operation, code, where)` is present at the buggy commit and absent at the fixed
one. `operation` may be `null`, which is how the cases about a route that never existed are written down.

## Limits, stated plainly

- **SDK examples are not checked.** `client.documents.add(...)`, `withSupermemory(...)` and friends are the largest
  share of the docs' code blocks; mapping SDK methods to operations is out of scope for this milestone.
- **Only found calls are counted.** A URL that is not a literal (`${BASE}/search`, a `baseUrl` variable, a relative
  `fetch('/search')`) is not a call the checker sees, so it is neither checked nor counted in the totals.
- **Only the spec's contract is checked.** Nothing here calls the API, so a spec-gap finding means the docs present
  an endpoint the pinned specs do not describe; it does not mean the endpoint is dead or wrong. A clean result does
  not mean the example would work — only that it does not contradict the spec.
- **Value semantics are out of reach.** A filter expression passed as a JSON string, a nested object whose shape the
  spec leaves open, an SDK call's options: all invisible or unchecked here.
- **The ledger is replayed against today's spec**, not the spec of each case's own day (one spec snapshot per
  version is pinned).

### Honesty about the numbers

The ledger cases were found while exploring the docs history with an early version of this checker; the selection
rule was written down afterwards. The cases come from a handful of fix commits, most of them bugs introduced by one
migration commit and of one kind (options sent as query parameters instead of a JSON body). So the ledger's recall
shows that these problems are real and catchable — it is not an accuracy or recall estimate for the checker.

Of the 15 ledger cases, 12 are the same bug class (`undocumented_param`, options sent as query parameters, counted
from `study/ledger.json`), so the ledger does not show breadth.

The seeded-drift score is near-tautological: the mutations are derived from what each example sends, so the checker
flagging every breaking one (and none of the neutral ones) is a property of the construction. It shows sensitivity,
not discovery, and it is not evidence of accuracy on real mistakes. What the neutral changes add is the
other half — that changes which should not break an example produce no finding.

## Data and licenses

The pinned data under `data/` is never modified, moved or republished by this repo:

- `data/docs/` — the docs pages at a pinned commit of the docs repository, MIT licensed (see `data/docs/LICENSE`).
- `data/history/` — earlier versions of a few of those pages, same license, used only for the ledger replay.
- `data/openapi/v4.json` and `data/openapi/v5.json` — the two public specs the docs reference. They state no
  license, so they are used for analysis only: code, docs and tests may name their paths, fields and counts, but
  nothing here reproduces them.
- `data/MANIFEST.json` — bytes and sha256 of every pinned file; `make data-check` verifies them. Credential-shaped
  placeholders in the fetched docs were replaced on the same line, so line numbers match upstream.

No network access, no model calls and no randomness anywhere in the tests or the experiment, so the whole thing
runs in seconds and gives the same answer twice.
