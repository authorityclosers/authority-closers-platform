# Report and Admin release continuation — 2026-09-14

This candidate continues the deployed `c437c1758d8a66ede0221f83fe787bb13de33c40` baseline. It is not a claim of staging or production deployment.

## Resulting behavior

- Admin's Sales Xray review workspace lists retained recordings from the explicitly configured operations and public learner tenants, including guest and account-owned uploads. Search and pagination keep that scope. Deleted sources are excluded. A saved report can populate the review/invitation flow without copying IDs manually.
- Latest run status is separate from retained report availability. A report only offers review when its current source generation is ready. Costs come from canonical stage authorization, quote and reservation records; reused historical stages fall back to an explicitly labelled recording total. Unknown actual charges remain unsettled, never zero or an estimated invoice.
- Review admission recognizes the canonical non-login processing principal used by both guest and authenticated acquisition uploads. It checks source ownership, current principal/account status and revocation, then retains the existing recording permission, retention and exact report checks. Reading a retained report does not renew an execution lease. Ordinary unverified learner recordings retain their existing verified-member path.
- C4 facts bind to canonical transcript segment IDs; the server supplies their exact source quotes and times. Explicit quote mismatches still fail. Fixed diagnostic codes identify failure classes without storing arbitrary exception text.
- The Sales Xray report and loading flow use personal coaching language, truthful stage/recovery status, responsive layouts and keyboard/reduced-motion support. Print exports expose expanded report content. The offline benchmark command replays synthetic fixtures without provider calls and does not represent paid-model quality validation.

## Local evidence

Combined source through `5d171a1` was assembled from independently reviewed leaves. The scoped checks recorded outside Git in `D:/AC-authority-closers-release-audit/activation-20260914/` are:

| Check | Result | Receipt |
| --- | --- | --- |
| C4, report, overview and failure diagnostics | 88 passed | `combined-c3c82cd-report-tests.xml` |
| Sales Xray frontend suite | 133 passed | `combined-report-ui.xml` |
| Admin inventory HTTP/unit contracts | 11 passed | `combined-591c897-admin-backend.xml` |
| Admin review frontend tests | Passed | `combined-591c897-admin-ui.xml` |
| Admin optimized Next.js production build | Passed, including TypeScript | Source tree `b8f161c2369e38b98528bef910b43e14eec44a32` |
| Guest/account review and invitation security | 10 passed | `combined-guest-review-final.xml` |
| Offline benchmark with external scratch directory | 29 passed; zero skipped | `combined-benchmark-external-temp.xml` |

The Admin HTTP tests use a mocked database and compiled SQL, not a real database integration. Guest source unit tests cover retained expired leases, account-owned uploads, revoked principals/visitors, suspended account owners, foreign source links, ordinary unverified users, deleted recordings and revoked permission. Existing disposable PostgreSQL review/ownership suites remain part of the exact release CI requirements.

The earlier combined review/benchmark run had two path-environment skips; the dedicated benchmark run above used an external scratch directory and passed all 29 tests. The initial Admin review found and corrected public-tenant omission, incomplete retry cost attribution and stale report readiness. Root review additionally found and corrected rejection of signed-in acquisition uploads.

## Deployment and paid-test boundary

Exact combined CI, immutable images, canonical installation, browser review submission and actual staging/production provider-report journeys remain pending at this commit. Base CI/browser receipts do not prove this candidate. The previously deleted test call must not be restored; any new run uses a new authorized upload.

Operator continuation preserves the original funded budget identity and uncertain prior reservations. Staging's next-plan maximum is narrowed to 11 C4 requests / ₹71 within its existing ₹74 remaining reservation capacity. Production remains 64 C4 requests / ₹336 maximum plan reservation under its separate ₹900 cap. These maxima are not actual charges. No new funding, refunds or manual SQL recovery are part of this change.
