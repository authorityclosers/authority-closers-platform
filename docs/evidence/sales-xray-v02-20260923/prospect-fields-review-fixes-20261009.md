# Prospect field review fixes — AUT-1585 / PR #414

Responds to the CTO's changes requested at
`35ac360a4d7b6e723e4f07596e464638e4feccf5`. This is a bounded correction to the
existing foundation, with no migration, catalogue, UI, identity-service or
provider changes. The original implementation and migration receipts remain in
[prospect-fields-20261009.md](prospect-fields-20261009.md).

## Tenant isolation

The outer recording/submission join now explicitly filters both tables to the
actor tenant. Submission identity is `(tenant_id, submission_id)` throughout
the evidence mapping; source identity is `(tenant_id, recording_id)`. Recording
locks are acquired in ID order. `_field_sources` rejects foreign recordings and
loads only the current tenant's retained C2 checkpoints, before checking their
manifest binding and evidence.

Privacy marks retain ADR 0051 D3: ID-only marks apply to every recording sharing
the transcript revision. They contain no source text. The recording branch of
the mark query is tenant-scoped; the shared-revision branch remains effective
across duplicates. This intentionally does not narrow privacy containment to one
tenant. Foreign recording/checkpoint content never supplies quote validation or
withholding text.

The fictional collision proof creates the same submission UUID in two tenants,
plus a foreign C2 with the same transcript revision. It captures actual ORM
loads and requires every loaded recording/checkpoint to belong to the reader's
tenant. It also tests defensive rejection of a foreign source argument, retained
shared-revision marking, and an explicit Unknown after the authorized checkpoint
is erased: the foreign checkpoint cannot replace missing evidence.

## Lock order and atomicity

PUT uses `edit_fields_and_read`: read/fence detected source history, then acquire
the prospect row for the expected-revision edit, then append audit. The source
share locks remain held through response construction and transaction commit.
The response refreshes only person revisions after the edit; it takes no new
recording lock while holding the tenant audit lock. Detected writes already take
their recording fence before the prospect and audit locks. No exception retry or
split transaction hides a lock failure, and no retention fence was removed.

The deterministic PostgreSQL regression pauses the first operation at its real
resource/audit boundary, observes the second operation blocked using
`pg_blocking_pids`, and then releases the first operation. It covers both PUT
first and sensitive marking first, with independently identified editing and
safety actors. Both must commit; subsequent HTTP reads must withhold the detected
business while preserving the saved, locked person city. Audit counts, immutable
field rows and the complete tenant audit hash chain are checked. A PUT that
commits before marking can return the prior supported evidence; every later read
must withhold it.

## API and coverage

Response shapes are unchanged: `ac.sales-xray.prospect-fields/1`, registry and
prospect with shared revision plus all 14 `profile_fields` keys. The
[fictional full response](prospect-fields-example-20261009.json) remains the UI
handoff. Stale/no-op, counts-only audit, person locks and explicit Unknown remain
part of the foundation.

The foundation has 12 public keys plus person-only phone/email. It does not
implement the complete pinned section 2, including structured qualification,
certainty, factual labels, stakeholders, objections and commitments. Basis,
person lock and confirmed/detected storage states do not establish those labels.
The CTO's [six-section coverage table](/AUT/issues/AUT-1585#document-cto-review-pr414-35ac360)
remains the gap record; the bounded contract follow-up belongs to
[AUT-1587](/AUT/issues/AUT-1587). No full-spec completion claim is made here.

## Runtime and delivery limits

Read-only inspection in this run found both lane preview ports (3040/3050)
unreachable. [Public dev prospects](https://salesxray-dev.authorityclosers.com/prospects)
returned HTTP 403. Authenticated Business/City cross-session acceptance and the
production-version receipt remain unverified. No host, service, settings or
shared runtime data were changed. Disposable local PostgreSQL evidence does not
establish deployed acceptance.

The existing sensitive CTO → CEO → builder/release stages remain the delivery
path. Migration 0079 and all backup mappings are unchanged by these fixes; their
earlier upgrade/parity receipts remain historical evidence. This run does not
repeat or claim a live restore or release.

## Verification checkpoint

- Registry, numeric fact contract, report context and new field backup parity:
  **30 passed in 13.89 seconds**.
- Ruff format: **1067 files formatted**; Ruff lint: **all checks passed**;
  mypy: **440 source files passed**.
- The final combined database process has passed the tenant collision case and
  both deterministic PUT/mark orderings. The remaining existing HTTP regressions
  are still running at this checkpoint; their complete result follows below.
- Repository lane check passes. This is a local test checkpoint, not a green-CI
  or deployed-acceptance receipt.

## Final local receipt (supersedes the checkpoint)

The implementation commit is `879ccfe`; the final handoff also contains this
receipt. No Python code changed after the following passing checks.

```text
python -m pytest -q -s --tb=short
  tests/database/test_prospect_field_safety_postgresql.py
  tests/database/test_prospect_fields_postgresql.py::test_put_persistence_noop_stale_race_denials_rollback_and_queries
  tests/database/test_prospect_fields_postgresql.py::test_detected_person_lock_disagreement_source_and_history_guards
  tests/database/test_prospect_library_postgresql.py

field PUT/sensitive mark (put first): both committed; later evidence withheld
field PUT/sensitive mark (mark first): both committed; later evidence withheld
field PUT/detail SQL statements (1/20 calls): [(37, 23), (37, 23)]
8 passed in 435.40s

python -m pytest -q
  tests/unit/conversation_intelligence/test_prospect_fields.py
  tests/unit/conversation_intelligence/test_prospect_fact_contract.py
  tests/unit/conversation_intelligence/test_prospect_report_context.py
  tests/infra/test_prospect_fields_backup_parity.py
30 passed in 13.89s

ruff format --check packages/python tests: 1067 files already formatted
ruff check packages/python tests: All checks passed!
mypy: Success: no issues found in 440 source files
python3 scripts/ac_task.py check: lane may be worked on
```

The first new database run returned 1 passed / 2 failed. One fictional erasure
fixture omitted clearing the manifest; the corrected fixture clears payload and
manifest together under the existing history guard. The other case used PUT's
same session in a bare marking-store call, bypassing the operator identity
resolver and creating an identity/foreign-key cycle. The final race fixture uses
an independently identified canonical safety operator. The fresh 8-pass run
above supersedes those fixture failures and also proves unchanged stale/no-op,
denials, atomic rollback, person-lock/disagreement behavior, library scope,
provenance/corruption rejection and constant query counts. These are disposable
schema tests using fictional data and runtime-injected loopback access.
