# Selected file on account access, 2026-09-24

The existing account form now gives a selected local recording a stronger teal panel. The filename wraps, and the on-device, not-uploaded status is readable without changing the sign-in flow or file handling.

Implementation: `apps/sales-xray-web/app/account-auth.tsx` and `account-auth.module.css`. The existing copy and decorative icon semantics remain in place.

Verification: focused `account-auth.test.tsx` passed (9 tests). The synthetic auth fixture was rendered with a local read-only review bridge (`analysis_read_only: true`) in an isolated checkout; no account request or recording upload was made. At 1440 × 1000, the panel measured 480 × 75px. At 390 × 844, it measured 342 × 75px and the document width stayed at 390px. Both rendered with the existing theme tokens and legible local-only status. Local screenshots are retained under `.tmp/selected-file-auth-review-evidence/` and contain only the synthetic filename.
