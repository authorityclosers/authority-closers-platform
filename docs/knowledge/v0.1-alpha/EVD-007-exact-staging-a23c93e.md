---
id: EVD-007
type: evidence
title: Exact Staging Controller Smoke a23c93e
status: exact-staging-controller-smoke
version: v0.1-alpha
updated: 2026-09-04
release_sha: a23c93e6acebb7c6a0d31de1c3d5d7374f53be92
validation_run: 33836245175
tags:
  - ac/evidence/staging
  - ac/evidence/release
---

# Exact staging controller smoke — `a23c93e`

Observed 2026-09-04 (Asia/Kolkata). This record proves the named immutable
staging release and bounded trusted-controller smoke only. It does not close
G1, certify the full browser/device matrix, prove every authenticated workflow,
activate gated media/telemetry providers, or approve production.

## Immutable identity

- GitHub Application validation run
  [33836245175](https://github.com/authorityclosers/authority-closers-platform/actions/runs/33836245175)
  completed successfully for head SHA
  `a23c93e6acebb7c6a0d31de1c3d5d7374f53be92`, including release-image
  packaging.
- Exact artifact `9923608431`, named
  `ac-application-a23c93e6acebb7c6a0d31de1c3d5d7374f53be92`, was
  digest-bound as
  `sha256:3e7fb331ac0bcd5b6e156d10c4d7af1c70c53da3db89b85d1f651e0148f83389`
  and measured `175741376` bytes.
- The trusted release controller was hardened in
  [PR 22](https://github.com/authorityclosers/authority-closers-platform/pull/22)
  so transient SSH/SCP transport failures are bounded and the remote
  installation transaction is never retried after it begins.

## Transaction and recovery observations

- Previous staging release:
  `65ea3e1094ae462c071a70ef2463f5a8c7754196`.
- Pre-migration backup:
  `/srv/authority-closers/backups/application/staging/20260904T054929Z-pre-a23c93e6acebb7c6a0d31de1c3d5d7374f53be92.dump`.
- Forward migration reached the reviewed head `20260903_0016`.
- PostgreSQL, API, worker, learner web, and admin web were reconciled and
  reported healthy before edge cutover.
- The installer armed its automatic rollback contract for the transaction; no
  rollback was invoked because migration, service health, route checks, edge
  cutover, and post-cutover smoke all passed.
- The reviewed staging profile intentionally selected
  `AC_EXTERNAL_SIDE_EFFECTS_HOLD=false` with `AC_EMAIL_PROVIDER=resend`; the
  deployed worker environment matched that non-secret profile metadata and
  reported ready for email jobs. This is bounded staging email-provider
  activation, not evidence of provider delivery, non-email side effects, or any
  production activation. Secret values are not recorded here.

## Trusted controller observations

- Release files and running API, learner, and admin image identities matched
  the exact release.
- Learner root, `/healthz`, service worker, icons, and reviewed image assets
  returned `200` on the learner staging route.
- API `/health/live`, `/health/ready`, and `/v1/programs` returned `200` on the
  API staging route. `/docs` and `/openapi.json` returned `404`.
- Admin staging remained protected by the expected Cloudflare Access route.
- The legacy WordPress apex and `www` boundaries remained unchanged.
- Google OAuth start passed its host-only cookie and exact callback binding
  checks.

## Boundaries

This controller record contains no new screenshot or full visual acceptance,
no complete authenticated mutation matrix, no browser/device certification,
and no media-provider, telemetry-provider, reviewer, scoring, or broad-admin
activation. The pre-migration backup was created and validated by the installer,
but a restore was not exercised during this successful deployment. Earlier
evidence remains scoped to its named release. Production remains **NO-GO**.

- evidences: [[GATE-003-exact-release-staging]], [[EVD-006-exact-staging-65ea3e1]], [[HOME-01-learner-home]], [[RT-003-learning]].
- does-not-evidence: [[GATE-004-production-activation]], full G1 readiness,
  email delivery, non-email media/telemetry provider activation, or a restore
  drill.
