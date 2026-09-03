---
id: DEC-001
type: decision
title: Separate Public Learner Tenancy and Consent-Backed Enrollment
status: accepted-runtime-pending
version: v0.1-alpha
updated: 2026-09-01
supersedes:
  - GAP-ENR-001
tags:
  - ac/decision/tenancy
  - ac/decision/consent
---

# Separate public learner tenancy and consent-backed enrollment

Accepted repository decision: operations and public learner tenants are distinct active tenants. Verified current consent provisions only an active `learner` membership in the configured public learner tenant. The explicit `Start free course` action may create/reuse the canonical eligibility fact for the exact global Free Course and enroll in the same transaction.

Canonical evidence records consent version/timestamp, `start_free_course`, program slug, and policy version. It records no password, provider token, email, or analytics-derived authority. Positive history is reused; conflicting/negative history fails closed and is not overwritten.

- controlled-by: [[SRC-000-control-authority]], [[SRC-010-implementation-controls]], [[SRC-050-trust-operations]].
- repository ADR: [ADR-028](../../adr/0028-separate-public-learner-context-and-consent-backed-free-enrollment.md).
- config boundary: [Environment contract](../../contracts/ENVIRONMENT_CONTRACT.md).
- implements: [[API-002-catalog-enrollment]], [[IMP-002-platform-api-domain]], [[IMP-003-seed-bootstrap]].
- status: code/tests exist in the current worktree; exact-current tenant, consent, transaction, isolation, and staging proof is pending.
