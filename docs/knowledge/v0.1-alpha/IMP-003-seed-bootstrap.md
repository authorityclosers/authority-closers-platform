---
id: IMP-003
type: implementation
title: Free Course Seed, Tenancy, and Bootstrap Map
status: uncommitted-candidate
version: v0.1-alpha
updated: 2026-09-01
tags:
  - ac/implementation/seed
  - ac/implementation/tenancy
---

# Free Course seed, tenancy, and bootstrap map

The versioned seed defines the exact program slug/title, four shift titles, five required Module 1 activities, and topology-only Modules 2–4: [free_course_foundation_v1.json](../../../packages/python/ac_platform/seed/data/free_course_foundation_v1.json).

Bootstrap/configuration files:

- [application bootstrap](../../../packages/python/ac_platform/bootstrap/application.py)
- [bootstrap CLI](../../../packages/python/ac_platform/bootstrap/cli.py)
- [application settings](../../../packages/python/ac_platform/application/settings.py)
- [environment contract](../../contracts/ENVIRONMENT_CONTRACT.md)
- [first-tenant bootstrap runbook](../../runbooks/FIRST_TENANT_OWNER_BOOTSTRAP.md)
- [staging seed runbook](../../runbooks/STAGING_FREE_COURSE_SEED.md)

The public learner tenant command is idempotent and creates no person or membership. Registration/login provisions learner membership after verified current consent. The explicit Free Course start creates/reuses eligibility and enrollment under [[DEC-001-public-learner-tenancy-consent]].

- feeds: [[SF-COURSE-001-free-course]], [[MOD-01-module-one]], [[JRN-03-module-1-learning-loop]].
- validated-by: [[IMP-004-tests]] and [[GATE-003-exact-release-staging]].
