---
id: EVD-005
type: evidence
title: Exact Staging Controller Smoke 5c7333c5
status: exact-staging-controller-smoke
version: v0.1-alpha
updated: 2026-09-04
release_sha: 5c7333c5a588f5209acd5ca9b5ce0e03e20e16a4
validation_run: 33792101073
tags:
  - ac/evidence/staging
  - ac/evidence/release
---

# Exact staging controller smoke — `5c7333c5`

Observed 2026-09-04 (Asia/Kolkata). This record proves the named immutable
staging release and bounded controller/runtime smoke only. It does not close
G1, certify the full browser/device matrix, activate gated capabilities, or
approve production.

## Immutable identity

- [Application validation run 33792101073](https://github.com/authorityclosers/authority-closers-platform/actions/runs/33792101073)
  completed successfully for head SHA
  `5c7333c5a588f5209acd5ca9b5ce0e03e20e16a4`; both `validate` and
  `package-release-images` jobs passed.
- Exact artifact `ac-application-5c7333c5a588f5209acd5ca9b5ce0e03e20e16a4`
  (GitHub artifact `9908094123`) has digest
  `sha256:2e3d3aa675f7d67d5f92bb74aba792e61cb0a85dc6eac82ed5d002c39f209340`.
  Its reviewed bundle checksums are `1c1c1a8de9899a969281128a859caa3e4c9fd6bd9869e3bf001c36532cd83d3a`
  (`application-images.tar.gz`) and
  `a093b26735af583c0e058fd6a8f2d949f56dadde52fd6642256527a6a6618587`
  (`release-images.env`).
- Staging `current-staging` resolves to
  `/srv/authority-closers/application/releases/5c7333c5a588f5209acd5ca9b5ce0e03e20e16a4`;
  the release file checksum and deployment record passed.
- Reviewed runtime image references are API/worker
  `sha256:c29713e86358812150c07145148dcb8ceb700c0b9aebca0b22c8cf2111296c60`,
  learner `sha256:9ca183cd2d86c98d304e63e1483a145ceb43544cb06f3147b642c9766057aaac`,
  and admin `sha256:064bbaed69f27ef1292041cd7b1b0a7769f74f681c1ba22cafe664db164c09ac`.
  The pinned PostgreSQL image is
  `postgres@sha256:1c59e2c3c818eaa0f0628f695b36e7c9e362d6b219b36a54a32df645cbd7e1af`;
  migration head is `20260903_0016`.

## Controller and operator observations

- The trusted Windows controller (`pwsh 7.6.5`) re-proved the exact release
  read-only: API, worker, learner web, admin web, and PostgreSQL were in the
  expected running state; API, learner, admin, and PostgreSQL healthchecks were
  healthy, and the worker is running under its running-only contract.
- Learner smoke passed for `/` (`200`, `learner-staging`) and `/healthz`
  (`200`). API smoke passed for `/health/live`, `/health/ready`, and
  `/v1/programs` (`200`, `api-staging`). `/docs` and `/openapi.json` both
  returned `404`.
- Admin staging returned the expected Cloudflare Access `302` boundary to the
  reviewed Access tenant. The WordPress apex and `www` both remained `200`
  with WordPress markers, and the reviewed apex origin remained unchanged.
- Deployment-time controller OAuth proof passed the exact provider redirect,
  `no-store` response, same-surface staging callback, and paired host-only
  `Secure`/`HttpOnly`/`SameSite=Lax` state cookies bound to one signed
  transaction. No cookie, state, code, or secret is recorded. The read-only
  follow-up intentionally did not repeat this stateful probe.
- Authenticated Chrome operator observation at
  `https://staging.authorityclosers.com/learning` exposed the learner
  workspace, `My Learning`, one enrolled course, `Authority Closers Free
Course`, `In progress`, and `0 of 5 required activities`, with an
  `Open course` link. This is an accessibility-tree observation, not a
  screenshot or visual acceptance claim; the actor identity is intentionally
  omitted.
- External effects were held for this evidence follow-up: no deployment,
  enrollment, evidence mutation, mail request, OAuth transaction, payment,
  recording, or production action was initiated while recording this note.

## Boundaries

The exact release is now staging-deployed and controller-smoked; older
`27fafae` and `81635d1` evidence remains retained for its named releases.
Fresh enrollment/provenance/replay/isolation, learner mutation journeys,
responsive/accessibility completion, Edge/iOS/PWA, restore/rollback,
security/load/observability, media, reviewer, and broad admin gates remain
open. Production remains **NO-GO**.

- evidences: [[GATE-003-exact-release-staging]], [[HOME-01-learner-home]], [[RT-003-learning]].
- does-not-evidence: [[GATE-004-production-activation]], full G1 readiness, or any external side-effect activation.
