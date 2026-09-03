---
id: IMP-001
type: implementation
title: Learner Web Implementation Map
status: implementation-candidate
version: v0.1-alpha
updated: 2026-09-01
tags:
  - ac/implementation/frontend
---

# Learner web implementation map

| Area                  | Current files                                                                                                                                                                                                                                               | Graph nodes                                                                                                                  |
| --------------------- | ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | ---------------------------------------------------------------------------------------------------------------------------- |
| route registry        | [routes.ts](../../../apps/learner-web/app/lib/routes.ts)                                                                                                                                                                                                    | [[RT-001-public-auth]], [[RT-002-onboarding-home]], [[RT-003-learning]], [[RT-004-progress-settings-system]]                 |
| auth/onboarding       | [login-form.tsx](../../../apps/learner-web/app/components/login-form.tsx), [password-auth-forms.tsx](../../../apps/learner-web/app/components/password-auth-forms.tsx), [onboarding-form.tsx](../../../apps/learner-web/app/components/onboarding-form.tsx) | [[SF-AUTH-001-authentication]], [[ONB-01-onboarding]]                                                                        |
| catalog/learning      | [learner-runtime.tsx](../../../apps/learner-web/app/components/learner-runtime.tsx), [course-path.tsx](../../../apps/learner-web/app/components/course-path.tsx), [activity-renderers.tsx](../../../apps/learner-web/app/components/activity-renderers.tsx) | [[HOME-01-learner-home]], [[SF-COURSE-001-free-course]], [[MOD-01-module-one]], [[ACT-02-reflection]]                        |
| progress/settings     | [progress-runtime.tsx](../../../apps/learner-web/app/components/progress-runtime.tsx), [settings-runtime.tsx](../../../apps/learner-web/app/components/settings-runtime.tsx)                                                                                | [[PROG-01-progress]], [[SF-SET-001-settings]]                                                                                |
| appearance/resilience | [theme-control.tsx](../../../apps/learner-web/app/components/theme-control.tsx), [surface-state.tsx](../../../apps/learner-web/app/components/surface-state.tsx), [sw.js](../../../apps/learner-web/public/sw.js)                                           | [[VAR-THEME-001-theme]], [[SF-SYS-001-universal-states]], [[JRN-05-resilient-web-pwa]]                                       |
| API client/drafts     | [learner-api.ts](../../../apps/learner-web/app/lib/learner-api.ts), [local-drafts.ts](../../../apps/learner-web/app/lib/local-drafts.ts)                                                                                                                    | [[API-001-identity-onboarding]], [[API-002-catalog-enrollment]], [[API-003-learning-evidence]], [[API-004-session-settings]] |

Status is path-observed in the current repository. Exact staging inclusion and
acceptance are release-scoped; this node does not by itself claim route
acceptance or production behavior.

- controlled-by: [[SRC-070-repository-interpretations]].
- validated-by: [[IMP-004-tests]] and [[GATE-003-exact-release-staging]].
- current evidence: [[EVD-003-current-candidate-design-qa]].
