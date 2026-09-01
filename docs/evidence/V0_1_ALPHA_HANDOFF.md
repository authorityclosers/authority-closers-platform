# Authority Closers v0.1 alpha handoff

- Evidence date: 2026-09-01 (Asia/Kolkata)
- Repository: `authorityclosers/authority-closers-platform` (private)
- Branch: `codex/g1-free-course-foundation`
- Deployed application release:
  `81635d18569c06962af37c1fa64d0d5814d0f2bf`
- Evidence commit: reported in the final task handoff after this evidence-only
  update is committed.

## Outcome

The bounded v0.1 staging alpha is live and runtime-proven for the browser-first
learner foundation, separate protected admin foundation, modular API,
PostgreSQL state, password authentication, recovery, Google authentication,
transactional email, published free-course catalog, learner home, complete
Module 1 VIDEO → REFLECTION → IMPLEMENTATION_CHALLENGE → REVIEW → IMPROVE
route family, and server-restored reflection draft. Release `81635d1` also
replaces the raw missing-consent Google callback problem document with a
same-origin, responsive recovery journey grounded in the approved auth design.

This is not a production launch declaration. Production learner, admin, and
API hostnames do not resolve and the required production bootstrap,
backup/restore, Access, secrets, rollback, observability, legal, and
exact-release gates have not been proved.

## Working staging URLs

| Surface      | URL                                                                           | Runtime result                                                 |
| ------------ | ----------------------------------------------------------------------------- | -------------------------------------------------------------- |
| Learner      | `https://staging.authorityclosers.com`                                        | HTTP 200; exact release `81635d1`                              |
| Login        | `https://staging.authorityclosers.com/login`                                  | Password and Google entry points live                          |
| Free course  | `https://staging.authorityclosers.com/programs/authority-closers-free-course` | Published course and module topology live                      |
| Learner path | `https://staging.authorityclosers.com/learn/authority-closers-free-course`    | Enrolled learner sees all five Module 1 activities             |
| Admin        | `https://admin-staging.authorityclosers.com`                                  | Cloudflare Access plus verified AC owner session               |
| API          | `https://api-staging.authorityclosers.com`                                    | live/ready/program routes pass; public docs/OpenAPI remain 404 |

The legacy `authorityclosers.com` and `www` WordPress boundary is unchanged.

## Test identities and access

- Existing Google/admin learner identity: `admin@authorityclosers.com`
- Dedicated seeded learner: `admin+alpha-learner@authorityclosers.com`

No password, reset token, OAuth code, or cookie is stored in Git or this
handoff. A fresh post-cutover `Reset your password — Authority Closers`
message was delivered to `admin@authorityclosers.com`; that one-time inbox
flow is the immediate secure way to establish a private test password.

## Runtime proof

- Exact release archive path-safety and commit binding: passed.
- Exact running-image/release match: passed.
- PostgreSQL migration and privilege chain: passed.
- API, worker, learner, admin, and PostgreSQL health: passed with zero restart
  evidence at deployment verification.
- Learner root, health, Apple/PWA icons, service worker, API live/ready/catalog,
  admin Access boundary, Google callback binding, and legacy WordPress smoke:
  passed.
- Fresh post-cutover recovery request: accepted and delivered from
  `Authority Closers <learn@authorityclosers.com>` to
  `admin@authorityclosers.com` at `2026-09-01T02:23:32Z`.
- Password login: dedicated learner landed on `/home`; home showed
  `Authority Closers Free Course`, `Continue course`, and authoritative
  `0 / 5` projection.
- Google boundary: OAuth start/callback binding passed deployment smoke; the
  exact missing-consent callback renders the branded `Review and continue`
  recovery screen on desktop and mobile instead of raw JSON. A final
  user-specific Google account-selection/re-consent completion was not replayed
  after `81635d1` because account selection requires action-time user
  confirmation.
- Reflection: server-restored draft rendered with in-progress state and
  character count.

## Verification gates

| Gate                                                      | Result                               |
| --------------------------------------------------------- | ------------------------------------ |
| Learner tests                                             | PASS — 55                            |
| Admin tests                                               | PASS — 71                            |
| Python suite                                              | PASS — 836; 97 skipped               |
| Learner lint/typecheck/Prettier/build                     | PASS                                 |
| Pull-request control-plane workflow                       | PASS — run `33460969014`             |
| Pull-request application workflow                         | PASS — run `33460969038`             |
| Exact-release validation and packaging                    | PASS — run `33461232992`             |
| Immutable image publication and reviewed transport bundle | PASS                                 |
| Staging migrations and deployment smoke                   | PASS                                 |
| Password login and recovery delivery                      | PASS                                 |
| Google start and missing-consent callback recovery        | PASS                                 |
| Final real-account Google re-consent completion           | OPEN — action-time user confirmation |
| Current-release public auth mobile captures               | PASS — 6 states                      |
| Drive/live desktop shell comparison                       | PASS with explicit viewport mismatch |
| Current-release authenticated mobile capture              | OPEN                                 |
| Production promotion                                      | NO-GO                                |

## Evidence

- [Exact staging journey index](screenshots/v0.1-staging-exact-27fafae/README.md)
- [Complete journey contact sheet](screenshots/v0.1-staging-exact-27fafae/journey-contact-sheet.png)
- [Drive reference/live home comparison](screenshots/v0.1-staging-exact-27fafae/comparison-shell-home.png)
- [Exact-release auth and recovery pack](screenshots/v0.1-staging-exact-81635d1/README.md)
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
  -ReleaseSha 81635d18569c06962af37c1fa64d0d5814d0f2bf
```

Deployment must consume the reviewed immutable release bundle and environment
contracts; production database or VPS state must never be manually edited into
authority.

## Open boundaries

1. Public auth/recovery is captured at a configured 390 × 844 mobile viewport,
   but a current-release authenticated 390 × 844 learner home/module journey
   is still missing because the selected browser no longer has a learner
   session. Public responsive evidence is not substituted for authenticated
   journey evidence.
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
7. Final real-account Google re-consent remains an action-time user step. The
   deployed recovery logic and provider boundary are proven without silently
   selecting or transmitting a signed-in Google identity.

## Explicit non-claims

No future SaaS breadth, simulator/call-review engine, native Windows or iOS
app, billing, SSO/SCIM, broad enterprise functionality, autonomous official
scoring, real-call processing, or production deployment is claimed.
