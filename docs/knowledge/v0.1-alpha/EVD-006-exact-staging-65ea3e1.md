---
id: EVD-006
type: evidence
title: Exact Staging Controller Smoke 65ea3e1
status: exact-staging-controller-smoke
version: v0.1-alpha
updated: 2026-09-04
release_sha: 65ea3e1094ae462c071a70ef2463f5a8c7754196
validation_run: 33802834176
tags:
  - ac/evidence/staging
  - ac/evidence/release
---

# Exact staging controller smoke — `65ea3e1`

Observed 2026-09-04 (Asia/Kolkata). This record proves the named immutable
staging release and bounded trusted-controller smoke only. It does not close
G1, certify the full browser/device matrix, prove route-specific authenticated
behavior, activate gated capabilities, or approve production.

## Immutable identity

- The GitHub Application `workflow_dispatch` validation run
  [33802834176](https://github.com/authorityclosers/authority-closers-platform/actions/runs/33802834176)
  completed successfully for head SHA
  `65ea3e1094ae462c071a70ef2463f5a8c7754196`; both `validate` and
  `package-release-images` jobs passed.
- Release artifact `9912047929` has digest
  `sha256:0a1c913928247599a0ce6641df8636b4f6aa364c703387fa98540b55a380abde`.

## Trusted controller observations

- The trusted controller matched the exact release and image identities, and
  all five expected services were in the expected state.
- Learner root, health, and asset checks passed.
- API `/health/live`, `/health/ready`, and `/v1/programs` returned `200`.
  `/docs` and `/openapi.json` returned `404`.
- Admin Cloudflare Access, WordPress, and OAuth boundary checks passed.
- External side effects were held while recording this note; no activation is
  claimed from this controller smoke.

## Boundaries

This controller record contains no screenshot or visual acceptance, no
route-specific authenticated learner proof, no enrollment or evidence-mutation
proof, and no browser/device, restore/rollback, security, observability,
media, reviewer, or broad-admin gate closure. The earlier exact-release records
remain retained for their named releases; this node does not replace EVD-005 or
transfer its `5c7333c5` authenticated `/learning` observation to this release.
Production remains **NO-GO**.

- evidences: [[GATE-003-exact-release-staging]], [[EVD-005-exact-staging-5c7333c5]], [[HOME-01-learner-home]], [[RT-003-learning]].
- does-not-evidence: [[GATE-004-production-activation]], full G1 readiness, or any external side-effect activation.
