# snippetspec

Checks the curl, JavaScript `fetch` and Python `requests`/`httpx` examples in API documentation against the OpenAPI
spec. Offline, with no API calls and no model.

Write-up with a diagram and charts: https://yashgix.github.io/snippetspec/

Renamed from `snippetcheck` on 16 Nov 2026. Frozen specs and git tags keep the old name.

It reads MDX pages, finds each HTTP call inside the code examples, matches it to a spec operation by method and path
template, and then checks what the example sends: path values, query parameters, and the request body's field names,
required fields, types and enum values. Every call gets a verdict with the exact problems behind it, and
`python -m snippetspec` exits non-zero as soon as one example contradicts the spec, so it can gate a docs build.

Main result, with its qualifier: on Supermemory's docs it flags all 15 real docs fixes from their history at the
buggy commit and none at the fixed one, and today's docs hold 11 findings, 10 of them endpoints the pinned specs do not
describe. That is a sensitivity check on bugs found while building the tool, not an accuracy estimate. On a second
API (Meilisearch) it caught all 24 hand-broken examples, but 114 of 216 untouched published examples (53%) are
flagged. In the flags sampled, the cause is that the spec is stricter than its own docs (runtime not confirmed). If
those docs are right, that is a 53% false-positive rate on that spec.

```text
$ python -m snippetspec data/docs/authentication.mdx
data/docs/authentication.mdx:69 #0 POST /auth/scoped-key mismatch unknown_path /auth/scoped-key
data/docs/authentication.mdx:114 #0 DELETE /auth/scoped-key/KEY_ID mismatch unknown_path /auth/scoped-key/KEY_ID
3 calls: 1 ok, 0 partial, 2 mismatch
```

## Why this exists

Docs examples drift from the API they describe. Supermemory's docs history shows it in its own words: one commit
(short sha `1af9dbc`) says the old docs "described a route that has never existed", and a docs PR (#1811) reports that
a namespace-move example sent `moveTo` in a body the route ignores, "so following the docs permanently deleted the
namespace". The question here: from the published spec alone, can every HTTP call in a docs site be checked
automatically, and would that have caught the drift bugs the docs team later fixed? The extractor groups code blocks
the way Margin's does (https://github.com/maniculehq/margin/blob/main/src/ingest/code-examples.ts), so its output can
sit next to a docs code-example record.

## What it measures

1. **Today's report.** Every call to the pinned docs' API host, checked against the pinned v4 and v5 specs, with
   each finding hand-triaged as a spec gap, unconfirmed, or false positive (`study/triage.json`).
2. **Ledger replay.** Real fix commits from the docs repo: each case must be flagged at the buggy version and clean
   at the fixed version (`study/ledger.json`, replayed from `data/history/`).
3. **Seeded drift.** The spec is changed one thing at a time (an operation removed, a field or parameter renamed, a
   field made required, an enum value dropped) and each real clean example is re-checked. Neutral changes (an
   optional field added, an enum value added) must flag nothing.

## Results

<!-- snippetspec:results -->
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
<!-- /snippetspec:results -->

That table is generated: `experiment.py` writes `results/metrics.json`, then `demo.py --readme README.md` replaces
the block between the two markers. The tables are generated. The numbers in the summary at the top are copied from them.

## Running it

Needs Python 3.14 and no packages (`ruff` for `make lint`). The Makefile calls `python3`. The two Supermemory specs
are not in the repository (see Data and licenses), so fetch them once first:

```bash
python3 tools/fetch_data.py   # rebuilds data/openapi/ and checks every pinned file against data/MANIFEST.json
make holdout      # python3 -m snippetspec.holdout, writes results/holdout.json
make test         # own tests (tests/) and v1 acceptance tests (tests/acceptance/)
make lint         # ruff check + format check
make data-check   # sha256 of every pinned file against data/MANIFEST.json
make experiment   # python3 experiment.py --out results/metrics.json
make readme       # python3 demo.py --readme README.md --out README.md
make check        # python3 -m snippetspec over data/docs
python3 tools/build_page.py   # rebuilds docs/index.html from results/
```

Directly:

```bash
python -m snippetspec                      # every page under data/docs
python -m snippetspec path/to/page.mdx     # just these pages
python -m snippetspec --docs DIR --json    # another folder, machine-readable
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
  share of the docs' code blocks. Mapping SDK methods to operations is out of scope for this milestone.
- **Only found calls are counted.** A URL that is not a literal (`${BASE}/search`, a `baseUrl` variable, a relative
  `fetch('/search')`) is not a call the checker sees, so it is neither checked nor counted in the totals.
- **Only the spec's contract is checked.** Nothing here calls the API, so a spec-gap finding means the docs present
  an endpoint the pinned specs do not describe. It does not mean the endpoint is dead or wrong. A clean result does
  not mean the example would work — only that it does not contradict the spec.
- **Value semantics are out of reach.** A filter expression passed as a JSON string, a nested object whose shape the
  spec leaves open, an SDK call's options: all invisible or unchecked here.
- **Method-filtered path matching.** When a concrete path exists without the call's method (for example
  `/items/search` only has POST and the call is `GET /items/search`), the checker falls back to a templated path
  (`/items/{id}`). OpenAPI's matching rule would match the concrete path first and report a method mismatch. The
  fallback comes from the v1 spec and an acceptance test, and is left as it is. It can hide a wrong-method call.
- **The ledger is replayed against today's spec**, not the spec of each case's own day (one spec snapshot per
  version is pinned).

### Hold-out: another API's docs

The three measurements above all use Supermemory, the data the checker was built on. To see how it does elsewhere,
`data/holdout/` pins Meilisearch's published OpenAPI spec and its docs code samples (both MIT, fetched by
`tools/fetch_holdout.py` with sha256 checksums, the docs at a commit from the same month as the spec).
`make holdout` runs two measurements and writes `results/holdout.json`:

1. **Clean docs.** Every curl sample as published, with the docs' `MEILISEARCH_URL` placeholder given a host.
2. **Hand-broken examples.** 24 cases in `study/holdout_cases.json`, each one documented change to one real sample
   (a misspelled route, a wrong method, a renamed field, a number written as a word, a body on a route that takes
   none). The list and its expected problems were written from the spec before the checker was run on any of them,
   and its sha256 is pinned in `study/holdout_cases.sha256`. A case counts as caught only when the expected problem
   appears in the broken page and not in the original.

<!-- snippetspec:holdout -->
| hold-out metric | value |
|---|---|
| pages | 245 |
| calls | 216 |
| calls_mismatch | 114 |
| unparsed_commands | 2 |
| cases | 24 |
| caught | 24 |
| recall, body-field | 5 of 5 |
| recall, body-type | 4 of 4 |
| recall, method | 3 of 3 |
| recall, placement | 2 of 2 |
| recall, query | 5 of 5 |
| recall, route | 5 of 5 |
<!-- /snippetspec:holdout -->

How to read it:

- **Recall on the hand-broken cases is high, but it is the same kind of test as the seeded drift.** One change to one
  field is easy to see for a checker that knows the spec. It shows the checker works on a second API, not that it finds
  real mistakes in the wild. No real, later-fixed Meilisearch docs bugs were collected in this milestone.
- **Many clean samples are flagged. In the flags I sampled, the cause is a spec-versus-doc disagreement, runtime not
  confirmed.** Meilisearch's spec is generated from code and differs from the samples in repeating ways: it lists many
  fields, query parameters and request bodies as required that the samples leave out, names some fields in snake case
  where the samples use camel case, gives a plain-string body a `text/plain` type, lists ranking rules capitalised,
  and expects repeated query parameters where the samples use comma lists. The checker applies the spec as written.
  I did not run any sample against a Meilisearch server, so I cannot say which side is right. A spec like this would
  make the checker noisy until its required lists are fixed.
- **The false-positive rate on this spec is high.** If the published samples are right, 114 of 216 (53%) are false
  alarms. None of the 114 is confirmed either way. `docs/MISMATCH-SPLIT.md` is a post-hoc split of the flagged calls
  on both APIs, kept apart from the method.
- **The parser changed after the first hold-out run, and again after an independent review.** One fix (a trailing
  backslash at the end of a block) came from reading the first hold-out output. The review fixes (explicit
  Content-Type, comments and strings in JavaScript, every URL in a curl command, requests and httpx body and query
  rules) came from reading the code, not the hold-out. The 24 cases stayed frozen, the checker was not tuned to
  flag more or fewer samples, and the review changes did not move the hold-out counts above.
- **What it did find that is real.** Two samples have an unclosed quote in their curl command, so no shell can run them
  (`code_samples_get_all_tasks_paginating_1.mdx` and `_2`). The scan reports these as unreadable commands rather than
  skipping them silently. One sample posts to `documents/delete-batch`, which the spec does not list (the checker reads the last segment as a document id and reports a method mismatch).

### Honesty about the numbers

The ledger cases were found while exploring the docs history with an early version of this checker. The selection
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

The code is MIT (`LICENSE`). The pinned data under `data/` is never modified by this repo.

- `data/docs/` and `data/history/` — Supermemory's docs pages at a pinned commit, and earlier versions of ten of them
  for the ledger replay. MIT, copyright supermemory (`data/docs/LICENSE`).
- `data/holdout/` — Meilisearch's OpenAPI spec and docs code samples, both MIT, with their license files beside them
  (`data/holdout/spec/LICENSE`, `data/holdout/docs/LICENSE`). Rebuilt by `tools/fetch_holdout.py`.
- `data/openapi/v4.json` and `data/openapi/v5.json` — Supermemory's two public API specs. They state no license, so
  they are not in this repository or its history. `python3 tools/fetch_data.py` downloads them and checks sha256 against
  `data/MANIFEST.json`. The live specs may change, in which case the check reports a mismatch instead of hiding it.
  Until you fetch them, the experiment and the tests that need them cannot run.
- `data/MANIFEST.json` — bytes and sha256 of every pinned file. `make data-check` verifies them. Credential-shaped
  placeholders in the fetched docs were replaced on the same line, so line numbers match upstream.

No network access, no model calls and no randomness anywhere in the tests or the experiment (only the fetch scripts
use the network), so the whole thing runs in seconds and gives the same answer twice.

Built with Arcturus (Claude Code builders, Codex review). Reviewed and verified by hand.
