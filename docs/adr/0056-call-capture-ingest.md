# ADR 0056: Call capture ingest

- Status: Proposed; CTO review required
- Date: 2026-10-08
- Amends: [ADR 0055 §7](0055-companion-device-credentials.md#7-capture-provenance-without-inventing-historical-evidence) and [ADR 0042](0042-sales-xray-speaker-map.md)

## Context

[AUT-1606](/AUT/issues/AUT-1606), foundation card F1 of
[AUT-1604](/AUT/issues/AUT-1604), records the binding
[CTO decision brief](/AUT/issues/AUT-1604#document-brief) for call capture ingest.
The brief wins wherever it differs from r16. The fifteen decision paragraphs
below retain the brief's wording; their numbers match the source decisions.

This documentation card records the common ingest boundary for every capture
source. Implementation belongs to later cards; provider choice, prices and
production activation are outside this card.

## Decision

### 1. One door

**One door.** Every capture source ends in today's source PUT (`/v1/.../acquisition/submissions/{id}/source`, cookie or ADR 0055 native). No second file door. Provider recordings enter through the same internal ingest service with the same size, policy and consent checks.

### 2. ADR amendments

**ADR 0056 "Call capture ingest"** (fallback: next free number on `main`) amends ADR 0055 §7 and ADR 0042. `capture_source` gains `provider_bridge`, `provider_softphone`, `provider_inbound`, `api_upload` (MCP uploads use it; the client goes in provenance) and `hardware_device`; device platform gains `hardware`. The enum lives in one Python constant; the DB check is widened only by F2's migration.

### 3. Capture session

**Capture session** = the call intent, made only when a call starts from our product. States `started → ended → recording_found → uploaded → saved | abandoned`. Each transition appends a `capture_session_events` row in the same transaction as the state update (supersede, never rewrite). A session binds to exactly one submission, once, at source PUT; a second bind is 409; another workspace's session is 404. A session with no recording after 24 h becomes `abandoned`.

### 4. Provenance

**Provenance** = one append-only row per submission, written at source PUT; a correction is a new row with `supersedes_id`. Holds: capture_source, device id, app version, phone model, original format/rate/channels/duration, `original_sha256` and `uploaded_sha256`, notice evidence (provider prompt id or the rep's "notice given" tap), consent versions, provider call id, AI providers and regions, match method. **Never** a phone number, contact name or raw file name.

### 5. Phone numbers

**Phone numbers (owner D2).** Only in one private contacts store (merged with r13's `conversation_prospect_contacts_private`; basis `person` or `call_metadata`): HMAC-SHA256 of the E.164 number with a per-environment key from Infisical (for matching), the number encrypted with AES-GCM under a key id (for the Save tap), and the last 4 digits for display. Numbers never reach AI requests, transcripts, reports, exports, logs, audit payloads or a prospect's Phone field, except through a person's "Save number to prospect" tap. A guard test proves AI request builders and report serialisers cannot read the store.

### 6. Matching

**Matching.** Rep started the call from a prospect → linked (a person's act, AUT-1109). Same number seen before → one-tap suggestion, never an auto-merge. Neither → r13 Detected prospect from call content.

### 7. Provider inbox

**Provider inbox.** One exact public path per provider and connection (`/v1/telephony/{provider}/{connection_public_id}/events`, ingress packet like `infra/application/BILLING_INGRESS.md`). Verify the signature where the provider signs (Plivo V3); store the raw event append-only and answer 200 at once. The webhook is a hint only: a job fetches the call from the provider API with the connection's credentials, downloads the recording, checks it, and saves the submission idempotently on `(workspace, connection, provider_call_id)`. No call exists without the verified fetch. Unsigned providers (Exotel) are rate-limited hints.

### 8. Secrets

**Secrets.** `telephony_connections` holds secret references (Infisical names) only, per environment. No key value in DB, git, logs, cards or chat. The owner buys and does KYC; keys reach Infisical by the OWNER-APPROVED SECRETS path.

### 9. Money and access

**Money and access.** Telephony state never grants access, never spends credits and never starts analysis. Analysis stays a person's tap (D10 auto-analyse is later and needs its own consent and owner approval).

### 10. Auto-upload

**Auto-upload (owner D3).** A separate versioned auto-upload consent per rep and workspace; source PUT carries `X-Upload-Trigger: auto|manual`, and the server refuses `auto` without a current consent. Switching it off in Settings stops the next upload, not "after sync".

### 11. Activation gates

**Activation gates.** Everything ships behind off-by-default flags (`AC_TELEPHONY_ENABLED`, auto-upload). Dev and staging use fictional data only. Production activation of provider calling, auto-upload or live drafts needs AC-GOV-AUD-001, counsel-reviewed notice and consent wording (owner default 5), and AUT-1596 resolved so company calls are not deleted after 7 days.

### 12. Formats

**Formats.** Keep 32 MiB / 60 min. The app re-encodes files over 30 MB to Opus mono and provenance keeps both hashes. The server accepts AMR, AAC, 3GA, WebM and Opus by content sniffing (not extension), keeps the original as the source of record and derives the decode input.

### 13. Two channels

**Two channels.** Provider stereo uses the provider's declared leg order as `channel_mapped_roles` with source `provider_declared` (ADR 0042 amendment). Mono is unchanged.

### 14. Live relay

**Live relay.** Off-box only (Cloudflare Worker + Sarvam). The VPS receives only draft text. Drafts are never canonical and never feed reports or scoring; the batch transcript stays canonical. Not built now (L5).

### 15. API / MCP / hardware

**API / MCP / hardware.** Workspace API keys are service principals under their own ADR (L7); MCP is a stateless read-only adapter over the same handlers (L8). Hardware reuses ADR 0055 pairing with a device code; chunked upload rides L4.

## Brief decision traceability

| Brief decision | ADR section                                    |
| -------------- | ---------------------------------------------- |
| 1              | [One door](#1-one-door)                        |
| 2              | [ADR amendments](#2-adr-amendments)            |
| 3              | [Capture session](#3-capture-session)          |
| 4              | [Provenance](#4-provenance)                    |
| 5              | [Phone numbers](#5-phone-numbers)              |
| 6              | [Matching](#6-matching)                        |
| 7              | [Provider inbox](#7-provider-inbox)            |
| 8              | [Secrets](#8-secrets)                          |
| 9              | [Money and access](#9-money-and-access)        |
| 10             | [Auto-upload](#10-auto-upload)                 |
| 11             | [Activation gates](#11-activation-gates)       |
| 12             | [Formats](#12-formats)                         |
| 13             | [Two channels](#13-two-channels)               |
| 14             | [Live relay](#14-live-relay)                   |
| 15             | [API / MCP / hardware](#15-api--mcp--hardware) |

## Alternatives

The binding brief excludes a second file door, automatic number merges,
webhook-only call creation and telephony-triggered access, credit spend or
analysis. It defers softphone, live relay, inbound calls, public API keys, MCP,
iOS, store releases, auto-analyse and any production activation.

## Consequences

Later cards implement the capture sessions, provenance, private contacts,
provider inbox and format handling recorded above. F2 alone widens the database
check for the capture-source enum. Every source retains the same upload size,
policy and consent checks. Provider choice and trials remain outside this ADR.

## Reversal cost

Recorded session events, provider events and provenance remain append-only;
corrections supersede prior rows. Changing capture sources, private-number
handling, channel declarations or consent requires revisiting the binding
brief and its affected contracts. Off-by-default flags and the activation
gates in decision 11 remain the boundary for activation.

## Evidence

- [Binding CTO brief](/AUT/issues/AUT-1604#document-brief), revision
  `ca9541dd-d601-4dfd-9d78-7ee3c9bff405` (revision 1);
  its source is owner-approved r16 at pin `06360db9` and owner decisions D1–D5.
- [r16 reference copy](/AUT/issues/AUT-1604#document-r16), revision
  `b5660be6-c5b1-49ea-81ab-862dba84d768` (revision 1).
  The brief takes precedence over this reference.
- Repository base at task start: `df769bac0ddb5d70880a0db382834503fb4c149e`.
- [ADR 0055](0055-companion-device-credentials.md) supplies the companion
  credentials and source PUT boundary; [ADR 0042](0042-sales-xray-speaker-map.md)
  supplies the channel-role contract being amended.

## Owner

CTO owns the binding decisions and ADR review. Admin Lead records them in F1;
subsequent assigned cards own implementation.

## Supersedes

This ADR amends ADR 0055 §7 for the capture-source additions and `hardware`
device platform in decision 2, and ADR 0042 for provider-declared channel roles
in decision 13. The amendment notes in those ADRs point here. No whole ADR is
superseded.

## Trigger to revisit

Revisit the brief through the CTO before changing any of its fifteen decisions.
Later calling, auto-upload and live-draft activation still require decision 11's
gates; the deferred capabilities retain their separately assigned ADRs/cards.
