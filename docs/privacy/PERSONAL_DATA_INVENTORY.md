# Personal data inventory: Google profile

| Field | Storage | Source | Purpose | Where shown | Retention | Erasure path |
| --- | --- | --- | --- | --- | --- | --- |
| `given_name` | `person_google_profiles.given_name` in Postgres | Verified Google ID token | Display profile personalization | `GET` and `PUT /v1/me/sales-xray-profile` response | Current value; refreshed at each Google sign-in | `erase_sales_xray_profile` deletes the Google profile row; person deletion also cascades |
| `family_name` | `person_google_profiles.family_name` in Postgres | Verified Google ID token | Display profile personalization | `GET` and `PUT /v1/me/sales-xray-profile` response | Current value; refreshed at each Google sign-in | `erase_sales_xray_profile` deletes the Google profile row; person deletion also cascades |
| `locale` | `person_google_profiles.locale` in Postgres | Verified Google ID token | Display profile localization | `GET` and `PUT /v1/me/sales-xray-profile` response | Current value; refreshed at each Google sign-in | `erase_sales_xray_profile` deletes the Google profile row; person deletion also cascades |
| `hd` (`hosted_domain`) | `person_google_profiles.hosted_domain` in Postgres; returned as `company_domain` | Verified Google ID token | Display the Google hosted domain | `GET` and `PUT /v1/me/sales-xray-profile` response | Current value; refreshed at each Google sign-in; an absent claim clears it | `erase_sales_xray_profile` deletes the Google profile row; person deletion also cascades |
| Photo copy and hashes | `photo_jpeg`, `photo_sha256`, `photo_source_sha256`, and `photo_fetched_at` in `person_google_profiles` | Sanitized 256×256 JPEG copied from a validated Google `picture` URL; URL is not retained | Keep a bounded first-party profile image | `GET` and `PUT /v1/me/sales-xray-profile` return a first-party `photo_url`; the authenticated photo route serves the JPEG | Current copy while the profile row exists; changed URLs refresh after sign-in, failures keep the previous copy, and an absent claim clears it | `erase_sales_xray_profile` deletes the Google profile row; person deletion also cascades |

The Google `picture` URL is never stored, displayed, hot-linked, or logged. No
new Google scopes are requested. The profile row is retained in Postgres backup
and restore inventories with the migration-bound parity contract.

## Organisation invitations

| Field | Storage | Source | Purpose | Where shown | Retention | Erasure path |
| --- | --- | --- | --- | --- | --- | --- |
| Normalized invite email | `organisation_invites.email_normalized` in Postgres | Operator-provided email for a direct member add or invitation | Match an invitation to the verified account and enforce one pending invite per organisation and email | Operator CLI shows only a masked address; API routes are outside this slice | Retained with the invitation row; no expiry or purge rule is introduced by this slice | Invitation lifecycle changes its status; this migration does not delete invite history. A retention and erasure rule must be defined before an invitation API is enabled |

Invite rows are included in the migration-bound Postgres backup and restore
parity contract. Full invite addresses must not be written to CLI output or
audit payloads.

## Billing ledger (ADR 0052, migration 0062)

| Field | Storage | Source | Purpose | Where shown | Retention | Erasure path |
| --- | --- | --- | --- | --- | --- | --- |
| Account holder id | `billing_accounts.person_id` in Postgres (NULL for an Organisation account) | The signed-in person's id when their Personal account is first admitted | Bind capacity lots and closings to one person in one tenant | The person's own usage statement and Admin billing reads for `platform_billing_manage` staff | For the life of the ledger; the row is never updated or deleted | None by deletion: the account row is financial history. Identity deletion marks the person `deleted` and ends memberships; the id stays as an opaque reference |
| Actor id | `billing_ledger_entries.actor_person_id` (with `actor_type` person, system or provider) | The person who wrote the row: the account holder for a purchase or refund request, a staff member for a grant or correction | Attribute every capacity change to a person, a system job or a provider event | Admin billing reads; never in the customer-facing statement beyond "granted by the AC team" | With the ledger row, for as long as the audit history it references | Supersession only: a wrong row is closed or corrected by a new row. The tables refuse `UPDATE` and `DELETE` at the database |
| Reason | `billing_ledger_entries.reason` (free text, at most 500 characters) | Typed by the staff member or set by the server (renewal, expiry, refund) | Explain a grant, correction, hold or refund to the customer and to reviewers | Admin billing reads; customer statement lines for grants and refunds | With the ledger row | Supersession only; staff must not type third-party personal data, contact details or payment identifiers into a reason |
| Audit event id | `billing_ledger_entries.audit_event_id` | The audit event written in the same transaction as the row | Tie each capacity change to the append-only audit chain | Admin billing reads | With the audit history; no purge rule is introduced by this slice | Follows the audit chain, which is never rewritten |

Both tables are included in the migration-bound Postgres backup and restore
parity contract (`ac-postgres-parity-v35`). The ledger stores seconds of
capacity, actor ids, reasons and references; it holds no name, email, card or
bank detail, and `source_ref` carries only our own order, period or audit
identifiers. Use is not stored here; it stays in the Sales Xray acquisition
reservation and settlement tables.
