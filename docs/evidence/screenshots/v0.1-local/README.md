# v0.1 local journey screenshot index

Captured on 2026-08-31 from the local Docker-backed v0.1 candidate. Learner web ran at `http://localhost:3000`, admin web at `http://localhost:3001`, and the API at `http://localhost:8000` with PostgreSQL, Mailpit, and Jaeger from the repository Compose stack.

These images prove the rendered UI and responsive contracts named below. They are not staging-deployment evidence. The local catalog intentionally remained empty because the controlled seed contract is staging-only and requires an existing canonical admin or owner actor plus an exact release marker. No direct SQL or unapproved fixture was used to manufacture course state.

## Learner desktop — 1440 × 900

| # | File | Route contract | Evidence status |
|---:|---|---|---|
| 01 | [Public home](01-learner-public-home-desktop.png) | `/` | API-backed empty catalog; no local fallback content |
| 02 | [Register](02-register-desktop.png) | `/register` | Email/password, age, policy, and service-email consent UI |
| 03 | [Verify email](03-verify-email-desktop.png) | `/verify-email` | Verification boundary and resend contract |
| 04 | [Login](04-login-desktop.png) | `/login` | Password session entry UI |
| 05 | [Forgot password](05-forgot-password-desktop.png) | `/forgot-password` | Recovery request UI |
| 06 | [Reset password](06-reset-password-desktop.png) | `/reset-password` | Token/password reset UI |
| 07 | [Terms](07-terms-desktop.png) | `/terms` | Versioned policy surface |
| 08 | [Privacy](08-privacy-desktop.png) | `/privacy` | Versioned policy surface |
| 09 | [Offline fallback](09-offline-fallback-desktop.png) | `/offline` | PWA/offline recovery surface |
| 10 | [Onboarding](10-onboarding-auth-boundary-desktop.png) | `/onboarding` | Progressive onboarding shell; authentication boundary |
| 11 | [Learner home](11-learner-home-auth-boundary-desktop.png) | `/home` | Protected learner-home authentication boundary |
| 12 | [Program detail](12-program-detail-empty-desktop.png) | `/programs/free-course` | API-backed empty/not-found handling |
| 13 | [Learning path](13-learning-path-auth-boundary-desktop.png) | `/learn/free-course` | Protected learning-path authentication boundary |
| 14 | [Module](14-module-auth-boundary-desktop.png) | `/learn/free-course/module/module-01` | Protected dynamic module/not-found boundary |
| 15 | [Universal loading](15-universal-loading-desktop.png) | `/programs/free-course?state=loading` | Loading-state contract |
| 16 | [API error](16-universal-error-desktop.png) | `/programs/free-course?state=error` | API program-not-found error with retry action; `error` falls back to the default state parser |
| 17 | [Universal offline](17-universal-offline-desktop.png) | `/programs/free-course?state=offline` | Offline-state contract |
| 18 | [Universal locked](18-universal-locked-desktop.png) | `/learn/free-course?state=locked` | Locked-state contract |

## Admin/studio desktop — 1440 × 900

Admin images use the explicitly bounded `AC_ADMIN_LOCAL_PREVIEW=1` mode. They prove the separate admin information architecture and locked mutation design, not production admin authentication.

| # | File | Route | Evidence status |
|---:|---|---|---|
| 19 | [Operations overview](19-admin-overview-desktop.png) | `/` | Local preview; read-only operations IA |
| 20 | [People](20-admin-people-desktop.png) | `/people` | Local preview; identity investigation IA |
| 21 | [Catalog](21-admin-catalog-desktop.png) | `/catalog` | Local preview; versioned catalog/publishing IA |
| 22 | [Learning operations](22-admin-learning-operations-desktop.png) | `/learning-operations` | Local preview; held-job/reconciliation IA |
| 23 | [Corrections](23-admin-corrections-desktop.png) | `/people/corrections` | Local preview; append-only correction IA |
| 24 | [Grants](24-admin-grants-desktop.png) | `/people/grants` | Local preview; explicit grant IA |

## Mobile viewport — 390 × 844

| # | File | Route | Evidence status |
|---:|---|---|---|
| 25 | [Public home](25-learner-public-home-mobile.png) | `/` | Learner responsive empty-catalog surface |
| 26 | [Register](26-register-mobile.png) | `/register` | Learner responsive registration surface |
| 27 | [Login](27-login-mobile.png) | `/login` | Learner responsive session entry |
| 28 | [Onboarding](28-onboarding-mobile.png) | `/onboarding` | Learner responsive onboarding boundary |
| 29 | [Offline](29-offline-mobile.png) | `/offline` | Learner responsive PWA recovery surface |
| 30 | [Locked](30-locked-mobile.png) | `/learn/free-course?state=locked` | Learner responsive locked state |
| 31 | [Admin overview](31-admin-overview-mobile.png) | `/` on admin web | Admin responsive local preview |
| 32 | [Admin catalog](32-admin-catalog-mobile.png) | `/catalog` on admin web | Admin responsive local preview |

## Browser QA notes

- Representative learner and admin routes were checked at 390 × 844 and 1440 × 900.
- No checked route had horizontal document overflow.
- Every checked route had one `main` landmark, one `h1`, and `html[lang="en"]`.
- No application-level console error was observed; only Next.js development/HMR messages were present.
- The viewport was reset after capture.

## Deliberately absent from this local pack

The real seeded Module 1 sequence—`VIDEO → REFLECTION → IMPLEMENTATION_CHALLENGE → REVIEW → IMPROVE`—is not represented by these local images. Those screenshots require an exact built release, approved staging seed execution, canonical actor provenance, learner enrollment, and browser verification against the deployed staging URLs. Modules 2–4 remain topology-only. Future simulator, call-review, native, billing, SSO/SCIM, and broad enterprise screens are outside v0.1.
