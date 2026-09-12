# Production email activation candidate

Status: implemented and locally verified in an isolated activation worktree;
not pushed, merged, deployed or activated.
Baseline commit: `f0313e2f4cf52709c41be3f3c13d5024154cbb69`.
Branch: `codex/production-email-activation-20260913`.
The eight reviewed patch paths were identical between the earlier
`6e99eaa401afa5118336079fab908843c4550977` packet base and this corrected held
release. The patch applied without changing any intervening fixes. The held
release worktree remained untouched.
Retained consent version: `ac-learner-terms-privacy-2026-09-13-v1` for both staging and production.

This second immutable release changes production's source-owned hold/provider
pair to `false`/`resend` and aligns the installer's exact profile expectations.
Practice remains disabled. Media, AI and all other provider capabilities are
unchanged. Compose still supplies mail provider configuration and credentials
only to the worker; API and migrator receive no mail credential.

The foundation backup resolver accepts only the two exact production pairs:
held/fake and released/resend. Install that compatible reviewed foundation before
application activation so local capture works before and after the transition.
Mixed pairs fail closed. No quota, cache, retention or capture behavior changes.

Application prerequisites are: committed active operations and distinct public
learner UUIDs from the held bootstrap; verified prod `/application` sender/key
pair and sender domain facts; the retained exact approved production consent
version in the source-owned profile contract; reviewed
initial queue/delivery scope; and canonical durable recovery `READY`. This
packet contains no credentials, sender value, tenant UUID or consent invention.
It creates no identity, owner, permission, session or learner consent.

Local validation on 2026-09-13 used the existing Python environment with
`PYTHONPATH` bound to this isolated worktree's `packages/python`, plus Git Bash
for the executable shell contracts. All selected tests passed without skips:

- `pytest -q tests/infra/test_application_release.py tests/infra/test_postgres_backup.py -k 'production_activation_pairs or stale_staging_provider_profile or profile or worker or email'`
  — 31 passed, 120 deselected. This covers exact production backup pairs,
  mixed/unreviewed pair rejection, staging policy, profile parsing, and the
  worker-only mail configuration boundary.
- `pytest -q tests/infra/test_application_release.py -k 'production_activation_policy or production_practice or compose_for or policy_off or consent'`
  — 12 passed, 73 deselected. This covers stale production activation policy,
  exact consent, production practice refusal, and Compose profile/rollback
  behavior using synthetic configuration.
- `pytest -q tests/unit/application/test_settings.py tests/unit/worker/test_worker.py -k 'operations or resend or readiness or provider or recovery'`
  — 20 passed, 174 deselected. This retains fail-closed credential-pair and
  operations settings, local/durable worker holds, and recovery fencing.
- `bash tests/infra/test-security-invariants.sh` — passed.
- Ruff lint and format checks for the three changed Python files, installer
  `bash -n`, and `git diff --check` — passed.

These are local source/configuration and mocked worker checks. No production
database, tenant command, provider request, deployment or email send was run.
Release CI, immutable images, exact deployment verification, and bounded real
email verification/recovery evidence remain required after the operational
prerequisites are satisfied. Source preparation does not satisfy the runtime
activation prerequisites.

The temporary remote backup/RPO pause remains accepted and visible; this record
does not claim remote recovery success or a provider-enforced billing ceiling.
Rollback and post-write forward recovery continue to use canonical release
procedures. Historic release evidence is preserved.
