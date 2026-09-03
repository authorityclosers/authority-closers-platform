---
id: DEC-006
type: decision
title: Authenticated In-App Free Course Enrollment
status: accepted-candidate
version: v0.1-alpha
updated: 2026-09-01
supersedes:
  - REQUIRED-PUBLIC-PROGRAM-ENROLLMENT-DETOUR
tags:
  - ac/decision/enrollment
  - ac/decision/ux
---

# Authenticated in-app Free Course enrollment

The learner app owns the explicit `Start free course` interaction. A public program page may preview the published course and preserve a return path through authentication, but it is not required to enroll. The server remains authoritative for consent, public learner tenancy, eligibility, enrollment and access.

The action may recover a verified, consented learner session that still points to another active tenant by ensuring the exact configured public learner membership and selecting it before canonical eligibility/enrollment. It does not accept a person or tenant from the client and does not make analytics or payment-provider state authoritative.

- controlled-by: [[SRC-000-control-authority]], [[SRC-010-implementation-controls]], [[DEC-001-public-learner-tenancy-consent]].
- research-informed-by: [[SRC-021-evidence-based-learner-experience]].
- appears-in: [[HOME-01-learner-home]], [[JRN-01-account-to-first-value]], [[API-002-catalog-enrollment]].
- evidence-required: unit, PostgreSQL transaction and exact-release staging journey proof before production.
