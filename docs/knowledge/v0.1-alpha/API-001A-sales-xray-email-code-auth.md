---
id: API-001A
type: api-contract-amendment
title: Sales Xray Email Code Authentication Addendum
status: implementation-candidate
version: v0.1-alpha
updated: 2026-09-23
tags:
  - ac/api/identity
  - ac/product/sales-xray
---

# Sales Xray email code authentication addendum

This narrow addendum records the owner direction received on 2026-09-23 and supplements [[API-001-identity-onboarding]] and [[SF-AUTH-001-authentication]] for the Sales Xray pre-upload gate. It does not reinterpret password reset, email verification, reviewer invitations, existing report authorization, trial allowances, or payment state.

## Owner decision

- A person must authenticate with the shared Authority Closers identity before any Sales Xray file is uploaded or paid analysis begins. A visitor may choose a local file first; it remains in browser memory while authentication and required profile completion run.
- Email code verification and Google sign-in create or resolve the canonical AC identity and issue its account session. A new account is created only after mailbox code verification and exact current Terms/Privacy consent. An unverified pre-registration identity also requires an exact current consent on its mailbox challenge before it can be reclaimed. It remains onboarding-pending until the separate required name/email/mobile profile flow completes.
- The email-code flow is JSON on the same surface and does not redirect or reload the page. The standalone Sales Xray return path is `/`; an embedded learner surface may use `/sales-xray` only when that surface is selected and configured. Google sign-in must run in a popup so the browser-held file remains mounted.
- Existing accounts resolve to their existing canonical person. New auth does not change existing report access rules, the 60-minute allowance, same-account trial state, or payment state. Email code challenges are separate from existing verification, password-reset, and reviewer challenge purposes.

## HTTP contract

`GET /v1/auth/email-code/config?surface=sales_xray` returns only public capability data:

```json
{
  "enabled": true,
  "consent_version": "<current configured version>",
  "google_enabled": true,
  "expires_in_seconds": 600,
  "resend_after_seconds": 60
}
```

`surface=learner` is available for embedded use. The server reports the current consent version from its configured canonical learner consent; it is not the Sales Xray upload-policy digest. The existing consent document links remain `/terms` and `/privacy`.

`POST /v1/auth/email-code/request` accepts JSON fields `email`, optional `consent` (must be JSON `true` for signup or an unverified pre-registration account), optional `consent_version`, `surface` (`sales_xray` or `learner`), and `return_path`. Signup sends the exact current `consent_version`; verified existing-account sign-in does not rewrite consent. The route always returns HTTP 202 with `{"accepted":true,"expires_in_seconds":600,"resend_after_seconds":60}` and `Cache-Control: no-store`, whether an email was queued or not.

`POST /v1/auth/email-code/verify` accepts JSON fields `email`, `code`, `surface`, and `return_path`. It returns `authenticated`, `person_id`, `email`, `display_name`, `account_created`, `profile_complete`, and the validated `return_path`, and sets the host-only AC session cookie. It does not navigate the browser. `profile_complete` comes from the canonical Sales Xray profile service in the same transaction. Existing WhatsApp profile data does not satisfy that check. A captured phone number is not represented as SMS-verified.

Return paths are exact same-origin allowlist values: `/` for standalone Sales Xray; `/` or `/sales-xray` for the configured learner surface. External URLs, fragments, and other paths are rejected.

## Security and persistence

The six-digit code is generated with the system cryptographic random source, stored as an HMAC lookup digest and separately encrypted for the durable email worker, expires after ten minutes, permits at most five failed attempts per one-hour send window, and can be resent after sixty seconds. Resend does not reset failed attempts. No more than five messages are queued per one-hour per-email send window. The current challenge is consumed in the same database transaction as canonical person provisioning and session issue. New accounts and unverified pre-registration identities require the current exact consent version. If an unverified pre-registration carries a password credential, the mailbox-proven transition consumes outstanding email challenges, revokes existing sessions, removes the unverified password credential, and appends a system audit event before issuing an account session. Active support/admin/owner identities cannot use learner email-code authentication. Suspended/deleted people cannot authenticate. The existing durable email outbox and configured email provider deliver the code; no SMS path is enabled by this contract.

The API remains subject to the Sales Xray edge/body gate: route-level authentication after request buffering alone does not satisfy the pre-upload requirement.

- implements: [identity HTTP](../../../packages/python/ac_platform/http/auth.py), [email code identity service](../../../packages/python/ac_platform/identity/email_login.py), [email outbox worker](../../../packages/python/ac_platform/worker/__init__.py), and [Resend renderer](../../../packages/python/ac_platform/providers/resend_email.py).
- validated-by: focused identity, auth-route, outbox-worker, provider-renderer and PostgreSQL migration/journey tests.
