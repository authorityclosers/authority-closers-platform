---
id: GATE-003
type: test-gate
title: Exact-Release Staging Gate
status: open-for-current-candidate
version: v0.1-alpha
updated: 2026-09-01
tags:
  - ac/gate/staging
---

# Exact-release staging gate

The current dirty worktree must become an immutable commit and release bundle before candidate behavior can be called staging-proven. Required checks include:

- exact SHA/archive/image identity and migrations;
- fresh consent → public learner membership → explicit start → eligibility/enrollment with replay, audit, welcome email, and tenant negatives;
- auth/onboarding/session recovery and revision conflicts;
- canonical home, Module 1, draft, evidence, progress, settings and theme journeys;
- responsive, accessibility, Edge browser/PWA and real iOS Safari/Home Screen checks;
- provider/media gates only where approved;
- security, idempotency/concurrency, failure recovery, observability, restore, rollback, and side-effect reconciliation.

- required-by: every `runtime-pending` or `implementation-candidate` node.
- historical evidence: [[EVD-001-staging-27fafae]] and [[EVD-002-auth-81635d1]] remain valid only for their named releases.
- current candidate evidence: [[EVD-003-current-candidate-design-qa]] is local/reference evidence, not this gate.
- source: [workflow QA checklist](../../workflows/v0.1-alpha-experience/05-handoff-qa/qa-release-checklist.md).
