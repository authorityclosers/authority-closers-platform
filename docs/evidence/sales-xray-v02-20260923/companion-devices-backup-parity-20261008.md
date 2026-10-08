# Companion device storage and backup parity — AUT-1557

Source baseline: `bc61dbfaca369ee81f22a1e4097a5783a12d71a2`, ADR 0055.

| Draft migration head | Contract | Tables |
| --- | --- | --- |
| `20261008_0077` | `ac-postgres-parity-v48` | 137 |

The four additional tables store device membership bindings, hashed pairing
attempts, refresh families and hashed access/refresh/web-session credentials.
Database checks reject plaintext credentials and invalid expiry bounds; a trigger
preserves credential payloads and spent-token timestamps across rotation. The
submission capture-source column is nullable and has no default or backfill.
It is registered as schema metadata; card 6 owns its ORM mapping and writers.

All three separately packaged backup/restore catalogues recognise the draft head
and retain their historical mappings. These contracts attest table inventories
and row counts, not individual values or a live restore.

Local verification on 2026-10-08:

- Disposable PostgreSQL migration/registry tests: 15 passed, including schema
  drift, exact constraint rejections, immutable rotation history and legacy NULLs.
- Release-tool tests: 190 passed. Root-only backup parity tests: 4,118 skipped
  because this session has no root access; the pure three-catalogue contract
  assertion was executed directly and passed (v48, 137 tables).
- Required Python formatting, lint and mypy checks passed; migration and
  foundation-tool formatting/lint also passed.
- Existing dev `/health/ready` returned `ready` with release
  `ce753781ba69f9b2e74b9300619473173bab2be1`. The draft migration was not applied
  to dev and does not constitute a new-head dev-start proof.

PR #399 (AUT-1534) currently owns the preceding prospect-tag migration and
overlapping backup catalogue files. Before publishing this card's PR, integrate
that merged schema baseline, select its next migration/contract version, rerun
the affected proofs, and apply the final migration on the fictional dev database.
The temporary draft head/version above must not be deployed alongside PR #399.
No native routes, activation flags, staging or production state were changed.
