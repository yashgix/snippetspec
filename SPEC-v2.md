# Spec v2: what changed after the v1 build, and why

The v1 specification (not published here) is unchanged. The 38 v1 acceptance tests in `tests/acceptance/` still run and pass.

## Fixes that bring the build to v1
- Double quotes are tracked when a shell block is split into commands (v1 text: "quoted newlines stay inside a word").
- Body problems are reported at `$.field` (v1: `validate` uses root `$`; the build wrote `body.field` for `check_call`).
- A fetch body that is a `JSON.stringify` of a non-literal is `json` with an unknown value (v1: placeholders match every schema).
- Metric names are written in sorted order.
- Own tests that contradicted v1 or the code under test were corrected.

## Deliberate changes to v1 behaviour
- **A quoting error no longer drops the whole block.** v1: "A quoting error gives no calls for the block." Now only the
  bad command gives no call. Curl commands that could not be read are returned by `unparsed_commands(example)`, counted as
  `unparsed` in the scan result and printed by the CLI. A lone bad command still gives no calls, so the acceptance test
  for it still passes. A quote that is never closed still swallows the lines after it, because the shell would too.
- **`$'...'` strings are decoded** (`\\n \\t \\r \\\\ \\' \\" \\xHH \\uHHHH`) before the words are split. v1 said nothing.
- **`--data-urlencode` is read.** With `-G` it becomes query pairs, otherwise a form body. An `@file` value is unknown.
- **A trailing backslash at the end of a block is ignored.** Found on the hold-out (a sample ends with `\`); fixed after
  the first hold-out run, with a regression test. This changed one count (an unreadable command became a call).

## Changes after an independent review (parser, not tuned on the hold-out)
- An explicit `Content-Type` (curl `-H` or `--json`, fetch `headers`, requests/httpx `headers=`) is kept on the call and
  must be a media type the operation declares, else `content_type` at `body:<media>`. A `+json` type counts as JSON.
  Before, the payload's shape decided and a `text/plain` header passed.
- fetch is found only in code: comments and string contents are blanked before the search. v1 said comments are skipped.
- Every URL of a curl command is a call (v1: "the first one, or `--url`, is used").
- requests and httpx: `files`, then `data`, win over `json`, which is the fallback when both are empty (v1: `json=`
  wins). httpx `content=` wins over all. List params repeat the name, `None` is dropped by requests and empty in
  httpx, bool text differs (`True` vs `true`). Sources are named in `docs/DESIGN.md`.
- NOT changed: matching the concrete path before filtering by method. The review is right about OpenAPI path templating
  but v1 and an acceptance test (`GET /items/search/` must reach `GET /items/{id}` when `/items/search` only has POST)
  require the method to filter first. Left as it is and listed as a limit.
- Effect: the v1 numbers are unchanged. On the hold-out, calls, flagged calls, unreadable commands and recall are
  unchanged (216, 114, 2, 24 of 24). Four findings only changed text from `body:json` to `body:application/json`.
  The hold-out cases were not edited. These parser changes came from reading the code, not from the hold-out results,
  apart from the earlier trailing-backslash fix.

## Not done: shlex `punctuation_chars`
Tried before deciding. It drops the newline after a trailing comment, so the next command merges into the previous
one, and one quoting error ends the whole token stream. The small quote-aware splitter stays, with shlex splitting each
command.

## The hold-out
Why: every v1 number comes from Supermemory, which the checker was built on.
What: Meilisearch's published OpenAPI spec and its docs code samples (MIT), pinned in `data/holdout/` and listed in
`data/holdout/MANIFEST.json`. The docs are at a commit from the same month as the spec, so the two agree in time.
`tools/fetch_holdout.py` fetches and verifies by sha256. `MEILISEARCH_URL` in the samples is replaced by a host before
checking (`snippetcheck/holdout.py`).
Method: 24 hand-written cases (`study/holdout_cases.json`), each one change to one sample, with the expected problem
written from the spec before the checker was run on the hold-out. The case file's sha256 is in `study/holdout_cases.sha256`
and is tested. Caught means the expected problem is in the broken page and not in the original.
Numbers: `results/holdout.json`, summarised in the README. They are not copied here.
Limits: the cases were chosen and broken by one person who knew the spec, so recall is an upper bound of the kind
"easy changes to known fields". No real fixed Meilisearch docs bugs were collected. The spec is stricter than the
API in ways that flag working samples, so precision on clean docs is poor for this spec. Nothing was changed to improve
it, because the data would then no longer be a hold-out.

## Still out of scope (listed limits)
`allOf`, `oneOf` exclusivity, and `format`, `pattern`, `minimum` and length constraints. SDK calls. A TypeScript port.
Server base paths in the spec (`servers[].url`). Concrete-path-before-method precedence (see above). Comma-separated array query values (read as one value).
