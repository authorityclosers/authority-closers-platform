# Sales Xray code sign-in fallback — 2026-09-24

## Cause and change

- The mounted local review returned HTTP 404 for `GET /v1/auth/email-code/config?surface=sales_xray`. Its review configuration omits canonical auth rewrites. This result does not establish the status of the hosted auth service.
- The first-load page previously described this as a general sign-in outage while still offering a separate existing-password form. It now names the unavailable **email-code option**, hides its unusable form, and offers the password action and a code-configuration recheck in the same status notice.
- Password sign-in remains independent of email-code configuration and still requires a canonical session read before completing. A password endpoint failure now uses a neutral error that does not presume bad credentials.

## Verification

- Focused Vitest: `account-auth.test.tsx` and `login/page.test.tsx`, 14 tests passed. Cases include failed and disabled code configuration, recovery after recheck, successful password authentication with a canonical session, and unavailable password endpoint without redirect.
- Web typecheck, scoped ESLint, and `git diff --check` passed.
- Live local browser at `/login`: with a 1024×768 viewport, both the unavailable-code state and password form measured a 1024×768 document with no scroll. The notice showed an enabled password action; the password form exposed its email and password fields. No credentials were entered.

## Limit

This check did not submit a real account sign-in or test email delivery. The local review endpoint is intentionally not a live auth integration.
