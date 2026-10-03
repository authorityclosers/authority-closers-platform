# AUT-739: confirmed inactive catalogue values

Source: AUT-739 plan revision 2 (`f455dc37-a4a2-4c24-affe-fa88a755c5aa`),
the CEO's final price and Enterprise decisions, and the CTO's 3 Oct scope
amendment permitting the C1 test-file change. Base: main
`b986bc976de2880c83a08d3f0368f1d67103f286`, billing lane. Main head was 0067;
the open-task search found no 0068 reservation before writing the migration.

Migration `20261003_0068` locks and validates every fixed 0065 seed field
before adding `prices_include_gst` (NOT NULL, default false) and filling the
approved values. All three rows remain `coming_soon` and advance from revision
1 to 2. Personal GST is included; packs inherit their plan's flag. Prices,
seats, minutes, packs and Enterprise feature keys match plan revision 2.
All cents, retention and rollover fields remain NULL. Unrelated rows retain
their original data and receive the column's false default.

Real loopback PostgreSQL tests prove the before/after values and revisions,
unchanged identity/timestamps where required, and rejection of 21 edited or
missing Enterprise seed variants. Each rejection exits Alembic with code 1
and the exact `inactive catalogue seed changed; review required` error;
read-back retains the previous head, all pre-migration data and no GST column.
The original C1 seed assertions are unchanged and now run at 0065. Model drift,
database constraints and the forward-only downgrade refusal still pass.

The anonymous HTTP test reads the C3-migrated fictional schema: all plan prices
are NULL, every pack omits both price fields, seats are 1–1 / 2–49 / 50–NULL,
minutes are 800 / 1000 / 1000, call limits are 90 / 90 / 120 and revisions are 2.
The public JSON contract is unchanged; the GST flag is stored only.

## Validation (2026-10-03)

- `uv run pytest -q tests/database/test_plans_confirmed_values_postgresql.py tests/integration/test_plans_public_postgresql.py tests/database/test_model_registry.py tests/infra/test_ac_release.py tests/database/test_plans_postgresql.py tests/unit/plans`: **167 passed**, no skips, 165.38 s.
- `uv run ruff format --check packages/python tests db/migrations/versions/20261003_0068_inactive_plan_values.py`: **891 files already formatted**.
- `uv run ruff check packages/python tests db/migrations/versions/20261003_0068_inactive_plan_values.py`: **passed**.
- `uv run mypy packages/python`: **passed**, 376 source files.
- `uv run ruff check db/migrations/versions/20261003_0068_inactive_plan_values.py infra/application/scripts/restore-drill.py infra/vps-foundation/scripts/ac-postgres-backup.py infra/vps-foundation/scripts/ac-restic-postgres-restore-proof.py`: **passed**.
- `uv run ruff format --check infra/application/scripts/restore-drill.py infra/vps-foundation/scripts/ac-postgres-backup.py infra/vps-foundation/scripts/ac-restic-postgres-restore-proof.py`: **3 files already formatted**.
- Direct execution of `test_three_separately_packaged_helpers_have_identical_versioned_contracts()` and `test_versioned_contracts_match_all_new_migration_tables_exactly()`: **passed**. All three helpers recognise exact head 0068 with v40 and 121 tables; historical contracts remain unchanged.
- `ac-gate check`: **passed** before implementation. PR-time single-track and CI results are recorded on the PR.

The root-owned parity suite remains a required CI gate. Local `sudo -n` was
unavailable; this is not root-owned backup/restore evidence. The initial UUID
reflection error was fixed and the final focused suite above passed.

## Dev check after the approved merge

Allow the normal release and dev refresh to apply 0068. Read anonymous
`GET /v1/plans`: verify the three rows and metadata above, `coming_soon`,
`prices: null` and pack objects containing only key, minutes and validity rule.
Record the deployed release SHA with that response. The checks here use
fictional disposable schemas; deployed C3 verification is still pending.
Activation, provider requests and live charges belong to their separate cards.
