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

Root must run the complete backup parity suite at the PR head. The dev migration
preflight found head `20261003_0068`, so it applied no change: the merged billing
migration `0069` must be installed before this task’s `0070`. Root owns that
normal dev migration and metadata read-back. No staging/production state or
customer call was used.
The API endpoints, model naming and report input remain later approved slices.
