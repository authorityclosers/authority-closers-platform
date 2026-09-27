# Sales Xray contact profile v1

The Sales Xray profile is additional self-service contact data attached to the
canonical AC `Person`. Email remains the verified email on that Person. Name
updates write `Person.display_name`; direct phone data is held in the separate
`sales_xray_profiles` row. The legacy `Person.whatsapp_number` field is not
read or changed by this contract.

`GET /v1/me/sales-xray-profile` reads the current account's profile. `PUT` uses
the complete request shape below and an optimistic revision:

```json
{
  "full_name": "Ada Example",
  "phone_number_e164": "+14155550100",
  "expected_revision": 0
}
```

`phone_number_e164` must be explicitly provided; it can be `null` while the
profile is being completed. A non-null value must use strict E.164 form with an
explicit country code. The API does not infer a country. A successful response
contains only the caller's `name`, verified `email`, `phone_number_e164`,
`phone_verified`, `profile_complete`, and `revision`. A stale revision returns
409. Name and phone values are not copied into audit payloads.

Profile completeness requires a verified, active AC account, a name, and a
valid non-empty phone number. Phone verification is reported separately and is
not implied by entry; the current profile update does not claim SMS ownership.
Unverified phone collisions do not block saving or identify another account.
They set an internal admin-review flag. The verified-phone uniqueness rule
applies only to rows with SMS proof.

`GET /v1/me/sales-xray-profile/write-eligibility` is a read-only, bodyless
preflight for the reverse proxy. It accepts only the configured application,
API, admin, and coach hosts, has no query-selected identity or tenant, and
requires the configured public learner workspace. It returns an empty 204 only
for an active account with verified email and a complete profile; unauthenticated
and incomplete accounts fail before protected request bodies are forwarded.
Profile reads and updates are limited to the learner and Sales Xray application
hosts, and updates retain same-surface Origin validation.

The account/profile requirement applies to new recording registration, source
uploads, plan quote and acceptance, and analysis/run dispatch on the legacy and
acquisition APIs. It does not change owner-checked reads, explicit guest claim,
or privacy deletion. New guest uploads and processing are denied. An existing
guest-owned call must be explicitly claimed by the same AC account before a
plan can be quoted or accepted. Upload transports re-resolve authorization
after streaming and require the same person, session, and tenant tuple.

On completed canonical account deletion, the separately stored Xray phone
profile is erased after the existing privacy hook reports completion. Historical
profile audit events retain only action, revision, changed-field names, and the
internal collision-review state.
