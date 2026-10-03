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
read or sent to a provider.

- Speaker freeze/dispatch, processing-plan, retained recovery/repair, role-context
  and prompt-revision unit suites: **125 passed**.
- Application release contracts: **89 passed**. These are distinct from the 125.
- PostgreSQL flow (legacy and patched declaration), claimed-owner freeze across
  sessions, immutable history/erasure, and four retained-recovery cases:
  **8 passed**, no skips. Role-bearing retained correction/revalidation succeeds.
- Read-only catalogue equivalence, checked-in heads and table-parity assertions:
  **3 passed**. The full root-owned metadata suite belongs to CI; it was not run
  locally and is not counted as passed.
- Ruff format/check and mypy across Python/tests: passed. Markdown Prettier:
  passed. All six legacy prompt/request parity cases remain covered.
- Normal migration command with `~/.config/acdev/database.env`: applied dev
  `0070 -> 0071 -> 0072`; read-back confirms `20261003_0072`. The configured
  environment is named `local`, and the target matches the configured dev API
  database. An initial `dev`-only label check failed; that shell did not stop and
  continued the authorized migration. Subsequent read-only validation used
  `set -e` and accepted the correct local label. No migration was repeated.

Dev: <https://salesxray-dev.authorityclosers.com>. This dormant mechanism is checked
with the patched-declaring-revision suites. The running API's readiness and OpenAPI
return 200, but its schema still omits the merged S3 speaker-map route. Authenticated
live S3 behavior remains unverified. No staging or production change was performed.
