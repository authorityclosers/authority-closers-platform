# AUT-311 S5a: model speaker validation and optional basis safety

Source: ADR 0042, AUT-311 approved plan rev 3, AUT-632 card, and the two
CTO follow-ups from PR #265. Base: `b5e240d29d7a24e7c81d3183665fd88a9e144899`.
The latest gate reported sales-xray FREE and main green; the clean sales-xray
checkout was started as `task/sales-xray/311-model-named-speakers`.

Bounded split: this slice adds the pure fresh-output validator and fixes
optional report-basis failures. Fresh v7 parser/storage integration and model
source GET wiring remain S5b. The validator is not yet called by the parser;
this slice does not claim server-persisted model names or new GET pre-fill.

- Strict entries use known attributed C2 speakers, 1–5 unique current evidence
  ids, four roles, and low/medium/high confidence. Names are null or bounded
  Unicode text, with literal NFC/casefold/whitespace-normalized cited presence.
  Preserve original name spelling and honorifics, including greetings naming
  another speaker. Reject controls, invented names, numeric confidence and extras.
- Invalid entries fall back independently. Oversize/malformed blocks and
  duplicate speakers or multiple You claims return no model source. Diagnostics
  contain fixed codes only. Successful output binds to the supplied C2 revision.
- Optional report rendering and its task lookup now share the content-free
  fallback boundary; conflicts, bad run ids and missing message/newline indexes
  return null. An empty declaring set returns before report/database reads.
  Ownership and retention still run in the caller before optional attribution.
- The model validator remains display-only: the existing resolver requires a
  profile name match for automatic You and rejects stale model revisions.

Verification: 267 distinct unit/regression cases passed (the updated 41-case
validator suite replaces its earlier 35 cases). Ruff format/check passed;
mypy passed across 426 source files. Fictional data only; no provider call,
migration or runtime edit. No prompt, report parser, report-store schema,
provider task, frozen snapshot or minutes logic changed in this slice.

Dev check: https://salesxray-dev.authorityclosers.com. Local readiness and
OpenAPI returned 200; GET/PUT speaker-map are exposed. Public dev returned 403;
authenticated live-call behavior is unverified. Run the seven unit suites in
the PR on the dev checkout; fixtures are fictional and invoke no provider.
