---
id: RT-001
type: route-family
title: Public and Authentication Routes
status: specification-ready
version: v0.1-alpha
updated: 2026-09-01
tags:
  - ac/route/public
  - ac/route/auth
---

# Public and authentication routes

| Browser route        | Screen/role    | Primary authority                                             |
| -------------------- | -------------- | ------------------------------------------------------------- |
| `/`                  | public catalog | published catalog API                                         |
| `/programs/{slug}`   | `COURSE-01`    | read-only published preview; safe return intent into auth/app |
| `/login`             | `AUTH-01`      | identity API                                                  |
| `/register`          | `AUTH-02`      | identity, exact consent, public learner tenant provisioning   |
| `/verify-email`      | `AUTH-03`      | one-time email challenge                                      |
| `/forgot-password`   | `AUTH-04`      | existence-neutral recovery command                            |
| `/reset-password`    | `AUTH-05`      | one-time reset challenge and session revocation               |
| `/auth/callback`     | `AUTH-06`      | signed OAuth transaction and bounded recovery result          |
| `/session-expired`   | `AUTH-07`      | reauthentication and return intent                            |
| `/terms`, `/privacy` | policy pages   | existing reviewed copy only                                   |

The public program route never mutates enrollment. Its primary action signs in
or opens the authenticated learner app, where [[HOME-01-learner-home]] owns the
explicit consent-backed `Start free course` command.

- renders: [[SF-AUTH-001-authentication]] and [[SF-COURSE-001-free-course]].
- appears-in: [[JRN-01-account-to-first-value]] and [[JRN-02-identity-recovery]].
- calls: [[API-001-identity-onboarding]], [[API-002-catalog-enrollment]], [[API-004-session-settings]].
- implementation: [route registry](../../../apps/learner-web/app/lib/routes.ts), [public page](../../../apps/learner-web/app/page.tsx), and [program page](../../../apps/learner-web/app/programs/[slug]/page.tsx).
- auth boundary: [[DEC-002-host-only-sessions]].
- supersedes: prior same-file wording that assigned the enrollment command to
  `/programs/{slug}`; decision authority is
  [[DEC-006-authenticated-in-app-free-course-enrollment]].
