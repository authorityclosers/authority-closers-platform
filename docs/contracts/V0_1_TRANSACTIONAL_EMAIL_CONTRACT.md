# v0.1 transactional email contract

Status: implemented renderer and fake-provider evidence; external delivery is
not yet activated or claimed.

This contract is bounded by `WF-AUTH-01`, the approved communication classes,
and the durable outbox. It does not create a general marketing or notification
system.

## Approved message family

| Stable message ID | Template | Trigger | Primary action | Expiry / safety |
| --- | --- | --- | --- | --- |
| `EMAIL-AUTH-VERIFY-V1` | `identity-email-verification` v1 | eligible password registration or existence-neutral resend | Verify my email | one-time challenge; exact UTC expiry shown |
| `EMAIL-AUTH-RESET-V1` | `identity-password-reset` v1 | eligible existence-neutral recovery request | Choose a new password | one-time challenge; exact UTC expiry shown; current password remains unchanged until consume |
| `EMAIL-ENROLL-WELCOME-V1` | `enrollment-welcome` v1 | canonical active enrollment and entitlement for an active verified person | Continue learning | no fabricated enrollment or client-only progress |

The auth templates use the `verification_security` communication class. The
welcome template uses `enrollment_welcome_next_action`. Template names and
versions are allowlisted and arbitrary subject/HTML input is rejected.

## Rendering contract

- Branded Authority Closers header, responsive table shell, hidden preheader,
  semantic heading, high-contrast CTA, visible security note, and plaintext
  fallback.
- Action links are absolute HTTP(S) links created only by the durable worker
  from canonical state after commit. One-time credentials remain in URL
  fragments so they are not sent in HTTP request targets or edge access logs.
- User-provided names and links are escaped. Newlines, invalid origins,
  timezone-free expiries, unknown templates, and unapproved versions fail
  closed.
- Transactional messages do not include a misleading unsubscribe action and
  do not opt the recipient into marketing.
- The provider idempotency key is the durable job dedupe key; uncertain
  delivery outcomes are quarantined for operations reconciliation rather than
  blindly retried.

## Explicit exclusions

- No magic-link or email-code login is implied by the presence of Google and
  password sign-in.
- No email is sent for every successful login. A future sign-in-alert policy
  requires a reviewed threat model, device/session semantics, rate controls,
  and a new allowlisted event/template.
- No marketing, calendar, reminder, discussion, broad notification, or
  certificate campaign is activated in v0.1.

## Runtime activation gate

The default and current staging posture is `AC_EMAIL_PROVIDER=fake` with
external side effects held. External delivery may be claimed only after all of
the following are evidenced:

1. reviewed sender domain and sender address;
2. API credential injected by secret reference, never committed or logged;
3. exact release deployed with `AC_EMAIL_PROVIDER=resend` and the operations
   hold deliberately released under the runbook;
4. verification, reset, deduplication, retry/quarantine, and receipt evidence
   observed in staging using the Authority Closers identity;
5. all secrets redacted from logs, screenshots, and handoff artifacts.

Static visual previews are generated with:

```powershell
uv run python scripts/render_email_previews.py
```

See [`../evidence/email-previews/v0.1-auth-family/README.md`](../evidence/email-previews/v0.1-auth-family/README.md).
