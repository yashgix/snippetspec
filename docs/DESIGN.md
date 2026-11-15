# Design notes

`snippetcheck` answers one question offline: do the HTTP calls a docs site prints agree with the OpenAPI spec the
site references? This file records how it does that, and why each decision went the way it did. It is not a user
guide; that is `README.md`.

## The pipeline

```
data/docs/*.mdx --mdx.extract-----> Example(page, line, language, title, meta, code, group)
Example         --calls.find_calls> Call(tool, method, url, query, body_kind, body)
data/openapi    --spec.operations-> Operation(spec, method, template, op)
Call + ops      --check.check_call> {operation, problems}
pages + specs   --report.scan-----> rows with verdict and problems
```

Each stage hands the next a plain, frozen value; nothing downstream re-parses text. That keeps the parsers boring
and the checks testable in isolation: `tests/test_calls.py` never needs a spec, `tests/test_check.py` never needs
MDX.

## Extraction (`mdx.py`)

The pages are MDX, so code lives in fenced blocks. Extraction is a line scanner rather than a Markdown library
because three properties matter more than completeness:

- **Nothing inside a block is read as markup.** Lines between fences are never inspected for tags, so a block that
  shows `<Tabs>` does not open a group.
- **Indentation is preserved per block.** Each content line loses up to the opening fence's indent, which
  reproduces the author's code without guessing at intent.
- **Fence length is respected.** An opening fence of four backticks contains three-backtick lines, so examples that
  embed examples survive.

`language` is the info string's first word, defaulting to `text`; `meta` is the rest; `title` follows Margin's
precedence (double-quoted, single-quoted, bare). `group` numbers the outermost alternatives container
(`CodeBlockTabs`, `Tabs`, `CodeGroup`, `CodeTabs`, `ViewGroup`), so blocks that are alternatives to each other can be
recognised later — the hook a validated flag would need. Self-closing tags do not open a container and a stray
closing tag is ignored, because real docs contain both.

## Calls (`calls.py`, `jsread.py`)

`Call` is deliberately tool-agnostic: `tool, method, url, query, body_kind, body`. The checker downstream cares only
about what goes on the wire, so a curl command and a `fetch` with the same effect produce equal calls, modulo
`tool`, which is kept for reporting.

`body_kind` is a small vocabulary with one job each:

| kind | meaning |
|---|---|
| `none` | nothing is sent |
| `json` | parsed JSON (values may contain UNKNOWN) |
| `form` | field-name-to-value dict, for form bodies |
| `unparsed` | something is sent, but it could not be read |

`unparsed` is what keeps honesty cheap: it flows into a `partial` verdict instead of forcing the parser to invent a
value.

### Shell

curl blocks are split with `shlex` (posix, comments) after unquoted separators are turned into command breaks,
because one block often holds several commands; backslash-newline is joined first, since that is the formatting the
docs actually use. Separators inside single quotes, double quotes, escaped characters, and comments are preserved or
ignored correctly, so a quoted URL with `&` or a comment containing `|` does not split a command.

Option handling is a table, not a grammar: long options with an argument, a set of short letters that take one, and
letter-by-letter reading of groups (`-sSL` is `-s -S -L`, `-XPOST` is `-X POST`). Anything unrecognised consumes
nothing, so an option the parser has never heard of cannot swallow the URL.

Semantics worth naming:

- Data parts are joined with `&` before parsing, because that is how curl concatenates several `-d` values.
- `-G` moves the data into the query string, after the pairs already in the URL — the order curl sends.
- JSON is detected three ways (`--json`, a JSON content type, data starting with `{` or `[`), and a parse failure
  becomes `unparsed` rather than an error: an example with a typo in its JSON is a call we cannot check, not a
  crash.
- A `-F name=@file` value is UNKNOWN, since the file's contents are not in the page.

A quoting error discards the whole block's calls. Half-parsing a block invents calls, and an invented call is worse
than a missing one.

### JavaScript

`fetch` is found with a regex that excludes `prefetch(` and `client.fetch(`: a bare fetch is the only shape that
unambiguously sends a request with no other context.

The arguments are read by a small recursive-descent reader (`jsread.py`) instead of a JavaScript parser, because the
input is snippets rather than programs: strings (escapes and template substitutions), numbers (underscores, hex,
binary, octal, exponents), `true`/`false`/`null`, arrays and objects. Anything else — a variable, a call, an
arithmetic expression, an object with a spread — is UNKNOWN. A literal followed by more expression (`'a' + b`) is
UNKNOWN too: it is not the value it looks like. Comments are skipped everywhere, because fragments carry them.

Keeping property spans as well as values is what makes `JSON.stringify(...)` readable: the option's raw text is
inspected for that exact prefix and its argument then read as a literal. A JSON.stringify expression is accepted
only when it is complete, so a body such as `JSON.stringify({a: 1}) || fallback` falls through to `unparsed`.

The options object is used only when it is a complete object expression; `{method: "POST"} || defaults` makes the
fetch options non-literal and drops the call.

### Python

Python examples are parsed with `ast`, not regexes: it is in the standard library, it is exact, and it gives line
and column for source ordering. Only `requests` and `httpx` by name are accepted — `session.get(...)` is a different
conversation and guessing is not the job.

`params={...}` with a dict literal adds query pairs (`{?}` when a value is not a literal), which is how most of
these examples write query parameters. `json=` wins over `data=`/`files=`, matching requests' own precedence.

F-string URLs keep their placeholders as `{source}` via `ast.unparse`, so `/documents/{doc_id}` matches the template
`/documents/{id}`. That is also why placeholders are later allowed to satisfy any schema.

## Matching (`spec.py`)

Matching is by segment count and per-segment equality, with `{name}` fitting any single segment. That is
intentionally simpler than OpenAPI's own path matching, which has no tie-break rules worth implementing here: when
several templates fit, the one with the most literal segments wins (`/a/special` over `/a/{id}`), and ties go to the
earliest operation in file order. Deterministic beats clever — the report has to be byte-identical between runs.

Failures are distinguished because they mean different things to a reader: `unknown_path` ('this endpoint is not in
the spec at all') versus `method_not_allowed` ('the path exists; this verb does not'). The latter lists the methods
the spec does declare, sorted, so the finding is actionable.

`deref` follows local refs only, capped at twelve hops, and lets the ref node's sibling keys win. That is JSON
Schema's rule and it matters: a property that adds a description next to a ref must not lose it. A cycle returns
the ref itself rather than raising.

## Checks (`check.py`)

The order of problems is fixed — path, then query, then body — and inside each, declaration order for missing things
and source order for sent things. A reviewer reading a finding list should see the same order every run.

`validate` implements the subset of JSON Schema the specs use: `type` (including lists of types), `enum`, `const`,
`properties`/`required`/`additionalProperties`, `items`, and `anyOf`/`oneOf`. Two decisions stand out:

- **A type mismatch ends the walk** at that node. Reporting a missing field inside a value that is not even an
  object is noise.
- **Choices pick the fewest problems among branches whose type fits**, earliest on ties. Any branch that is
  problem-free accepts the value; if no branch fits the type, the answer is a single `type` problem rather than a
  dump of every branch's complaints.

`additionalProperties` absent means 'not documented', which the checker treats as undocumented rather than allowed.
That is the strict reading, and it is what makes a renamed field visible; a spec that means 'anything goes' says
`additionalProperties: true` and is respected.

Parameters are text, never JSON: `?limit=5` carries `5`, and `integer` means 'fully matches `-?\d+`'. `const`/`enum`
are compared as text (`true`, `false`, `null`, else `str`), so a boolean enum works. An array-typed parameter checks
its item schema against the single text value — the specs' way of documenting repeated query parameters.

Bodies:

- No body when the spec marks the body required is `missing_body`; no body otherwise is silence.
- A body where the operation declares none is `unexpected_body`, except an empty JSON object, which several real
  list endpoints document as 'no filters'. Treating that as an error would flag correct examples.
- Content type is checked before shape: a JSON body sent to a form-only operation is a `content_type` problem, not
  a pile of field findings.
- JSON bodies are validated from the schema's root, so field locations read `$.field` rather than `body.field`.
- Form bodies are name-checked only and use the same root-style locations as object properties. Their values are
  strings by construction, and the specs describe them as strings in a form anyway.

### Placeholders

A placeholder is UNKNOWN, or a string containing any of `$`, `{`, `}`, `<`, `>`; it satisfies every schema. This is
the most consequential permissive decision in the tool, and it is deliberate: docs write `${BASE_URL}`, `{docId}`,
`<your-key>` and similar, and flagging those would bury the real findings. The cost is stated in the README — such
values are not checked at all.

## Verdicts (`report.py`)

Three verdicts, with the mapping kept in one place:

- any problem gives `mismatch`;
- no problem but an `unparsed` body, or a JSON body containing UNKNOWN at any depth, gives `partial`;
- otherwise `ok`.

`partial` exists because a silent `ok` on an example whose body was a variable would overstate coverage. Splitting
it out of `mismatch` matters as much: the checker's own limitation should not be reported as the docs' bug.

`scan` also counts pages, every code block, and calls to hosts other than the API host, so the report can say how
much of the site it looked at and how much it skipped.

## Seeded drift (`mutate.py`)

The point of this experiment is not to find bugs but to show the checker reacts to the spec changes that break real
clients. Each mutation is applied to a deep copy of one spec, and only to one operation:

| mutation | what changes | expected code |
|---|---|---|
| `remove_operation` | the method disappears from its path item | `unknown_path` or `method_not_allowed` |
| `rename_field:k` | property `k` becomes `k_renamed`, in `required` too | `undocumented_field` |
| `add_required` | a new required property | `missing_field` |
| `drop_enum_value` | one value removed from an enum | `enum` |
| `rename_param:n` | a query parameter is renamed | `undocumented_param` |
| `add_optional` | a new optional property | nothing |
| `add_enum_value` | a value appended to an enum | nothing |

Two implementation details make the results mean something:

1. **Inlining before editing.** The operation's body and parameter schemas are replaced by dereferenced copies
   first. Otherwise renaming a property inside a shared component would change every operation that references it,
   and the experiment would measure something else entirely.
2. **Mutations are derived from the call.** A `rename_field` exists only for a key the example actually sends, and a
   `drop_enum_value` only for a value the example actually uses. That makes the breaking set a fair test of
   sensitivity — and it is also why the README says it measures sensitivity, not discovery.

Neutral mutations exist to catch the opposite failure: a checker that flags everything would score perfectly on
breaking mutations and be useless in practice.

## Ledger replay (`history.py`)

A ledger case is a single problem identity — `(method, operation, code, where)` — checked at three commits. The
identity is intentionally narrow: it asks whether that exact problem is present, not whether the page is clean, so
unrelated findings on the same page neither create nor hide a case. `operation` may be null, which is exactly how
the 'route that never existed' cases are expressed.

`evaluate` returns four booleans rather than one, because they answer different questions: was the problem already
visible at the introduced commit, does the buggy commit show it, is it gone at the fix, and — the headline — both of
the last two. A case that fails `cleared` is a false negative; a case that fails `detected` means the checker does
not see the bug the docs team fixed.

`days_open` is computed from commit dates rather than hand-written, so the exposure it reports can be recomputed
from `study/ledger.json` alone.

## Metrics and determinism (`metrics.py`, `experiment.py`, `demo.py`)

`findings` reduces rows to sorted distinct `(method, path, code, where)`: the report talks about problems, not
occurrences, so one wrong example repeated on three pages is one finding. Paths lose the query string, because a
problem should not change identity when an example's page number does.

`experiment.py` returns metrics with sorted keys and writes JSON with sorted keys, one-space indent and a trailing
newline, creating parent folders, so two runs over the same pinned data are byte-identical and a diff under
`results/` means a real change. Ratios go through one helper (six places, `0.0` for an empty denominator) so the
file does not change shape when a set is empty.

`demo.py` owns presentation only: it prints the report from `results/details.json`, or rewrites the README's results
block from `results/metrics.json`. Rendering fails loudly unless each marker appears exactly once and in order — a
silently half-rewritten README is worse than a failed build. No number is ever typed by hand into the README, which
is the reason the block exists at all.

## A possible integration with Margin's ingest (a hypothesis)

One possible integration is to attach three fields to each extracted code example: `validated` (`true`, `false`, or
absent when no call was found or the call could not be read), `operation`, and `problems`. This is a hypothesis
about the kind of ingest step Margin could add; it is not a description of Margin's current code or behavior.

The third state is the interesting one: it separates 'checked and wrong' from 'not checkable', which is the
distinction a bare `runnable` flag cannot draw. The visible surface could then be a badge next to the snippet plus
a CI gate on mismatches.

## What is deliberately not done

- **No network.** Not for the spec, not for the API, not for a model. Everything is a pure function of files.
- **No SDK mapping.** `client.documents.batchAdd(...)` has its HTTP shape in another package; mapping it here would
  need that package's source, not just the spec.
- **No response checking.** The examples show responses too, but the specs' response schemas are looser than the
  code the docs print, so checking them in this milestone would produce more noise than signal.
- **No heuristics for non-literal URLs.** Resolving `${BASE}` would need conventions the docs do not state
  consistently, and a wrong guess would be reported as the docs' fault.
- **No attempt at JSON Schema completeness.** Ref resolution, choices, enums, constants, required fields,
  additional properties, items and types cover what the two pinned specs actually use; everything else is ignored
  rather than half-implemented.
