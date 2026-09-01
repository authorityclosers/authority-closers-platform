---
id: IMP-004
type: implementation
title: Test and Verification Implementation Map
status: mixed-evidence
version: v0.1-alpha
updated: 2026-09-01
tags:
  - ac/implementation/tests
---

# Test and verification implementation map

| Test family                  | Representative files                                                                                                                                                                                                                                                                                                       | Validates                                                                               |
| ---------------------------- | -------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | --------------------------------------------------------------------------------------- |
| learner UI/API               | [learner-ui.test.ts](../../../apps/learner-web/app/lib/learner-ui.test.ts), [learner-api.test.ts](../../../apps/learner-web/app/lib/learner-api.test.ts), [local-drafts.test.ts](../../../apps/learner-web/app/lib/local-drafts.test.ts), [theme-control.test.ts](../../../apps/learner-web/app/lib/theme-control.test.ts) | screens, route links, client idempotency, drafts, theme                                 |
| auth/onboarding              | [auth route tests](../../../tests/unit/http/test_auth_routes.py), [onboarding tests](../../../tests/unit/identity/test_onboarding.py), [password PostgreSQL tests](../../../tests/integration/test_password_identity_http_postgresql.py)                                                                                   | identity, consent, session, revision and recovery                                       |
| catalog/enrollment/bootstrap | [course route tests](../../../tests/unit/http/test_course_routes.py), [course PostgreSQL tests](../../../tests/integration/test_course_http_postgresql.py), [bootstrap PostgreSQL tests](../../../tests/integration/test_bootstrap_postgresql.py)                                                                          | published catalog, free eligibility/enrollment, tenant bootstrap, idempotency/isolation |
| learning/evidence            | [learning unit tests](../../../tests/unit/http/test_learning_routes.py), [learning domain tests](../../../tests/unit/learning/test_evidence.py), [learning PostgreSQL tests](../../../tests/integration/test_learning_http_postgresql.py)                                                                                  | projection, draft, evidence, prerequisites and append-safe behavior                     |
| security/recovery/infra      | [HTTP boundary](../../../tests/security/test_http_boundary.py), [rate limits](../../../tests/security/test_rate_limits.py), [restore drill](../../../tests/infra/test_restore_drill.py), [release tests](../../../tests/infra/test_application_release.py)                                                                 | origin, limits, restore hold, release identity                                          |

Historical pass counts belong only to their named evidence pages. This graph build did not rerun the application suite; its required validation is structural/formatting only.

- validates: [[GATE-001-G0-control-plane]], [[GATE-002-G1-free-course]], [[GATE-003-exact-release-staging]].
- evidence: [[EVD-001-staging-27fafae]] and [[EVD-002-auth-81635d1]].
