# AUT-1677 — older nullable Report metadata

An otherwise source-bound completed Report previously became unavailable when an
older serializer supplied `null` for optional evidence or skill state metadata.
The browser now normalizes those nulls to absent fields: dimension `evidence`
and `call_state`, `summary_evidence`, `verdict_evidence`, and the optional Story.
The existing nullable Overview behavior is retained.

The canonical Python `ReportDimension` and `ReportDraft` types already admit
null for these evidence/state fields. Current projections omit them; this change
also accepts their explicit absence in older response shapes. It does not infer
a skill assessment, outcome, timestamp, commitment, or source. Non-null fields
retain the existing closed shape, bounds, literal quote, revision and timing
checks. Positive skill states still require observed status and literal evidence.
Required summary/verdict/source fields cannot become defaults.

Regression coverage checks nullable and omitted metadata equivalence, no new
skill states, positive-state evidence enforcement and required-content rejection.
The real saved-report preload opens the nullable acquisition envelope and still
rejects a stale source revision. The focused contract/preload/Story/pillar tests,
incremental typecheck, changed-file cached ESLint, Prettier and browser-script
Ruff checks are the local gates.

Populated dev-only `/review-fixture/report/legacy` runs invented native source
through the real parser and real Report views. The shared-dev browser runner is
`apps/sales-xray-web/tests/browser_report_legacy.py`; it checks six pillars/eight
skills, honest outcome gaps, exact source selection, retained Reading/Document
views and 1440/390 light/dark overflow. The screenshot receipt is recorded in
the strike's NOTES after committed work reaches dev/live.

This is a read compatibility change. No provider/schema/state change, production
QA, deployment, Company/outcome API, or saved-call shell integration is claimed.
Strike A still owns mounting `preloadSavedReport` in its route/studio; H/QA owns
authenticated production acceptance. The existing Pro/AC Orchestra access
limitation remains recorded; no cloud output supplied this repair.
