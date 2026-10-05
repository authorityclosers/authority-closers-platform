# AUT-468: product updates store evidence

Initial source pin: `d8da579226496c731f1a216ca72ce9bcc9233c61`.
Current validation base: `7511641c6249e731581532c4b38edacdb843f0f2`.
Branch: `task/platform/468-product-updates-store`.
Policy: AUT-423 plan revision 1; design: AUT-433 plan revision 3.
ADR 0050 was taken; this slice uses ADR 0054. Main subsequently assigned
migration `20261004_0074` and parity v45 to the prospect store. This unmerged
slice now uses migration `20261004_0075` after `20261004_0074`, advancing
backup parity from v45 (130 tables) to v46 (133 tables). Older contracts remain
unchanged.

## Implementation

- Registered `product_updates`, account-level `update_seen`, and event-only
  `notifications`, with foreign keys to persons and nullable tenant references.
- ORM guards and PostgreSQL triggers refuse note/seen UPDATE and DELETE.
  Notifications permit only a single null-to-timestamp `read_at` update.
- Portable CHECKs enforce title, audience, creator, status, publication,
  supersession shape and item count. A PostgreSQL insertion trigger enforces
  JSON array/string shape and 200-character item bounds; model validation
  provides string bounds on SQLite without PostgreSQL-only model CHECKs.
- Capability registration, both installed permission CHECKs, HTTP Literal and
  grant CLI agree on `platform_updates_manage`. No permission is granted.
- Six version-1 published seed rows preserve the original `changelog.ts` at
  `dc25878` verbatim, with descending publication timestamps preserving order.
- All three separately packaged backup/restore helpers include the new tables.
  Privacy inventory records retention and erasure boundaries.

The migration, models, seed text and parity changes are approximately 450
production lines; the mechanical schema and two enforcement layers account for
the increase over the card's approximate 350-line target. The CI continuation
also adjusts the existing credit-ledger migration regression: it checks that
0073 remains in the applied chain and the database reaches the current head,
following the established billing-ledger test pattern. This required test-only
scope addition preserves its numeric, trigger and forward-only checks.

## Verification before the main update

Only fictional data and random isolated schemas in the lane's injected localhost
test database are used. Each schema is removed by its test fixture.

- `ac-gate check`: passed for this owning branch.
- Repository Ruff format and lint, plus changed migration/infra scripts: passed.
- `uv run --frozen mypy packages/python`: passed (417 source files).
- `uv run --frozen pytest tests/database/test_product_updates.py
  tests/integration/test_product_updates_postgresql.py tests/unit/product_updates
  tests/database/test_model_registry.py tests/database/test_capability_grants.py
  tests/unit/http/test_platform_access.py -q -x --tb=short`: **169 passed**, no skips.
  Covers the incremental 0073→0074 upgrade with preserved grant/revocation history,
  schema comparison, six seed rows, both engines' CHECKs and ORM guards,
  PostgreSQL bulk UPDATE/DELETE, read-once events and grant CLI acceptance.
- `uv run --frozen pytest tests/infra/test_restore_drill.py
  tests/infra/test_ac_release.py -q -x --tb=short`: 180 passed, 2 skipped.
  Skips: Docker daemon unavailable; approved-dump restore integration not enabled.
- Full root-owned `tests/infra/test_capability_backup_parity.py`: **3,737 passed,
  zero skipped**, in 79.46 seconds at `05b4306b9d508c1b0825fc94990c3aec3e804096`.
  [Root's receipt](/AUT/issues/AUT-1171#comment-bab2c023-519f-426e-b9de-d89e15ffbd6a)
  records effective uid 0, exact command, uploaded output and JUnit evidence.
  The continuation changes only this receipt and the credit-ledger regression;
  the parity suite, helpers, migration, models and all other tracked inputs are
  identical to that verified commit. No claim of a second Root run is made.
- Initial CI shard 2 failed only because the credit-ledger regression expected
  `20261003_0073` to remain the current head. The same failure was reproduced
  locally before the fix. After the fix, `uv run --frozen pytest
  tests/database/test_credits_ledger_postgresql.py -q -x --tb=short`: **8 passed**,
  no skips. Repository format (998 files), lint and mypy (417 files) pass again.

## Main update verification, 5 October 2026

- Completed the interrupted merge from main and then merged the current main
  pin `7511641c6249e731581532c4b38edacdb843f0f2`. All staged files outside this
  card were verified to match the existing main merge target before committing.
  The final diff against main contains only this store slice and its documented
  credit-ledger test adjustment.
- Renumbered the unmerged product-update migration to `20261004_0075`, following
  the already merged prospect migration `20261004_0074`. All three helpers
  preserve prospect parity v45 and add product updates at v46 (133 tables).
  Updated the migration, contract tests and ADR references together.
- Re-ran the selected store, PostgreSQL upgrade, capability, CLI, platform-access,
  model-registry, credit-ledger, restore and release suites in one command:
  **357 passed, 2 skipped**, in 127.67 seconds. The two skips remain the Docker
  daemon and opt-in approved-dump restore integration checks listed above.
- Repository Ruff format: **1,016 files passed**. Ruff lint passed, including
  the renumbered migration and three changed helpers. Mypy passed for **421
  source files**. `git diff --check` passed.
- The original Root receipt is historical: its parity inputs differ from this
  update. A new Root-owned full parity receipt at the pushed head is required
  before CTO review. CI including `single-track` must also pass at that head.

## Dev check and handoff

This store slice has no screen change. After merge/deployment, check that the
deploy record reports migration `20261004_0075`. Do not run manual migrations,
change service settings or seed real accounts. Staging verification follows the
standard release path. The PR requires green CI including `single-track`, Root's
parity receipt, CTO review and CEO approval because migrations, capability checks
and backup scripts are sensitive. The engineer does not merge or mark delivery done.
