---
id: RT-004
type: route-family
title: Progress, Settings, Completion, and System Routes
status: runtime-pending
version: v0.1-alpha
updated: 2026-09-01
tags:
  - ac/route/learner
  - ac/route/system
---

# Progress, settings, completion, and system routes

| Browser route                   | Screen/authority                                    | Boundary                                                    |
| ------------------------------- | --------------------------------------------------- | ----------------------------------------------------------- |
| `/progress`                     | `PROG-01`; learning projection                      | implementation candidate; canonical facts only              |
| `/settings`                     | `SET-01..05`; `/v1/me`, onboarding and session APIs | implementation candidate; bounded browser-local appearance mode and variants |
| `/learn/{programSlug}/complete` | completion predicate                                | incomplete reasons or course-complete state                 |
| `/certificates/{certificateId}` | self-scoped certificate API                         | course completion certificate, not competency certification |
| `/offline`                      | `SYS-03`; static PWA shell                          | no protected data or offline authority                      |

- renders: [[PROG-01-progress]], [[SF-SET-001-settings]], [[SF-SYS-001-universal-states]], [[VAR-THEME-001-theme]].
- appears-in: [[JRN-04-profile-settings-appearance]] and [[JRN-05-resilient-web-pwa]].
- calls: [[API-003-learning-evidence]] and [[API-004-session-settings]].
- implementation: [progress page](../../../apps/learner-web/app/progress/page.tsx), [settings page](../../../apps/learner-web/app/settings/page.tsx), [completion page](../../../apps/learner-web/app/learn/[programSlug]/complete/page.tsx), and [offline page](../../../apps/learner-web/app/offline/page.tsx).
- known-limitation: exact-current staging and browser/device evidence is open.
