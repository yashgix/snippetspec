# Mismatch split (post hoc)

This is a post-hoc reading of committed results. It is not part of the frozen v1 method and changes no verdict,
number or test.

The question: of the calls the checker flags as `mismatch`, which are confirmed errors in the snippet, and which are
disagreements between the spec and its own docs?

## Rule

Only existing fields are used: `verdict`, `method`, `operation` and `problems` in `results/details.json` and
`results/holdout.json`, and `label` in `study/triage.json`.

1. **Confirmed snippet error.** Outside evidence shows the snippet is wrong: a later docs fix, or a run against the
   API. A finding labelled `false_positive` would count against the checker instead.
2. **Spec and docs disagree.** The triage labels the finding `spec_gap`: the docs show an endpoint the pinned
   specs do not describe.
3. **Unconfirmed.** Everything else.

## Supermemory, today's docs

24 mismatch calls in `results/details.json`, grouped into 11 findings by method and path, each with a triage label.

| class | findings | calls |
|---|---|---|
| confirmed snippet error | 0 | 0 |
| spec and docs disagree (`spec_gap`) | 10 | 21 |
| unconfirmed | 1 | 3 |
| total | 11 | 24 |

Examples:

- `GET /v3/analytics/usage`, 3 calls, `spec_gap`. No analytics path in either spec, and a later docs commit says the
  page was checked against the current API.
- `POST /auth/scoped-key`, 1 call, `spec_gap`. Neither spec has an `/auth` path.
- `POST /v3/documents/documents`, 3 calls, `unconfirmed`. The path reaches `/v3/documents/{id}`, which allows only
  DELETE, GET and PATCH. Nothing says whether the route is live.

The 15 ledger cases are confirmed snippet errors (a later commit fixed each one), but they are at past commits, not
among these 24 calls.

## Meilisearch hold-out, clean samples

Not split. 114 of 216 published samples are flagged (53%). These flags have no triage label, no sample was run against
a server, and no later docs fix was collected. So by the rule above all 114 are unconfirmed. Counting problem codes
does not settle it: a missing required field can mean the snippet left it out or the spec over-requires it.

What the fields do show:

- 82 of the 114 flagged calls have only "missing" problems (`missing_field`, `missing_param`, `missing_body`): the spec
  asks for something the sample does not send.
- The largest group is `POST /indexes/{indexUid}/search`: 56 flagged calls, 54 of them for leaving out snake-case
  fields the spec marks required, such as `$.crop_length` and `$.matching_strategy`.

If the published samples are right, the 114 are false alarms, a 53% false-positive rate on this spec.
