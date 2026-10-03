# AUT-311 S4c: report attribution disclosure

Source: gate-created `task/sales-xray/311-speaker-report-basis`, from merged
main `b9f2f70e35c821f72d4f59184a8850977d696aad` (PR #259).
Contract: ADR 0042, plan rev 3 D7/D10/D12, CTO's three S4c notes.

## Implementation

- Speaker-map GET/PUT read-back now supplies `report_basis` from the exact C5
  input of the report selected by the existing report boundary, including retained
  recovery. It never reads the processing-plan column or model report text.
- Retained request metadata, verified C2/C4/C1 checkpoints and the saved profile
  reconstruct provider bytes through the existing recovery helper. Both the input
  digest and all saved input metadata must match. Roles and origin come from the
  reconstructed `source_context`; missing/invalid optional proof returns null with
  a content-free diagnostic. Reports without roles return null.
- Comparison uses bound speaker ids, roles and account-holder flags, ignoring
  names and map hashes. Matching confirmation/channel choices update the status;
  a changed role, holder or transcript sets `matches_current: false`. The original
  map hash and holder remain visible. No report text is rewritten.
- Plan freezing selects choices for its exact submission lease. The comment now
  states that callers hold the plan lock; a later PUT applies to the next plan.
- Bounded S4c only: attribution read/projection, the requested lease correction,
  proof and evidence. S5 model naming and UI wiring remain separate. The extra
  PostgreSQL coverage exercises real saved prompts and read-only behavior.

## Verification

- 194 distinct unit/regression cases passed across speaker map/store/service,
  HTTP, freeze/dispatch, acquisition report and retained-C5 recovery suites.
- PostgreSQL: the lease-scoped freeze regression passed. Eight report-pipeline
  cases cover legacy/null and declaring roles with Groq/Gemini, single/multiple
  C4 chunks, replay, unchanged C0–C4 receipts and canonical erasure.
- The two single-chunk fixtures initially assumed a provider label. They now use
  their actual fictional C2 label; optional role validation correctly refused the
  original unknown label.
- Ruff format/check and mypy passed. No prompt builder, provider, usage, schema,
  release or protected policy change. The declaring set remains empty; production
  v1–v6 inputs are unchanged.

CI follow-up: shard 2 reproduced a missing `with_roles` argument in the synthetic
60-minute report test's direct call to the shared reporting fixture. The caller
now explicitly selects `with_roles=False`, preserving its legacy-report scope.
`uv run pytest tests/database/test_conversation_massive_report_postgresql.py
tests/unit/conversation_intelligence/test_speaker_report_basis.py -q` passed all
36 cases, including the complete fictional 60-minute C1–C5 PostgreSQL path, with
no skips. This coverage overlaps the earlier results and is not summed. Ruff
format/check and mypy passed again; the correction changes no production code.

## Dev check and limits

At <https://salesxray-dev.authorityclosers.com>, with a fictional claimed call,
GET speaker-map for a legacy report: `report_basis` is null. For a future declaring
report, confirm the same roles, rename, then swap You: same roles/rename preserve
matching basis; swap reports an earlier attribution. Echo the GET ETag unchanged.

Run the new basis unit suite and the two PostgreSQL targets above with the
configured disposable loopback test database. They patch a declaring revision
only inside tests and use fictional recordings/fake brokers; no provider runs.

Read-back on 3 October: local API with configured Host returns readiness/OpenAPI
200, but its running OpenAPI still omits speaker-map. Public dev access returns 403. Authenticated live route behavior remains unverified, tracked by the existing
AUT-119 runtime repair. No runtime restart or migration was performed here.
