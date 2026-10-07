# AUT-1534: persisted person-entered prospect tags

Source: `b1ac586144490d2176fc15db5a5f13cd176a92c6`; branch `task/sx-prospects/1534-prospect-tags`. Saved specification: AUT-1528 revision `e08b982d-6e96-4932-a523-becdf7c636d5`, copied into AUT-1534's executable plan. Latest-main gate reported main green/sx-prospects FREE; the clean checkout passed start/check. Migration 0077 was available, so no filename/head adjustment was needed.

Size decision recorded in the task's implementation-notes document before implementation: required HTTP, authorization, race, rollback, migration and measured-query proofs exceed the approximate 300-line target. The exact 11 allowed file roles and one tags operation remain the scope. Bounded split option: additive migration/parity first, tags write/read/proof second; this PR keeps the operation and its proof together.

## API contract

`PATCH /v1/conversation/prospects/{prospect_id}/tags` replaces the complete ordered list. Both keys are required; extra keys and every query parameter are rejected. `tags` is a strict list of 0–10 strings, each 1–40 raw characters; trim surrounding whitespace and reject blank or exact duplicate trimmed values. Preserve Unicode, case and order. `[]` clears tags. `expected_revision` is the existing strict positive integer shared with name editing. No inferred labels, vocabulary, stage, identity or readiness effect.

Fictional request:

```json
{
  "tags": ["QA label", "Follow up"],
  "expected_revision": 4
}
```

Exact success shape (changed save and fresh no-op):

```json
{
  "schema": "ac.sales-xray.prospect-tags/1",
  "prospect": {
    "prospect_id": "22222222-2222-4222-8222-222222222222",
    "tags": ["QA label", "Follow up"],
    "revision": 5
  }
}
```

Use the current detail revision, PATCH, then refresh the existing list/detail API. Both now project stored tags; unset tags remain `[]`. The existing detail Tags field joins these values. No UI editor is delivered. Name request/schema and its rejection of extra `tags` stay unchanged.

The existing configured-host, safe-Origin, session/current served workspace and identity admission guards are reused, with JSON-only 2048-byte/5-second body limits. Responses/errors remain private/no-store and vary by Cookie. Owner-only selection uses the authorized prospect query plus current owner, with a row lock and refreshed ORM state. Missing, foreign-person/workspace and read-only organisation targets return 404; an unserved workspace returns 403. Stale revision returns 409, “The prospect changed. Reload before saving again.” Existing 401/403/404/408/413/415/422 guards remain.

Revision is checked before no-op. A fresh identical trimmed ordered list changes no revision, timestamp or audit. A change increments revision once and uses the existing clock. `conversation.prospect_tags_changed` is appended in the same transaction, with only `field: tags`, `previous_revision`, `current_revision`, `previous_tag_count`, `current_tag_count` (counts/revisions as strings). Actor/session/workspace/prospect remain event metadata. Label contents never enter event payloads or validation errors. Audit failure rolls back the entire edit.

## Migration and parity receipt

`20261007_0077_prospect_tags.py` follows `20261005_0076`: add one non-null JSON `tags` column, server default `'[]'`, Python callable default `list`, forward-only downgrade. No inferred backfill, tables or indexes. Populated 0076→0077 proof uses an isolated disposable loopback schema and normal Alembic upgrade, preserving legacy fields, membership and audit hashes; model metadata must match the upgraded schema.

All three parity consumers register exact head `20261007_0077` → `ac-postgres-parity-v48` with the unchanged v47 inventory: 133 distinct tables. Historical mappings and unknown-head refusal remain. New-head tests cover missing prospect/history tables, count mismatch, extra table and wrong head. These are migration-head/table-row-count contracts; database tests prove tag values separately. No operational backup, restore, foundation installation, live SQL or host change was performed. Foundation/application consumers must receive this catalogue through normal release delivery before attesting the new head.

## Verification

Required focused/regression command: **241 passed, 21 skipped in 236.42 seconds**. All new tags HTTP/storage/migration/parity cases passed; skipped cases belong to the root-owned restore boundary, unavailable Docker, or opt-in approved-dump restore. They are not live restore evidence. Full Python Ruff format/check pass (1057 files); mypy passes (434 source files). Syntax checks for the migration and all three parity scripts, evidence Prettier, `git diff --check` and latest-main `ac-gate check` pass. GitHub CI is required separately before merge. Measured authenticated SQL statements: writes **23/23/23** for 1/20/25 call memberships; list **14/14/14** for 1/20/20 visible prospects; detail **19/19/19** for 1/20/25 calls. No per-row/per-call query growth. Fictional tests cover stable name/owner/UUID, persisted ordered multilingual/case-distinct tags, full detail/source/report preservation, clear/default, maximum bounds, strict input and transport guards, creator/reader/foreign denials, tags/tags and name/tags races, cached-row refresh after lock, audit metadata/chain and rollback.

## Required CI repair

The CTO returned PR #399 at `c4d228f` for failed required CI. In run `37653337813`, Python shard 0 reached tests: 3850 passed, with the sole failure in `test_populated_0075_upgrade_preserves_rows_and_matches_organisation_model`. It upgrades through 0076 to `head` but still asserts the terminal version is 0076. The same failure reproduced on the injected disposable loopback database (1 failed in 17.35 seconds): actual `20261007_0077`, expected `20261005_0076`.

Bounded scope adjustment under the task's unjam rule: include `tests/integration/test_organisation_settings_postgresql.py` solely to compare the terminal version with the existing `_migration_head()` helper. This twelfth file is required regression support for this additive migration; preserve the populated 0075→0076→head path, row/default/nullability/model assertions and every tags acceptance check. No application behavior, organisation feature or CI infrastructure changes. The checkout is clean and the open organisation UI PR #363 does not touch this test.

Python shard 2 never reached tests: prerequisite package downloads exhausted three bounded attempts, with `apt-get install` exit 124. A normal PR push will run fresh required CI; no timeout/skip/workflow changes or acceptance relaxation are warranted. The application aggregate failed because required components failed. New required CI must pass before review approval or merge; the earlier code review is not CI approval.

Repair verification: **15 passed in 97.16 seconds**, covering both organisation settings tests, all tags PostgreSQL cases and all nine tags parity cases. Full Python Ruff format/check (1057 files) and mypy (434 source files), evidence Prettier, diff whitespace and latest-main gate pass. The assertion fix is two added lines and one removed line; only this regression test and this receipt changed after the reviewed feature head. Earlier 241-pass/21-skip feature evidence remains separate. No tags implementation or migration changed during the repair.

```sh
uv run --frozen pytest -q --tb=short tests/integration/test_organisation_settings_postgresql.py tests/database/test_prospect_tags_postgresql.py tests/infra/test_prospect_tags_backup_parity.py
uv run --frozen ruff format --check packages/python tests
uv run --frozen ruff check packages/python tests
uv run --frozen mypy packages/python
pnpm exec prettier --check docs/evidence/sales-xray-v02-20260923/prospect-tags-20261007.md
git diff --check
ac-gate check
```

## Runtime boundary and delivery check

7 October builder baseline: public dev `/prospects` returns 302 to Cloudflare Access. Authenticated web/API serving SHAs and phone/laptop visual checks are unavailable in this run. Read-only loopback API health reports `ce753781ba69f9b2e74b9300619473173bab2be1`; that is not the public upstream. Active Caddy and sx-prospects preview source route `/v1/*` to staging, with staging Host. The accepted name receipt likewise records shared staging API/database. No runtime write or local-dev Alembic upgrade was attempted against this boundary. Disposable loopback proof is not dev/staging acceptance.

After CTO review/CEO approval, watchdog merge and normal release delivery, Chief of Staff routes runtime acceptance to the authorized operator using the existing protected fictional QA transport/retained prospect from AUT-1516. Record actual web/API release SHAs, API/database upstream and deployed migration/catalogue receipt. On [dev prospects](https://salesxray-dev.authorityclosers.com/prospects), read the existing object and revision, save a fictional label through this route, refresh list/detail and the Tags display, verify fresh no-op, stale 409 and foreign-person/workspace 404. Then verify [staging prospects](https://salesxray-staging.authorityclosers.com/prospects); if data is shared, read back the first save before deciding whether another change is needed. Use only supported audit read-back; keep CI audit/rollback/race proof separate. No duplicate create/provider run, forced runtime audit failure or live DB query. Phone/laptop visual review is a follow-up when access permits. Done requires merged, visible dev then staging evidence; approval alone is not completion.

Executed regression command (disposable loopback URL injected, never printed):

```sh
uv run pytest -q -s --tb=short tests/database/test_prospect_tags_postgresql.py tests/database/test_prospect_profile_edit_postgresql.py tests/database/test_prospect_store_postgresql.py tests/database/test_prospect_library_postgresql.py tests/database/test_conversation_postgresql.py::test_populated_migration_head_matches_real_model_registry tests/infra/test_prospect_tags_backup_parity.py tests/infra/test_prospect_backup_parity.py tests/infra/test_postgres_backup.py tests/infra/test_postgres_restore_proof.py tests/infra/test_restore_drill.py
uv run ruff format --check packages/python tests
uv run ruff check packages/python tests
uv run mypy packages/python
ac-gate check
```
