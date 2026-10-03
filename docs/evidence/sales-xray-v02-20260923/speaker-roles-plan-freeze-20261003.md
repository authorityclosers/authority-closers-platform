# AUT-311 S4b2: freeze speaker roles before C5

Base: `fbb795ca7653729969bedd8dea676c5ccedd8dba`, after reviewed PR #257
merged. Authority: AUT-311 plan rev 3, ADR 0042 and the CTO's S4b1 findings.
This slice freezes names-free plan input and carries it through retained recovery.
Report-basis disclosure and S5 model naming remain separate. No declaring prompt,
provider activation, scoring, minutes or protected profile change.

## Implementation

- First C5 construction resolves the upload owner through `_customer_person_id`;
  the processing service person's name is never substituted for a guest owner.
  Current choices are scoped to that owner, tenant, recording and source hash.
- Prediction uses the same withheld transcript projection as speaker-map reads.
  Unknown/stale user attribution falls back to text prediction with a bounded
  diagnostic. Invalid snapshots freeze a null result. A progress marker makes a
  null result durable too, without adding a column or changing the plan manifest.
- Polls, profile holds, repairs and saved-intent dispatch reuse the frozen value.
  Later user changes affect a new plan. Returned role blocks are detached copies;
  names/profile text never enter them. Undeclared revisions never read the map.
- Optional roles that exceed the existing prompt budget fall back locally to the
  original request, with `speaker_roles_prompt_budget_exceeded`. The sanitized
  request is saved; there is no provider or repair retry and no higher budget.
  Report basis must later read this actual C5 input, rather than the plan column.
- Retained reconstruction and validation receive the saved request's revision and
  snapshot, preserving exact input digests and binding without a new AI run.

## Migration and backup parity

The real PostgreSQL flow exposed an S2a omission: the existing plan-history trigger
implicitly rejected changes to the newly added `speaker_roles` column. Forward
migration `20261003_0072`, after call-metrics `0071`, permits exactly one freeze,
including a frozen null fallback. Later changes, unfreezing and resurrection after
erasure fail. Original manifest, identity, acceptance and history protections remain.
Canonical erasure may clear both private fields. No backfill or new table.

All three separately packaged backup/restore helpers recognize `0072` with existing
`ac-postgres-parity-v43`, **127 tables**. Historical mappings remain unchanged.
Follow the normal configured migration path; no manual SQL or runtime edits.

## Verification

All fixtures and provider responses are fictional and local. No customer call was
read or sent to a provider. Focused unit, PostgreSQL and static results are recorded
on the PR and task; skipped root-only checks are not counted as passes.

Dev: <https://salesxray-dev.authorityclosers.com>. This dormant mechanism is checked
with the patched-declaring-revision suites. The running API's readiness and OpenAPI
return 200, but its schema still omits the merged S3 speaker-map route. Authenticated
live S3 behavior remains unverified. No staging or production change was performed.
