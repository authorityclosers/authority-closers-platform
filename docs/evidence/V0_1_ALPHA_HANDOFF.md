# Authority Closers v0.1 alpha handoff

- Evidence date: 2026-09-01 (Asia/Kolkata)
- Repository: `authorityclosers/authority-closers-platform` (private)
- Branch: `codex/g1-free-course-foundation`
- Deployed application release:
  `27fafaea1e5de41ae6a830746b1d832b42c7d444`
- Evidence commit: `5f0cfc8`

## Outcome

The bounded v0.1 staging alpha is live and runtime-proven for the browser-first
learner foundation, separate protected admin foundation, modular API,
PostgreSQL state, password authentication, recovery, Google authentication,
transactional email, published free-course catalog, learner home, complete
Module 1 VIDEO → REFLECTION → IMPLEMENTATION_CHALLENGE → REVIEW → IMPROVE
route family, and server-restored reflection draft.

This is not a production launch declaration. Production learner, admin, and
API hostnames do not resolve and the required production bootstrap,
backup/restore, Access, secrets, rollback, observability, legal, and
exact-release gates have not been proved.

## Working staging URLs

| Surface      | URL                                                                           | Runtime result                                                 |
| ------------ | ----------------------------------------------------------------------------- | -------------------------------------------------------------- |
| Learner      | `https://staging.authorityclosers.com`                                        | HTTP 200; exact release `27fafae`                              |
| Login        | `https://staging.authorityclosers.com/login`                                  | Password and Google entry points live                          |
| Free course  | `https://staging.authorityclosers.com/programs/authority-closers-free-course` | Published course and module topology live                      |
| Learner path | `https://staging.authorityclosers.com/learn/authority-closers-free-course`    | Enrolled learner sees all five Module 1 activities             |
| Admin        | `https://admin-staging.authorityclosers.com`                                  | Cloudflare Access plus verified AC owner session               |
| API          | `https://api-staging.authorityclosers.com`                                    | live/ready/program routes pass; public docs/OpenAPI remain 404 |

The legacy `authorityclosers.com` and `www` WordPress boundary is unchanged.

## Test identities and access

- Dedicated learner: `admin+alpha-learner@authorityclosers.com`
- Infrastructure and Google admin: `admin@authorityclosers.com`

No password is stored in Git or this handoff. The dedicated learner password
is established with the newest `Reset your password — Authority Closers`
message delivered to the Authority Closers admin mailbox.

## Runtime proof

- Exact release archive path-safety and commit binding: passed.
- Exact running-image/release match: passed.
- PostgreSQL migration and privilege chain: passed.
- API, worker, learner, admin, and PostgreSQL health: passed with zero restart
  evidence at deployment verification.
- Learner root, health, Apple/PWA icons, service worker, API live/ready/catalog,
  admin Access boundary, Google callback binding, and legacy WordPress smoke:
  passed.
- Worker runtime: `AC_EMAIL_PROVIDER=resend`,
  `AC_EXTERNAL_SIDE_EFFECTS_HOLD=false`, AC sender configured.
- Fresh recovery request: Resend status `delivered` to the dedicated learner.
- Password login: dedicated learner landed on `/home`; home showed
  `Authority Closers Free Course`, `Continue course`, and authoritative
  `0 / 5` projection.
- Google login: exact `admin@authorityclosers.com` account selected at Google;
  callback landed on `/home` with `owner` context. The former consent/error
  response did not recur.
- Reflection: server-restored draft rendered with in-progress state and
  character count.

## Verification gates

| Gate                                                      | Result                               |
| --------------------------------------------------------- | ------------------------------------ |
| Learner tests                                             | PASS — 54                            |
| Learner lint/typecheck/Prettier/build                     | PASS                                 |
| Pull-request control-plane workflow                       | PASS — run `33447263943`             |
| Pull-request application workflow                         | PASS — run `33447263944`             |
| Exact-release validation and packaging                    | PASS — run `33447522610`             |
| Immutable image publication and reviewed transport bundle | PASS                                 |
| Staging migrations and deployment smoke                   | PASS                                 |
| Password login and recovery delivery                      | PASS                                 |
| Google login/callback                                     | PASS                                 |
| Drive/live desktop shell comparison                       | PASS with explicit viewport mismatch |
| Current-release authenticated mobile capture              | OPEN                                 |
| Production promotion                                      | NO-GO                                |

## Evidence

- [Exact staging journey index](screenshots/v0.1-staging-exact-27fafae/README.md)
- [Complete journey contact sheet](screenshots/v0.1-staging-exact-27fafae/journey-contact-sheet.png)
- [Drive reference/live home comparison](screenshots/v0.1-staging-exact-27fafae/comparison-shell-home.png)
- [Design QA](../../design-qa.md)
- [Drive UI implementation matrix](../traceability/DRIVE_UI_IMPLEMENTATION_MATRIX.md)

The pack contains learner home, module path, all five activities, recovery,
Google owner home, public catalog, login, registration, program detail,
protected admin, and the real-mail proof. It records no password, token,
OAuth code, cookie, or secret.

## Reproduction commands

```powershell
pnpm install --frozen-lockfile
pnpm run validate
pwsh -NoProfile -NonInteractive -File scripts/Deploy-Staging.ps1 `
  -ReleaseSha 27fafaea1e5de41ae6a830746b1d832b42c7d444
```

Deployment must consume the reviewed immutable release bundle and environment
contracts; production database or VPS state must never be manually edited into
authority.

## Open boundaries

1. A current-release authenticated 390 × 844 mobile journey capture is still
   missing because the selected Chrome connection did not apply a temporary
   viewport override. Responsive unit/CSS checks are not substituted for
   cross-device visual evidence.
2. Media playback remains provider/policy-gated. No fake video completion is
   asserted.
3. Implementation evidence submission remains independent-reviewer-gated.
4. Fresh self-enrollment remains blocked by controlled gap
   `PROV-G1-AGE-ELIGIBILITY-POLICY`; learner consent is not inferred to satisfy
   eligibility.
5. Edge and iOS Safari/PWA runtime evidence, a live restore drill, and the
   remaining authorized non-production performance/security evidence must be
   current for the promoted artifact before broader release claims.
6. Production requires its own secrets, database/bootstrap, backup/restore,
   DNS, Cloudflare Access, rollback, observability, legal content, and
   action-time approval evidence. Current DNS checks return NXDOMAIN for
   `app.authorityclosers.com`, `admin.authorityclosers.com`, and
   `api.authorityclosers.com`.

## Explicit non-claims

No future SaaS breadth, simulator/call-review engine, native Windows or iOS
app, billing, SSO/SCIM, broad enterprise functionality, autonomous official
scoring, real-call processing, or production deployment is claimed.
