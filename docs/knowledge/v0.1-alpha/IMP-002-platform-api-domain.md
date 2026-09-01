---
id: IMP-002
type: implementation
title: Platform API and Domain Implementation Map
status: uncommitted-candidate
version: v0.1-alpha
updated: 2026-09-01
tags:
  - ac/implementation/backend
---

# Platform API and domain implementation map

| Contract area               | HTTP/application files                                                                                                                                     | Domain/persistence files                                                                                                                                                                                                                       |
| --------------------------- | ---------------------------------------------------------------------------------------------------------------------------------------------------------- | ---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| identity/onboarding/session | [auth.py](../../../packages/python/ac_platform/http/auth.py)                                                                                               | [identity](../../../packages/python/ac_platform/identity/services.py), [onboarding](../../../packages/python/ac_platform/identity/onboarding.py), [tenancy provisioning](../../../packages/python/ac_platform/tenancy/learner_provisioning.py) |
| catalog/free enrollment     | [course.py](../../../packages/python/ac_platform/http/course.py)                                                                                           | [enrollment services](../../../packages/python/ac_platform/enrollment/services.py), [self-attestation](../../../packages/python/ac_platform/enrollment/self_attestation.py)                                                                    |
| learning/evidence           | [learning.py](../../../packages/python/ac_platform/http/learning.py)                                                                                       | [learning services](../../../packages/python/ac_platform/learning/services.py)                                                                                                                                                                 |
| certificates                | [certificates.py](../../../packages/python/ac_platform/http/certificates.py)                                                                               | [certificate services](../../../packages/python/ac_platform/certificates/services.py)                                                                                                                                                          |
| admin/recovery              | [admin_learning.py](../../../packages/python/ac_platform/http/admin_learning.py), [operations.py](../../../packages/python/ac_platform/http/operations.py) | audit, outbox, jobs, and recovery services                                                                                                                                                                                                     |

- implements: [[API-001-identity-onboarding]], [[API-002-catalog-enrollment]], [[API-003-learning-evidence]], [[API-004-session-settings]], [[API-005-admin-operations]].
- constrained-by: [[DEC-001-public-learner-tenancy-consent]], [[DEC-002-host-only-sessions]], [[DEC-003-canonical-progress-evidence]].
- validated-by: [[IMP-004-tests]].
- evidence boundary: files are implementation evidence; deployed behavior requires [[GATE-003-exact-release-staging]].
