# Migration 20260930_0060: platform release management and backup parity

Source pin: `a4af92a6b811585a6b546ff02384e4570d161a8f` (latest main at
task start). AUT-28 implements slice A1 of the AUT-498 plan, revision
`4c07f115-c55f-4910-8777-33facb038362`.

## Change

Migration `20260930_0060` follows `20260930_0054`; 0055–0059 remain reserved.
It replaces only the supported-permission and permission-scope checks, retaining
all previous capability values and adding `platform_release_manage` at platform
scope. Downgrade raises `RuntimeError("forward-only")`.

The Python capability registry, HTTP Literal, web enum and console labels now
include all seven platform permissions. This also repairs projection validation
for `platform_organisations_manage`. The web array bound follows the enum length;
unknown and duplicate permissions remain rejected. No capability implies another.

All three independently packaged recovery helpers register head 0060 with
`ac-postgres-parity-v34` and the same 108 representative tables as 0054, including
`capability_grants` and `capability_revocations`. The migration adds no tables,
so it reuses the contract rather than changing the inventory. Exact migration
identity remains mandatory; an older-head snapshot cannot prove the new head.

## Local verification (fictional data, platform lane database)

- `uv run pytest tests/unit/http/test_platform_access.py
  tests/database/test_capability_grants.py tests/database/test_model_registry.py
  tests/infra/test_ac_release.py -q`: 168 passed before adding the PostgreSQL
  regression below.
- Final database/API suite: 74 passed. The new PostgreSQL regression upgrades
  an isolated schema to current head, persists each of the seven platform
  capabilities, and rejects release management at tenant and program scopes.
  SQLite model creation and the existing parametrised persistence checks pass.
- Existing PostgreSQL grant/replay/revocation/atomic-audit service test: 1 passed.
- Three Admin web test files: 69 passed, including all seven permissions together,
  unknown-value rejection, both new labels, and explicit login navigation.
- Direct contract-only assertions pass for helper equality, checked-in revision
  membership, and every versioned table inventory/count. These do not exercise
  root ownership checks.
- Repository format, lint and type checks are recorded on the pull request.

The local account has no sudo access. The full root-owned backup/restore metadata
suite runs in the existing Control-plane validation CI gate; local contract
assertions do not replace that gate. No live grant, deployment, production data
change, or live restore was performed. Root's staging grant task verifies the
post-merge account projection separately.
