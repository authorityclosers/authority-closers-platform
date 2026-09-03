# Onboarding/profile taxonomy contract v1

Status: bounded contract proposal; no API, database, scoring, personalization,
consent, provider, or WhatsApp activation in this change.

Base: green repository commit `2a499cf` (`codex/g1-free-course-foundation`).
This contract is intentionally additive and is not a claim that the current
runtime accepts these fields.

## Decision summary

The profile extension is a small set of optional, user-declared attributes:

- `country_code` — ISO 3166-1 alpha-2. The current configuration is `IN`
  (India), based on the assigned-work-item cue that Indian education sources
  are relevant. That country choice is an explicit inference and must be
  confirmed before activation.
- `phone_number_e164` and `whatsapp_number_e164` — two independent contact
  endpoints. Either may be absent; equal values are allowed; neither proves
  reachability, WhatsApp availability, verification, opt-in, or consent.
- `education_level_code` — a broad `ISCED_2011_*` reference or
  `NOT_STATED`. It is not a local degree-equivalence or competency decision.
- `degree_name` — optional exact user-entered qualification name. It is not
  verified, canonicalized, or expanded from an abbreviation.
- `education_field_code` — a broad `ISCED_F_*` reference or `NOT_STATED`.
  It is never inferred from a degree or specialization.
- `specialization` — optional exact user-entered specialization/concentration,
  kept separate from `degree_name`.
- `sales_interest_codes` and `sales_interest_other` — optional AC-owned,
  user-selected learning-interest labels. They are descriptive only and do
  not rank a learner, unlock content, select a tenant, or produce a score.

The machine shape is in
[`onboarding-profile-taxonomy-v1.schema.json`](onboarding-profile-taxonomy-v1.schema.json).
The exact source/provenance and no-vendoring decision is in
[`onboarding-profile-source-manifest.json`](onboarding-profile-source-manifest.json).
The route/state contract is in
[`onboarding-profile-state-matrix.csv`](onboarding-profile-state-matrix.csv).

## Authority and controlled-source basis

The required controlled source order was fetched by exact Drive ID on
2026-09-03 before this proposal was drafted:

| Source       | Exact Drive ID                                 | Contract consequence                                                                                                             |
| ------------ | ---------------------------------------------- | -------------------------------------------------------------------------------------------------------------------------------- |
| Master Index | `1gC6BdFZ2LfjrpjM-qPKcX1qWMTUBSAXo3b-AlaOYqus` | Controlled-document precedence; no invented protected semantics.                                                                 |
| BRD          | `1HEp7QN4u3c_636uACznnkruYHhGYHAJWXH7Dlfjybpk` | Experience/persona labels are profile attributes, not authorization; WhatsApp is capability-gated; privacy is a hard constraint. |
| AC-IMP-00    | `10tKbAIJWONFNTzK2-NHffy4h1wKgoQP7VdJH_K2eR-A` | First-slice boundaries; real-call and WhatsApp capabilities remain gated.                                                        |
| AC-IMP-01    | `1JVnCjDdE79YseM-1PuhvW00xcoicwmhoHtUvEuKKrdU` | Exact source fetching, evidence, and forbidden-inference discipline.                                                             |
| AC-IMP-03    | `1ncsRMiMMiQ39tCn7dV3vpqwUnirY06BgSuVdm_BuIFo` | Recovery, accessibility, privacy, and provider gates; no autonomous scoring.                                                     |
| AC-IMP-04    | `1gQnsY1JjphpmOmfyCRZkfI-p0TWZjF1PkY1xF744Gnc` | Person/LearnerProfile boundary, explicit context capture, optional first-slice setup, and no unsupported AI skill claims.        |
| AC-IMP-05    | `1Vvf1wCA_JjrJQwhkTsgyDM_9179G4M899pWWc3-UdXw` | Route/state freeze and evidence discipline before activation.                                                                    |

Supporting controlled sources were also fetched in manifest order: PRD
(`1vZGxiP5GRA7He0gA7oF6hmTeHqoEZUIJko_QBUtDW_k`), IA
(`1VLJTswU2sqlimfoSIROVvlJ9Z6ue-6Dd45oEcu1ddhs`), UX Research
(`1M_IlSgZwWfHVk1IU3JBzY-EhT3RIfXO07WII8MbwxPM`), UX States
(`10HzU7kLk78WBHd_Y23jYaP0rIaScq7gW27e5D7D-08E`), UI System
(`1y7yCqro9ABW8Yn61ZVmnLV8eGlelcq3BisCDTx40SsI`), SRS
(`1qE_ASXOBN-AAuIglfs4-5Fi_HN3x-jDItBYdb95Ou2g`), Data/Tenancy
(`1SUxNYTu30NXwBEbk7os1OBVn4H5qBky-LnzLuOvwaYw`), API/MCP
(`1kWawS57AGVv7jT5Kp2V0Mk8kK0B6BwPzlG6KiAOtpt0`), Security
(`1rFTiq7BI4dpLLMIDacC8qMhpAbAmOct8W_I65Ydqbmw`), Admin
(`12-VjN02jx8M7S8wJrZLcl4OwLcXIFGXKu74wxdJrWuY`), Telemetry
(`1ggdrD_ldZL3ItJsAMONq_ygQFjbR6dOURpeHGXd4M4I`), Mobile/PWA
(`1wxYkUGdHchtSYFpiXxGWQoaT95D4y4LO_qZG7MlEsoI`), DevOps/SRE
(`1r1P2XdYSY8XhcgLR6icYqhlN1vEbqKagj8Rb16JpcJs`), QA/Release
(`1DUx9JIHNC1KCR62Qso6KTFPoBxmfhU6GSuNqSl87hBg`), and ADR/Risk
(`1cNE-8DB0iX28U5IR_StkO-JGE2TPG-pbKn6LQ-bZSaY`). AC-UXA-01 was fetched as
the relevant assurance source (`1ZRyNPkkfc8DsBAlpKE9ksb6Oi-nB9BX-`).

Controlled implications applied here:

1. The server remains canonical. Existing `/v1/onboarding` uses an explicit
   revision precondition and idempotency key; a future promotion must retain
   that behavior and reject unknown fields until the new contract is approved.
2. `/onboarding` is the profile-editing surface. `/settings` is a summary and
   account/settings surface that links to profile editing; a new `/profile`
   route is not introduced by this proposal.
3. Experience, sales-owner, and business-context labels remain editable
   profile attributes. They cannot be reinterpreted as roles, permissions,
   entitlement, or tenant selection.
4. Browser-local recovery is a bounded convenience only. It never becomes
   canonical state, and the existing seven-day/sign-out/purge/conflict rules
   remain in force.
5. No analytics event may carry raw phone numbers, WhatsApp numbers, degree
   text, specialization, or free-form interest text. Presence/count metadata
   may be considered only through a separately approved telemetry change.

## Field contract

All fields are optional in the draft and on the profile summary. `Skip setup`
must remain possible without any field. A future API representation should add
these under an explicit `profile_taxonomy` object in the versioned onboarding
contract; it must not silently reinterpret the existing registration
`whatsapp_number` field or backfill a direct phone number from it.

| Field                  | Type and bound                                                       | Normalization                                                                                                                                                      | Purpose and source boundary                                                                                                                                                  |
| ---------------------- | -------------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------ | ---------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `country_code`         | nullable string; two uppercase ASCII letters; current allowlist `IN` | Trim, uppercase, reject unknown configured code. Do not infer.                                                                                                     | User-declared country context for display/number-entry assistance only. ISO 3166-1 is the code authority.                                                                    |
| `phone_number_e164`    | nullable string; `+` plus 7–15 decimal digits total                  | Canonical payload is E.164. A future UI parser may accept local presentation only after explicit country choice and a reviewed library; do not validate existence. | Optional direct phone endpoint. ITU E.164 supplies structure/max length; no provider lookup.                                                                                 |
| `whatsapp_number_e164` | nullable string; same bound as phone                                 | Same as phone; it may equal phone but is never aliased to it.                                                                                                      | Optional user-declared WhatsApp endpoint. It is not messaging consent or provider status.                                                                                    |
| `education_level_code` | nullable enum `NOT_STATED` or `ISCED_2011_0`…`ISCED_2011_8`          | Uppercase stable code; `NOT_STATED` is explicit.                                                                                                                   | Broad international education-level reference from UNESCO UIS. No degree equivalence/eligibility inference.                                                                  |
| `degree_name`          | nullable Unicode text, max 120 characters                            | Unicode NFC, trim outer whitespace; preserve case, punctuation, and abbreviations.                                                                                 | Exact user-entered qualification name. UGC is consulted for current nomenclature only; no exhaustive list or verification.                                                   |
| `education_field_code` | nullable enum `NOT_STATED` or `ISCED_F_00`…`ISCED_F_10`              | Uppercase stable code; never derive from another field.                                                                                                            | Broad field-of-education reference from UNESCO UIS.                                                                                                                          |
| `specialization`       | nullable Unicode text, max 120 characters                            | Unicode NFC, trim outer whitespace; preserve wording.                                                                                                              | Exact user-entered specialization/concentration, separate from degree name. UGC’s notification pattern supports a specialization suffix, but does not establish equivalence. |
| `sales_interest_codes` | nullable unique array of 1–3 AC-owned codes                          | Trim and canonicalize codes; order is not meaningful; reject unknown/duplicate codes.                                                                              | User-selected learning-interest labels derived from the existing bounded goal choices. This is an AC product interpretation, not a universal taxonomy.                       |
| `sales_interest_other` | nullable Unicode text, max 240; required iff `other` is selected     | Unicode NFC, trim outer whitespace; no automatic categorization.                                                                                                   | User-described interest; never converted into a score, recommendation, or protected label.                                                                                   |

The canonical phone pattern is deliberately narrow (`^\\+[1-9][0-9]{6,14}$`)
to prevent local-format ambiguity. The seven-digit lower bound is an AC input
validation choice, not a claim that every such number is assigned or reachable.
Country calling code is derived from the E.164 value for parsing/display; it is
not persisted as an independent source of truth. For the India configuration,
`+91` is corroborated by the official DoT notice and the ITU assigned-code
table, but the current assignment must be rechecked at activation.

## Normalization and privacy rules

- Preserve user meaning. Trim outer whitespace and apply Unicode NFC to text;
  do not lowercase, transliterate, expand degree abbreviations, or map free
  text to a field automatically.
- Require explicit country choice for local phone parsing. Do not derive
  country from IP, browser locale, GPS, email domain, OAuth claims, or a phone
  prefix. A profile country and a phone’s numbering country may differ.
- Keep direct phone and WhatsApp endpoint values independent. A duplicate
  value is valid; a different value is valid; a missing value is valid.
- Do not send numbers to WhatsApp, a messaging provider, a phone verifier, or
  an external AI service. Provider use, template policy, opt-in, retention,
  and suppression belong to a future capability gate.
- Store only the profile values needed for the user-declared purpose. The
  exact post-closure account/profile retention period remains a security/legal
  policy input and must not be invented here. Deletion requests follow the
  existing eligible-data deletion/anonymization flow; legally retained audit
  or financial facts remain restricted under policy.
- Auto-recovery should not persist contact numbers in browser storage until a
  separate privacy decision approves that treatment. Keep contact values in
  memory for the current form and support user-initiated copy/download when
  safe. Non-contact draft values remain subject to the existing seven-day,
  sign-out purge, mismatch, and storage-failure rules.
- Never log or emit raw values. Errors may identify the field and a safe
  reason (for example, “use international format”) without echoing a full
  number or free text.

## UI and accessibility contract

The implementation target is WCAG 2.2 AA plus the existing AC mobile intent.
The form must:

- use a real label for every input, a `fieldset`/`legend` for grouped choices,
  and a visible, programmatically associated error summary for invalid input;
- expose `autocomplete="tel"` and `inputmode="tel"` only for phone inputs,
  keep country and education controls keyboard reachable, and not use a
  placeholder as the only label;
- announce saving, saved, skipped, offline, conflict, and retryable states
  as text; never communicate them by colour alone;
- move focus to the error/conflict summary after a failed save and return
  focus to the invoking edit control when returning from settings;
- keep conditional `other` inputs discoverable, labelled, and required only
  when their corresponding choice is selected;
- preserve the one-column mobile flow without horizontal overflow at the
  existing 390px target, keep touch targets at least 44px where AC’s mobile
  intent applies, and preserve zoom/reflow;
- avoid exposing raw contact values in live regions, URL query parameters,
  screenshots, or test telemetry.

The taxonomy reference is a build/release artifact, not an end-user network
dependency. If a generated reference is missing or stale, render the
free-text degree/specialization and skip paths with an honest
`taxonomy_reference_unavailable` state; do not ask the learner to download an
official file or block the rest of the profile.

## API and routing contract

This change does not modify API or database code. The following is the bounded
promotion contract for a later controlled implementation:

| Surface                   | Route/API                  | Contract                                                                                                                                                                                                                           |
| ------------------------- | -------------------------- | ---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| Profile edit              | `/onboarding`              | Authenticated verified person; progressive form; optional fields; explicit Save/Skip; no recommendation or score. Return intent is an allowlisted `home` or `settings` value.                                                      |
| Profile read/write        | `GET/PUT /v1/onboarding`   | Preserve server-authoritative snapshot, `ETag`/`If-Match`, UUIDv4 `Idempotency-Key`, safe errors, and no unknown-field tolerance. A future version may add `profile_taxonomy`; activation requires API/data/security/QA promotion. |
| Settings summary          | `/settings`                | Read `/v1/me` and `/v1/onboarding`; show separate phone/WhatsApp rows and a link to `/onboarding?return=settings`. No direct profile mutation or provider state.                                                                   |
| Home gate                 | `/home`                    | `not_started` may route to `/onboarding?return=home`; `in_progress`, `completed`, and `skipped` have explicit next-action copy according to the existing contract. Profile values never authorize learning access.                 |
| Unauthenticated deep link | login/session-expired flow | Authenticate first, then return only to the allowlisted onboarding intent; no open redirect and no profile values in query parameters.                                                                                             |
| Admin                     | separate admin host        | No new admin taxonomy editor. Support may view the self-scoped profile only under existing permission/audit rules; routine recovery must not require direct DB edits.                                                              |

The state matrix’s `ONB-TAX-*`, `SET-TAX-*`, and `ROUTE-TAX-*` rows are the
acceptance contract for presentation, canonical data, recovery, accessibility,
privacy boundaries, and allowlisted telemetry names.

## Sales-interest semantics (explicitly bounded)

The current AC-owned labels are:

| Code                       | UI label                          | Provenance                                                        |
| -------------------------- | --------------------------------- | ----------------------------------------------------------------- |
| `handle_objections`        | Handle objections with confidence | Existing learner onboarding candidate choice.                     |
| `discovery_calls`          | Run clearer discovery calls       | Existing learner onboarding candidate choice.                     |
| `close_more_consistently`  | Close more consistently           | Existing learner onboarding candidate choice.                     |
| `repeatable_sales_process` | Build a repeatable sales process  | Existing learner onboarding candidate choice.                     |
| `other`                    | Something else                    | Contract affordance for coverage; copy requires product approval. |

This codebook is an implementation interpretation, not a protected business
classification or external standard. It may be used to display the learner’s
own selected interests. It must not drive scoring, assessment, entitlement,
tenant selection, employment/talent decisions, or an autonomous course
recommendation. Any personalized starting point requires a separate approved
mapping and an explicit evaluation plan.

## Source, licensing, and generation decision

No authoritative reusable dataset is vendored. The source manifest records the
exact URLs, retrieval date, provenance, licensing assessment, and generation
steps. The decision is based on these facts:

- ISO permits free-of-charge use of country codes, but its full materials and
  publications remain copyright-protected; the contract stores only a current
  allowlisted code and fetches labels through a reviewed release step.
- ITU’s in-force E.164 recommendation is freely available on its official
  page, but ITU copyright remains; the contract references the number rule and
  copies no table or prose.
- UNESCO UIS owns/custodies ISCED. The official manuals provide the standard,
  but the fetched material did not establish a commercial dataset licence; the
  related 2015 operational manual is CC BY-NC-ND 3.0 IGO, which does not allow
  a commercial derivative dataset. Only stable identifiers are represented.
- UGC and Indian DoT official pages are used as authoritative references, but
  a reusable-data licence for their lists/notices was not identified. Degree
  and specialization remain user text instead of a copied list.
- W3C WCAG 2.2 is referenced for acceptance criteria; no normative text is
  copied.

Release generation must fetch each source at the exact manifest URL, record
`source_id`, URL, retrieval date, source revision/date, response SHA-256, and
reuse decision, then run the contract tests. End-user runtime must not fetch
these sources. A stale/missing source blocks taxonomy artifact promotion only;
it does not block the core learner project.

## Inference ledger

| Item                                                        | Classification                                                                             | Required handling                                                                                 |
| ----------------------------------------------------------- | ------------------------------------------------------------------------------------------ | ------------------------------------------------------------------------------------------------- |
| India/`IN` is the requested country                         | Inference from work-item context; not present as a direct user decision in this repository | Confirm before activation; retain an explicit versioned country allowlist.                        |
| Broad ISCED code identifiers and paraphrased labels         | Standard-derived implementation interpretation                                             | Keep codes separate from local equivalence; recheck current UIS release.                          |
| India `+91` support                                         | Corroborated by official DoT/ITU references; current assignment freshness remains a gate   | Recheck current E.164/DoT source at activation; do not infer number validity.                     |
| Sales-interest codebook                                     | AC-owned interpretation of existing candidate goal labels                                  | Product-owner promotion required; no protected or scoring use.                                    |
| Seven-digit minimum, text lengths, three-interest cap       | Local validation/recovery proposals                                                        | Treat as contract values pending controlled API/data promotion; they are not universal standards. |
| Contact exclusion from automatic local drafts               | Privacy/data-minimization proposal                                                         | Security/privacy review before implementation; preserve explicit user copy/download recovery.     |
| `/onboarding` as profile editing and `/settings` as summary | Follows current IA and route contracts                                                     | Do not add a parallel `/profile` route without controlled IA change.                              |

## Activation gates and explicit non-goals

This proposal does not activate any of the following:

- scoring, evaluation, readiness, competency, certification, hiring, or talent
  decisions;
- personalized course mapping or recommendation;
- consent capture, marketing/transactional preference changes, or age-policy
  changes;
- WhatsApp API/provider integration, message sending, verification, opt-in,
  templates, suppression, or delivery claims;
- phone verification, geolocation, IP inference, external AI, call capture,
  transcription, or provider data processing;
- database migrations, registration-field rewrites, admin taxonomy editing,
  production deployment, or runtime source fetching.

Before implementation, obtain the requested-country confirmation and promote
the contract through the controlled PRD/IA/UX States/UI System/SRS/Data/API/
Security/QA documents. Then add a canonical model migration, revisioned API
tests, local-draft privacy tests, accessibility journey evidence, deletion/
retention review, and exact-current staging proof. AC-SVAL-01 and
AC-GOV-AUD-001 remain out of scope until scoring/evaluation or provider/data
activation is explicitly requested.
