# Learner Sales Xray acquisition journey

Base: `c36c7b23734921bf4438ca73abcc114b40090757`.

The learner `/sales-xray` route mounted the legacy account-intake studio while
the standalone app used acquisition submissions and processing-principal
approvals. On 14 September 2026, an actual Chrome visit to
`https://learner-staging.authorityclosers.com/sales-xray` in the Authority Closers
profile showed the signed-in learner and “This account has no approved
processing allowance.” No recording was uploaded during that observation.

The primary learner route now mounts the existing AcquisitionStudio inside the
Academy shell. Its embedded variant has one outer main landmark and uses the
existing scoped styles without the standalone brand/account header. The shared
workspace gate requires authenticated access in this variant; workspace,
acquisition-entry or acquisition-session 401s lead to AC sign-in. Embedded
uploads cannot create a guest session or load Turnstile as a fallback.

`/sales-xray/calls` reuses the account submission library and opens a selected
call back at `/sales-xray`. `/sales-xray/recordings` retains the legacy embedded
CallStudio for historical recordings and reports. The primary page links both.
Existing explicit claims, server-measured minute allowance, source-bound report
validation and consent-before-provider processing remain in the shared studio.
Changing pages or reopening a report does not upload or accept a plan again.

## Local verification

Node 24.19.0, pnpm 11.19.0, Windows. Actual external receipts live under
`D:/AC-authority-closers-release-audit/learner-acquisition-20260914/`.

- Focused learner suite: **9 passed in 3 files**, exit 0. Six mounted journey
  cases use the real route, workspace gate, studio, library and report with
  fixture HTTP responses; only the surrounding Academy chrome is mocked.
  Coverage includes upload and separate plan consent, mixed-script report,
  saved report restore without mutations, three 401 boundaries, explicit claim,
  single main/no duplicate header, shared displayed allowance and internal
  library navigation. Two existing shell tests and the route test also pass.
- Complete standalone Sales Xray suite: **146 passed in 17 files**, exit 0.
  Includes existing guest, source-binding and historical-report regressions.
- Learner and standalone TypeScript checks: exit 0.
- Changed learner files ESLint and full Sales Xray ESLint: exit 0.
- `git diff --check`: exit 0.

| Receipt                    | SHA-256                                                          |
| -------------------------- | ---------------------------------------------------------------- |
| learner-tests-final.xml    | 3db4c0513bbec382c8db1196523c318ef2f9364985860d2fa4762326ecbcfe43 |
| standalone-tests-final.xml | c24cff010fafb1410881a91c6bc7886b966d26a1d3889e7d9043a4fa710cb1c8 |
| learner-typecheck.log      | 5a3973f79ed9becd5f23c4feff467513814de7ea381d75a4d2e339aa8b8edca9 |
| standalone-typecheck.log   | 5a3973f79ed9becd5f23c4feff467513814de7ea381d75a4d2e339aa8b8edca9 |

Initial failed receipts remain retained separately. Two initial learner failures
were a test fixture's invalid report-envelope field; the existing strict parser
correctly rejected them. One standalone assertion still expected the legacy
route component. These were corrected before the final passing runs. An unused
lint suppression was also removed after changing the library return path.

## Integration boundary

This leaf does not change API authorization, guest scope, provider policy,
credentials, cost caps or live state. It requires the release coordinator's
parallel backend change admitting only authenticated public-Academy actors on
the exact learner hostname. Frozen acquisition routes otherwise reject that
hostname. Local mounted fixtures do not prove deployed admission or provider
execution; combined CI, staging and production browser/report checks remain
release-coordinator responsibilities. The existing real standalone test
submission was left untouched.
