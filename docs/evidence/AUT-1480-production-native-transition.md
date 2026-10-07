# AUT-1480 production native transition

Source implementation evidence, 7 October 2026, for the CTO decision on
[AUT-1476](/AUT/issues/AUT-1476). Scope: release engine, focused tests and runbook.
No dev-visible screen/API change. Root retains production execution and pause
clearing; this source change requires CTO review and CEO SHA-bound approval.

## Implementation

The existing governed native transition now takes `staging` or `production`
through preparation, receipt selection, preflight, install, publication,
restoration and failure containment. Receipts are
`native-preparations/<env>-<native-sha>.json`, with an explicit environment on
new receipts. Staging receipts without that field remain usable unchanged.
An opposite-environment receipt is never selected, and a receipt copied under
the wrong environment prefix refuses.

Production additionally checks staging's live activation resolves to the exact
native source being prepared. Deployment preflight repeats that check. All
approval checks and carried approval bytes come from production's own current
activation, with the existing digest and one-day minimum lifetime guards.
Previous units must live under production's own operator inputs; renderer,
unit readback, deployment receipts, activation publication, healthy-core checks
and application-only rollback all bind to the requested environment.

Existing target provenance/OCI/source checks, strict native-input comparison,
installer, approval rules and promotion guards remain in force. Preparation
starts no helper and leaves runtime/publication/containment unchanged. A failed
armed transition pauses the requested environment, records its failed core,
restores pinned native units/helper before the core predecessor, and verifies
the restoration. Production failure leaves staging's state unchanged.

## Verification

Tests use fictional native CI/OCI records, approvals, unit descriptors and
systemd/Docker/core delivery adapters. Coverage includes both environments'
preparation and CLI, publication, dry-run invariance, missing rollback pins,
helper/activation/core/readiness failures, unsuccessful recovery, receipt
isolation and unchanged legacy staging receipts. Engine preflight cases also
cover missing/different live staging native identity, staging pins supplied to
production, production approval expiry/digest, production-only authority, and
rechecking staging after a preparation receipt was saved. Matching native
ancestor delivery and changed-input refusal run through the staging timer and
production promotion paths.

Source base: `1c06c4af14222a9de71334b25f3e373cf1fa4906` (latest main at task start).

- `uv run pytest -q tests/infra/test_ac_release.py tests/infra/test_sales_xray_native_installer.py tests/infra/test_ac_release_foundation_install.py tests/infra/test_ac_release_train.py tests/infra/test_ac_release_admin.py tests/unit/test_prepare_sales_xray_native_activation.py tests/unit/test_native_artifact_compatibility.py`: **482 passed**, 183.69 seconds.
- `uv run ruff format --check packages/python tests infra/release/ac_release.py`: **1049 files formatted**.
- `uv run ruff check packages/python tests infra/release/ac_release.py`: **passed**.
- `uv run mypy packages/python`: **passed**, 432 source files.
- `pnpm exec prettier --check docs/runbooks/RELEASE_ENGINE.md docs/evidence/AUT-1480-production-native-transition.md`: **passed**.
- `git diff --check` and latest-main `ac-gate check`: **passed**.
- `python3 infra/release/ac_release.py prepare-native --help`: **staging and production accepted**, both predecessor pin options required.

Ordinary PR CI and exact reviewed head are recorded on the source task.
No real provider/customer/database calls or host execution occurred.

## Root handoff

[Production preparation/resume runbook](../runbooks/RELEASE_ENGINE.md#production-native-preparation-and-resume)
contains the production dry-run, saved-receipt fields and existing promotion
rehearsal. Root installs only the exact reviewed merged engine through the
locked clean-source installer, verifies flags and identities, supplies recorded
production predecessor pins and retains the preparation/rehearsal evidence.
Production pause clearing and live installation are outside this source card.
