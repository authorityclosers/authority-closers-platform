# AUT-311 speaker-map storage: schema and erasure

Source: approved AUT-311 rev 3, ADR 0042 and the AUT-316 card. Controlled
documents were fetched by the exact IDs in the checked-in instructor/admin
source manifest (Master Index, BRD, IMP 00/01/03/04/05, and implementation
specifications). Base: `788064c0`, after invoice migration PR #235 merged.

Bounded S2 split: this PR supplies schema, erasure and parity; S2's validated
append/read/no-op/locking service follows. No speaker-map HTTP write or C5
role consumer is activated by this change.

- Migration `20261003_0070` follows `20261003_0069`; downgrade is forward-only.
- Speaker choices have tenant/submission and tenant/membership foreign keys,
  unique revisions, bounds 1–50, bounded transcript references and latest/actor
  indexes. PostgreSQL rejects updates. Canonical recording/account erasure
  deletes private choice content and preserves the audit chain.
- Nullable plan `speaker_roles` has no default/backfill; source erasure clears
  it. Names-free snapshot resolution/write-once handling belongs to S4.
- Backup, restore-proof and application restore-drill agree on
  `ac-postgres-parity-v42`, 126 tables, adding only
  `conversation_speaker_map_revisions`. Historical mappings remain unchanged.

Verification (fictional, disposable loopback PostgreSQL only):

- New PostgreSQL schema/bounds/update/tenant proof: 1 passed.
- Canonical recording/account erasure and unrelated-call/audit proof: 2 passed.
- Existing speaker-map, call-label unit and PostgreSQL regression tests: 99 passed.
- Model registry and release checks: 96 passed. Backup parity: 3265 explicitly
  skipped because the suite requires Root; these skips are not passing evidence.
- Ruff format/check and mypy passed. PostgreSQL schema matches ORM metadata;
  SQLite registry builds in the model-registry tests.
- CI fixture correction: all 7 profile unit tests pass after reproducing the
  missing-table failure. Ruff format/check, mypy and Prettier also pass.

CI runs the backup parity suite with the required privileges. The first CI run
reported [1 failure, 2674 passes and 3 skips in shard 0](https://github.com/authorityclosers/authority-closers-platform/actions/runs/37114685438/job/111179082727).
The profile-only SQLite fixture omitted the new speaker history table; it now
creates and drops it alongside label history.
The dev migration preflight found head `20261003_0068`, so it applied no change:
the merged billing migration `0069` must precede this task’s `0070`. Root owns
that normal dev migration and metadata read-back as a dev check, not a merge
prerequisite (CTO direction of 3 Oct). No staging/production state or customer
call was used.
The API endpoints, model naming and report input remain later approved slices.

## S2b: validated revision service

Base `59115890` (merged PR #244). The lane gate created
`task/sales-xray/311-speaker-map-storage` from latest main; `ac-gate check` passed.
The bounded slice changes only the storage service, its tests and this evidence.
Its size includes the PostgreSQL concurrency/rollback/ownership proof; HTTP and
pipeline wiring remain separate slices.

- Reads require the signed-in, claimed call owner and current retention authority.
  Writes lock the canonical recording and repeat the complete ownership binding
  check. Current C2 is read through the authorized transcript projection inside
  the lock; a stale transcript cannot confirm names or roles.
- Choices cover every non-null transcript label exactly once: at most 32 labels,
  IDs up to 128 characters, supported roles and at most one `you`. Names retain
  Unicode and honorifics, use null for the default, and reject controls and names
  over 80 characters. Extra model/source fields cannot be persisted as user choices.
- Equivalent reordered retries return the current revision without writing.
  Competing stale revisions and the 50-revision limit conflict. Each successful
  change appends one revision and `conversation.speaker_map_changed` in the same
  transaction; the audit payload contains only old/new revision numbers.
- Erasure hooks stay unchanged. Moving their imports to module scope would cycle
  through `application` / `guest_ownership` / `acquisition_reports`, now used by
  the storage service. The redundant historical index remains unchanged.

Validation on the dev host, fictional data in disposable loopback schemas:

- `uv run pytest tests/unit/conversation_intelligence/test_speaker_map_store.py
tests/unit/conversation_intelligence/test_speaker_map.py
  tests/unit/conversation_intelligence/test_submission_labels.py -q`: **131 passed**.
- `uv run pytest tests/database/test_speaker_map_postgresql.py -q`: **5 passed**.
  Includes actual concurrent transactions, same-content and competing retries,
  rollback of both history and audit, latest-read/superseding history, same-tenant
  non-owner and cross-tenant rejection, migration parity and canonical erasure.
  The storage proof supplies a fictional authorized C2 projection at the existing
  renderer boundary; it does not exercise a provider or the future HTTP routes.
- `uv run ruff format --check packages/python tests`, `uv run ruff check
packages/python tests`, `uv run mypy packages/python` and Prettier check pass.
- Root's completed AUT-977 receipt verifies dev head 0070, the append-only table
  and nullable plan column. This heartbeat independently read API readiness (200).
  The new service is dormant until S3; no new screen behavior is claimed.
