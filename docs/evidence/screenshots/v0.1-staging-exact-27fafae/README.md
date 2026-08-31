# Authority Closers v0.1 exact staging journey evidence

Captured and reviewed on 2026-09-01 from the deployed staging release:

- commit: `27fafaea1e5de41ae6a830746b1d832b42c7d444`
- learner: `https://staging.authorityclosers.com`
- admin: `https://admin-staging.authorityclosers.com`
- API: `https://api-staging.authorityclosers.com`
- dedicated learner: `admin+alpha-learner@authorityclosers.com`
- infrastructure and Google admin: `admin@authorityclosers.com`

No password, reset token, verification token, OAuth code, API key, session
cookie, or secret is recorded here. The learner password is established with
the newest transactional reset message delivered to the Authority Closers
admin mailbox.

## Exact-release captures

[Open the complete journey contact sheet](journey-contact-sheet.png) for a
single-view index of the captured learner, auth, public, and admin surfaces.

|   # | File                                                           | Route or proof                                   | What it proves                                                                                                                            |
| --: | -------------------------------------------------------------- | ------------------------------------------------ | ----------------------------------------------------------------------------------------------------------------------------------------- |
|  01 | [Learner home](01-learner-home-authorized.png)                 | `/home`                                          | Password-authenticated learner shell, canonical learner identity, server-authorized current course, and real `0 / 5` progress projection. |
|  02 | [Module path](02-module-path.png)                              | `/learn/authority-closers-free-course`           | Four published modules and the five-activity Module 1 loop.                                                                               |
|  03 | [Video](03-video.png)                                          | `/activity/73dfbbf7-5f2c-5e88-ad27-e5c84c65690f` | VIDEO workspace and honest media-provider gate.                                                                                           |
|  04 | [Reflection](04-reflection.png)                                | `/activity/a6d22402-b606-5987-a9d2-f5d96c8cccba` | Restored server draft, in-progress state, character count, and controlled submission lock.                                                |
|  05 | [Implementation](05-implementation.png)                        | `/activity/00f23259-a74b-5d36-96df-e57ab9584b32` | Implementation-evidence workspace and reviewer-gated submission.                                                                          |
|  06 | [Review](06-review.png)                                        | `/activity/2c14f1cc-712c-5c71-9273-c2a68bb1b906` | Review workspace and current authorized state.                                                                                            |
|  07 | [Improve](07-improve.png)                                      | `/activity/e5de3ba2-52a6-572b-8aad-9b0183035e76` | Improve workspace and current authorized state.                                                                                           |
|  08 | [Recovery confirmation](08-password-recovery-confirmation.png) | `/forgot-password`                               | Non-enumerating live recovery response after a real request.                                                                              |
|  09 | [Mail delivery record](09-transactional-mail-proof.md)         | Resend + worker runtime                          | Exact-release provider configuration and a newly delivered recovery message.                                                              |
|  10 | [Google admin home](10-google-admin-home.png)                  | Google callback → `/home`                        | Google sign-in completed as `admin@authorityclosers.com` and rendered owner context.                                                      |
|  11 | [Public catalog](11-public-catalog.png)                        | `/`                                              | API-backed published course discovery.                                                                                                    |
|  12 | [Login](12-login.png)                                          | `/login`                                         | Email/password and Google learner authentication entry points.                                                                            |
|  13 | [Registration](13-register.png)                                | `/register`                                      | Consent-gated password and Google registration entry points.                                                                              |
|  14 | [Program detail](14-program-detail.png)                        | `/programs/authority-closers-free-course`        | Published modules, activity count, enrollment action, and learner-path link.                                                              |
|  15 | [Admin staging](15-admin-staging.png)                          | admin `/`                                        | Cloudflare Access-protected owner session, tenant context, read-only admin foundation, and no fabricated operational records.             |
|   — | [Drive/live home comparison](comparison-shell-home.png)        | approved desktop shell + live `/home`            | Source and implementation reviewed together; viewport mismatch is explicit.                                                               |

## Runtime proofs

- Deployment admitted the exact commit-bound archive and exact running image
  set for `27fafae`.
- PostgreSQL migration and privilege steps passed.
- API, worker, learner, admin, and PostgreSQL containers are healthy.
- Learner root, health, PWA assets, API live/ready/programs, Cloudflare Access,
  Google start/callback binding, and the legacy WordPress boundary passed the
  deployment smoke gate.
- Worker runtime reports `AC_EMAIL_PROVIDER=resend`,
  `AC_EXTERNAL_SIDE_EFFECTS_HOLD=false`, and an AC sender configured. The
  sender value and credentials are intentionally not recorded.
- A fresh staging recovery request produced a Resend row with status
  `delivered` and subject `Reset your password — Authority Closers`.
- Password login completed as `admin+alpha-learner@authorityclosers.com` and
  landed on `/home` with the free course visible.
- Google login completed as `admin@authorityclosers.com`, returned to `/home`,
  and rendered `owner` access.

## Approved Drive references used

The source files remain in the preceding controlled reference pack and were
downloaded by exact Drive ID, not filename guess:

- [Auth registration](../v0.1-staging-exact-5b55a05/ref-auth-registration.png)
- [Desktop learner shell](../v0.1-staging-exact-5b55a05/ref-shell-desktop-home.png)
- [Mobile learner shell](../v0.1-staging-exact-5b55a05/ref-shell-mobile-home.png)
- [Desktop course overview](../v0.1-staging-exact-5b55a05/ref-course-desktop-overview.png)
- [Mobile course outline](../v0.1-staging-exact-5b55a05/ref-course-mobile-outline.png)
- [Mobile reflection](../v0.1-staging-exact-5b55a05/ref-reflection-mobile.png)
- [Desktop implementation](../v0.1-staging-exact-5b55a05/ref-implementation-desktop.png)
- [Admin overview](../v0.1-staging-exact-5b55a05/ref-admin-overview.png)

## Known boundaries

1. Current-release authenticated mobile screenshots are still required for
   complete cross-device visual acceptance; the selected Chrome connection
   did not apply a temporary viewport override.
2. Media playback is not activated before the provider/policy gate.
3. Evidence submission is not activated before independent reviewer
   assignment.
4. Fresh self-enrollment remains blocked on controlled eligibility fact
   `PROV-G1-AGE-ELIGIBILITY-POLICY`; consent is not treated as eligibility.
5. Broad SaaS, simulator/call-review engines, native Windows/iOS, billing,
   SSO/SCIM, and enterprise breadth remain extension contracts.
6. Production is **NO-GO** until production secrets, database/bootstrap,
   backup/restore, DNS, Access, rollback, observability, and exact-release
   runtime gates are independently proven. The legacy apex WordPress site is
   not the new LMS.
