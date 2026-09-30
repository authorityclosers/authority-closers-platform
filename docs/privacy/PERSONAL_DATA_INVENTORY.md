# Personal data inventory: Google profile

| Field | Storage | Source | Purpose | Where shown | Retention | Erasure path |
| --- | --- | --- | --- | --- | --- | --- |
| `given_name` | `person_google_profiles.given_name` in Postgres | Verified Google ID token | Display profile personalization | `GET` and `PUT /v1/me/sales-xray-profile` response | Current value; refreshed at each Google sign-in | `erase_sales_xray_profile` deletes the Google profile row; person deletion also cascades |
| `family_name` | `person_google_profiles.family_name` in Postgres | Verified Google ID token | Display profile personalization | `GET` and `PUT /v1/me/sales-xray-profile` response | Current value; refreshed at each Google sign-in | `erase_sales_xray_profile` deletes the Google profile row; person deletion also cascades |
| `locale` | `person_google_profiles.locale` in Postgres | Verified Google ID token | Display profile localization | `GET` and `PUT /v1/me/sales-xray-profile` response | Current value; refreshed at each Google sign-in | `erase_sales_xray_profile` deletes the Google profile row; person deletion also cascades |
| `hd` (`hosted_domain`) | `person_google_profiles.hosted_domain` in Postgres; returned as `company_domain` | Verified Google ID token | Display the Google hosted domain | `GET` and `PUT /v1/me/sales-xray-profile` response | Current value; refreshed at each Google sign-in; an absent claim clears it | `erase_sales_xray_profile` deletes the Google profile row; person deletion also cascades |
| Photo copy and hashes | `photo_jpeg`, `photo_sha256`, `photo_source_sha256`, and `photo_fetched_at` in `person_google_profiles` | JPEG copied from a validated Google `picture` URL; only its SHA-256 is retained | Keep a bounded first-party profile image | Not shown by this claims-only change; the follow-on photo route owns display | While the profile row exists; photo replacement and fetch rules are part 2 | `erase_sales_xray_profile` deletes the Google profile row; person deletion also cascades |

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
