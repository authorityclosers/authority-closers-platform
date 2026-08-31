# Drive-aligned v0.1 visual evidence

Captured on 2026-08-31 from the local AC learner (`127.0.0.1:3100`), admin
(`127.0.0.1:3101`), and API (`127.0.0.1:8100`) runtimes using the Codex
in-app browser. The selected source direction is the approved Drive Clarity
Grid family. These are viewport captures, not stitched full-page images.

## Desktop — 1440 × 900

|   # | File                                                  | Route/state                           | Evidence boundary                                                         |
| --: | ----------------------------------------------------- | ------------------------------------- | ------------------------------------------------------------------------- |
|  01 | [Login](01-login-desktop.png)                         | `/login`                              | Email/password plus eligible-existing-person Google authentication        |
|  02 | [Registration](02-register-desktop.png)               | `/register`                           | Consent-gated email/password registration; no learner Google registration |
|  03 | [Session expired](03-session-expired-desktop.png)     | `/session-expired`                    | Explicit 401 reauthentication and durable-work reassurance                |
|  04 | [Onboarding](04-onboarding-loading-desktop.png)       | `/onboarding` loading                 | Progressive-onboarding shell without fabricated profile state             |
|  05 | [Learner home](05-learner-home-offline-desktop.png)   | `/home?state=offline`                 | Offline state in the Clarity learner shell                                |
|  06 | [Universal loading](06-universal-loading-desktop.png) | `/programs/free-course?state=loading` | Public loading state                                                      |
|  07 | [Admin overview](07-admin-overview-desktop.png)       | `/`                                   | Read-only admin IA; no operational records asserted                       |
|  08 | [Admin people](08-admin-people-desktop.png)           | `/people`                             | Empty/truthful people foundation                                          |
|  09 | [Course studio](09-admin-studio-desktop.png)          | `/catalog`                            | Locked version/studio contract; no publish or media claim                 |

## Mobile — 390 × 844

|   # | File                                               | Route/state           | Evidence boundary                              |
| --: | -------------------------------------------------- | --------------------- | ---------------------------------------------- |
|  10 | [Login](10-login-mobile.png)                       | `/login`              | Responsive access layout                       |
|  11 | [Registration](11-register-mobile.png)             | `/register`           | Responsive email/password registration         |
|  12 | [Session expired](12-session-expired-mobile.png)   | `/session-expired`    | Responsive reauthentication                    |
|  13 | [Onboarding](13-onboarding-loading-mobile.png)     | `/onboarding` loading | Responsive progressive-onboarding shell        |
|  14 | [Learner home](14-learner-home-offline-mobile.png) | `/home?state=offline` | Mobile shell, offline state, bottom navigation |
|  15 | [Admin overview](15-admin-overview-mobile.png)     | admin `/`             | Responsive admin foundation                    |
|  16 | [Course studio](16-admin-studio-mobile.png)        | admin `/catalog`      | Responsive locked studio foundation            |

Every capture contains one `main` landmark and one `h1`. The checked mobile
documents had zero horizontal overflow. The auth and session-expired captures
contain exactly one form. Local admin capture uses the bounded
`AC_ADMIN_LOCAL_PREVIEW=1` route mode; the visible session status remains
truthful and is not converted into a fake verified actor.

This pack does not prove an authenticated learner ready state, a Google
callback/session, real verification or recovery delivery, approved lesson
media, or an enabled reviewer workflow. Those require exact-release staging
runtime evidence and must not be replaced with browser fixtures.
