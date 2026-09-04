---
id: GATE-003
type: test-gate
title: Exact-Release Staging Gate
status: open-for-current-candidate
version: v0.1-alpha
updated: 2026-09-04
tags:
  - ac/gate/staging
---

# Exact-release staging gate

The candidate must be represented by an immutable commit and release bundle
before its behavior can be called staging-proven. The earlier bounded
controller smoke for release `5c7333c5a588f5209acd5ca9b5ce0e03e20e16a4` remains
recorded; the latest bounded controller smoke for release
`a23c93e6acebb7c6a0d31de1c3d5d7374f53be92` is also recorded, while the full
gate remains open for the required checks below:

- exact SHA/archive/image identity and migrations;
- fresh consent → public learner membership → explicit start → eligibility/enrollment with replay, audit, welcome email, and tenant negatives;
- auth/onboarding/session recovery and revision conflicts;
- canonical home, Module 1, draft, evidence, progress, settings and theme journeys;
- responsive, accessibility, Edge browser/PWA and real iOS Safari/Home Screen checks;
- provider/media gates only where approved;
- security, idempotency/concurrency, failure recovery, observability, restore, rollback, and side-effect reconciliation.

- required-by: every `runtime-pending` or `implementation-candidate` node.
- historical evidence: [[EVD-001-staging-27fafae]] and [[EVD-002-auth-81635d1]] remain valid only for their named releases.
- prior exact-release evidence: [[EVD-005-exact-staging-5c7333c5]] remains valid
  only for its named `5c7333c5` release and records a text-only authenticated
  `/learning` accessibility observation.
- current exact-release evidence: [[EVD-007-exact-staging-a23c93e]] records
  GitHub CI/package identity and trusted-controller staging smoke for
  `a23c93e`; it contains no complete authenticated learner-route or visual acceptance
  proof.
- prior exact-release evidence: [[EVD-006-exact-staging-65ea3e1]] remains valid
  only for its named `65ea3e1` release.
- current candidate visual evidence: [[EVD-003-current-candidate-design-qa]]
  remains local/reference evidence; it is not visual proof for this gate.
- source: [workflow QA checklist](../../workflows/v0.1-alpha-experience/05-handoff-qa/qa-release-checklist.md).
