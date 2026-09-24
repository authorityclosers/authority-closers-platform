# Selected file on account access, 2026-09-24

The existing account form now gives a selected local recording a stronger teal panel. The filename wraps, and the on-device, not-uploaded status is readable without changing the sign-in flow or file handling.

Implementation: `apps/sales-xray-web/app/account-auth.tsx` and `account-auth.module.css`. The existing copy and decorative icon semantics remain in place.

Verification: `pnpm --filter @ac/sales-xray-web test -- app/account-auth.test.tsx` passed (9 tests). The synthetic auth browser fixture requires the separate read-only review bridge; a plain Next development server could not display that fixture, so this checkpoint makes no browser-visual claim.
