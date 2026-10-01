# ADR 0042: Sales Xray speaker map — which speaker is you

Date: 2026-09-30. Status: Accepted (architecture) — CTO, 30 Sep 2026; CEO option A decided: naming within coaching-v7.

## Context

Sales Xray needs one server contract for speaker names, roles and the account holder's confirmation. The fixed rev 3 contract replaces D1 of rev 2 and adds N1–N8 and the frozen-snapshot requirements of AUT-615 R1–R8. This ADR records those decisions; it does not activate a recipe or approve scoring. ADR 0036 remains unchanged.

The shipped web fallback (`speaker-profiles.ts`, `suggestYou` and `detectSpokenNames`) supplies the deterministic patterns to port. C2 provider speaker labels remain uncertain attribution. Naming uses the existing C5 `coaching-v7` call: no new AI stage, bridge recipe, extra per-upload provider call or unresolved naming timing/cost decision.

## Decision

### Recorded decisions

- **D1 — Two server sources:** Read-time deterministic `speaker_map.py` ports the shipped name patterns and role cues; the existing C5 `coaching-v7` call also returns model `speakers[]`. Stage codes and ADR 0036 stay unchanged.
- **D2 — Computed prediction:** Text prediction is a pure function of the C2 transcript and the account holder's name, computed on read and not stored. Store user decisions; `map_revision` is the content hash of the resolved map.
- **D3 — Append-only decisions:** `conversation_speaker_map_revisions` follows call-name revisions: revision number, actor and time, latest wins, never updated. Erase through the same recording-erasure and person-deletion hooks as call names.
- **D4 — Per-speaker, per-field precedence:** Current user revision → channel with saved user side (phase 3) → model from a report on the same `transcript_revision` → text prediction. Only user confirmation and a saved channel side are authoritative; model/text remain display-only.
- **D5 — Words and declarations:** Roles use words with segment-id cues, the recording channel (phase 3), or the user's answer. No verified identity or voice inference; voice enrollment remains separate in [AUT-313](/AUT/issues/AUT-313).
- **D6 — Account holder:** Use the call owner's Sales Xray profile name (`Person.display_name or first_name`): signed-in actor on HTTP reads, `_customer_person_id` in the worker, never processing-service `recording.person_id`. It labels `you` unless renamed. Model/text may set `you` only when a stated name matches that profile; otherwise a seller is `salesperson`. A user answer or saved channel side may set `you`.
- **D7 — Frozen report input:** Declaring prompt revisions alone receive names-free `speaker_roles`; v1–v6 remain byte-for-byte unchanged. Resolve once when C5 is first built and write once to `conversation_processing_plans.speaker_roles`, reusing it through polls and dispatch. A user change affects the next plan. Report provenance comes from that snapshot, never model text. The first declaring revision is `coaching-v7`.
- **D8 — Profile unchanged:** Keep `dipak_report_v1.json` and its approval hash unchanged. Predicted attribution stays uncertain and labelled predicted; user confirmation is independent adjudication, and phase-3 channel side is declared by the user. A later profile clarification does not block this work.
- **D9 — Alignment:** Transcript-level `speaker_identity` is the closed set `unverified_provider_labels|text_predicted_roles|model_named_roles|user_confirmed_roles|channel_mapped_roles`; other values fail `alignment_claimed_speaker_identity`. Per-segment identity stays `unverified_provider_label`; C2 segments are never relabelled or changed.
- **D10 — Confirmation after reporting:** Update call names, You, lanes and transcript labels immediately, without AI or minutes; never rewrite report text. Matching `you` changes the predicted note to confirmed. A different `you` shows “This report used an earlier speaker guess” and offers **Update analysis** through existing quote/accept: reuse C2/C4, run C5 only, no user minutes (charged once per upload), with provider cost quoted and budget-checked. Reports without a declaring revision never use the map.
- **D11 — Two-channel phase 3:** Distinct channels each become one speaker (0 left, 1 right); identical stereo counts as mono. Save `left|right|null` per account. If unset, predict from words and ask “Is this you?” with “Remember for my two-channel recordings” ticked. Preflight already accepts 1–2 channels; C1 records `source_channels`. Scribe `use_multi_channel` / Deepgram `multichannel` changes the C2 recipe/cache key; combined-channel duration may double transcription cost. CTO brings the later phase-3 design/cost to CEO after S3.
- **D12 — Separate endpoints:** Follow ADR 0036 D11: report, transcript, overview and `/v1/me/*` responses stay unchanged, preserving strict web parsers and stored report hashes.

### Fixed rev 3 additions (N1–N8)

- **N1:** Port the existing stop-list, name patterns and Hindi greetings, including “मेरा नाम …” and “… जी नमस्ते”; preserve spoken spelling and honorifics. A two-speaker greeting may name the other speaker; a three-speaker greeting does not guess the addressee. Both sources use D1's contract.
- **N2:** Model output is `speakers[{speaker_id, spoken_name, role, evidence_segment_ids, confidence}]`. `spoken_name` is exact as spoken, honorific retained, or null; evidence ids count 1–5; confidence is `low|medium|high`, never numeric. On new provider-output parsing, require known C2 speaker ids, evidence ids belonging to that transcript, and literal normalized name presence in at least one cited segment. Drop a failing entry with a content-free diagnostic; the report succeeds and no repair retry is used. Never perform this check on `canonical_read`.
- **N3:** API roles are `you|salesperson|prospect|other` (or null on unresolved GET), with at most one `you`. Role cues alone produce `salesperson`; D6 governs model/text `you`. The snapshot maps `you` to `seller` with `is_account_holder: true`, `salesperson` to `seller` with false, and `prospect|other` unchanged with false.
- **N4:** Use D9's closed origins and D4's field precedence. Wrong-transcript reports cannot supply model names. Model names/roles are pre-filled and display-only until confirmed; browser storage never establishes authority.
- **N5 / R2:** Persist the exact names-free snapshot below once per plan. Pass the same snapshot to C5 and the later validator; never read live revisions, browser state or model output to establish enforcement provenance.
- **N6:** GET adds `salesperson`, `model` in both source enums, `model_named` status and per-speaker `confidence`; PUT accepts `salesperson`. The exact keys and enums are below. D12 compatibility holds.
- **N7:** Before a transcript exists, GET returns 200, `status: unavailable`, `unavailable_reason: transcript_not_ready` and `speakers: []`, with no placeholder names or roles. Checks use fictional fixtures only, with no live-call access.
- **N8 — Later UI wiring:** Read `ac.xray.speakers.v1:<callId>` once as pre-fill, save a user revision only after the user's tap, then remove the key. Sign-out and successful call deletion remove these keys too. After S3, server results replace client fallback. This cleanup is later UI work, outside S3 and this docs slice.

### API contract

Only the signed-in owner of a claimed call may use the map routes, through the call-name route's `current_owner` guard. Anyone else receives 404.

`GET /v1/conversation/acquisition/submissions/{submission_id}/speaker-map` returns:

<!-- prettier-ignore -->
```json
{
  "schema": "ac.sales-xray.speaker-map/1",
  "submission_id": "uuid",
  "status": "predicted | model_named | confirmed | channel | unavailable",
  "unavailable_reason": "transcript_not_ready | null",
  "transcript_revision": "string | null",
  "map_revision": "64 hex | null",
  "user_revision": 0,
  "speakers": [{
    "speaker_id": "speaker_0", "number": 1,
    "role": "you | salesperson | prospect | other | null",
    "role_source": "predicted | model | confirmed | channel | null",
    "display_name": "string | null",
    "name_source": "stated_in_call | account_profile | user | model | null",
    "name_evidence": [{ "segment_id": "s3", "start_ms": 4000, "end_ms": 6200 }],
    "role_cues": [{ "cue": "introduced_own_company", "segment_id": "s3", "start_ms": 4000, "end_ms": 6200 }],
    "channel": null, "confidence": null
  }],
  "report_basis": null
}
```

Enum/type strings above describe the wire contract, not literal runtime values. `confidence` is null unless the selected source is model, then `low|medium|high`. Number speakers 1..n by first appearance. Null role asks “Which one is you?”; never predict `unattributed`. At most five role cues per speaker, from `stated_account_holder_name|introduced_own_company|stated_call_purpose|asked_discovery_question|presented_offer_or_price|proposed_next_step`.

`report_basis` is null until S4 and for reports without roles; otherwise `{status: predicted|model_named|confirmed|channel, map_revision, you_speaker_id, matches_current: bool}`, comparing roles only. GET sets `ETag` to `user_revision`.

`PUT /v1/conversation/acquisition/submissions/{submission_id}/speaker-map` requires `If-Match: <user_revision ETag>`, using call-name `parse_revision_etag` / `format_revision_etag`, and a body of at most 8 KiB read within 5 seconds:

```json
{
  "transcript_revision": "string",
  "speakers": [
    { "speaker_id": "speaker_0", "role": "you", "display_name": null }
  ]
}
```

List every transcript speaker exactly once, at most 32, with roles `you|salesperson|prospect|other` and at most one `you`. Confirm sends shown roles; changing You sends swapped roles. A rename is 1–80 characters without controls; null defaults to the profile name for `you` or the stated name for others. Stale `If-Match` returns 409 “The speakers changed. Reload before saving again.” Stale transcript revision or the 50-revision limit also returns 409. Identical content is a no-op 200 with no new row. Return the GET body and new ETag; emit `conversation.speaker_map_changed` with revision numbers only, no names. No AI, minutes or report change.

Phase 3 alone adds `GET` / `PUT /v1/conversation/acquisition/speaker-settings`: `{two_channel_you_side: left|right|null, revision: 0}`.

### Frozen snapshot and enforcement boundary (R1–R8)

Exact shape: `origin`, `transcript_revision`, `map_revision`, `speakers[{speaker_id, role: seller|prospect|other, is_account_holder}]`:

<!-- prettier-ignore -->
```json
{
  "origin": "unverified_provider_labels | text_predicted_roles | model_named_roles | user_confirmed_roles | channel_mapped_roles",
  "transcript_revision": "C2 revision",
  "map_revision": "64 hex",
  "speakers": [
    { "speaker_id": "speaker_0", "role": "seller", "is_account_holder": true },
    { "speaker_id": "speaker_1", "role": "prospect", "is_account_holder": false }
  ]
}
```

No names, name evidence or profile strings enter this block. The nullable plan column has no backfill. Resolve before first C5 construction; reuse unchanged through `StageRequest` and `coaching_source_context`, polls and dispatch. PUT never mutates a running plan. `speaker_identity` echoes the stored origin; C2 bytes and per-segment identity remain unchanged. S4 builds the dormant mechanism with empty `SPEAKER_ROLE_PROMPT_REVISIONS`; [AUT-347](/AUT/issues/AUT-347) declares v7 while retaining runtime Gate 2 refusal. S5 parses/stores model output after [AUT-348](/AUT/issues/AUT-348), without activation or historical rewrites.

R1–R3 permit enforcement only for `user_confirmed_roles` or saved-side `channel_mapped_roles`, the matching C2 revision, and at least one prospect. Unknown, unconfirmed, stale or malformed attribution (duplicate/unknown speaker ids or revision mismatch) falls back through D4 with a diagnostic and cannot enforce; reports publish unchanged with snapshot provenance. `other` or unmapped speakers cannot supply prospect support.

R4–R5 are later validator rules, subject per dimension to P-A's controlled-source confirmation or Dipak sign-off via CEO: `human_connection_trust`, `discovery_deep_understanding` and `qualification` in `observed|conflicted` require at least one cited prospect segment; seller evidence may also be cited. No semantic answer test; other dimensions and non-observed states (`insufficient_evidence`, `not_applicable`, `unknown`) stay unchanged. Literal quote/slice/time checks run first. Unconfirmed dimensions remain unenforced; S0–S4 are not blocked by P-A. No new scoring rule or two-bearing-segment floor is approved.

R6–R8 preserve the separate validator's `report_dimension_prospect_evidence_required` / `conversation_report_dimension_prospect_evidence_required` failure path, with only that code added to worker safe codes and C5 repair allowlist. Use the existing single eligible bounded repair (returned failure, accepted budget, not OpenAI, not already repaired); name failing dimensions/prospect ids, revalidate fully, then fail if still invalid. Never rewrite statuses or substitute a non-observed fallback. Apply only to new output of the first declaring recipe (v7; a new revision if already released), never `canonical_read`; v1–v6 and historical reports stay unchanged. The contract is shared with UI; enforcement waits for S4, the declaring recipe and P-A, without new endpoints or names in role input.

## Alternatives

- CEO option A is decided: name generation and the first speaker-role consumer run within `coaching-v7`. A separate stage, bridge recipe or extra per-upload request is not selected; no Scout cost task is required.
- Client storage, voice identity and predicted/model attribution cannot replace a confirmed server revision or saved channel side.

## Consequences

Names and roles share one owner-only contract, with deterministic reads before v7 and validated model pre-fill later. Confirmation updates the call immediately and preserves report history; a quoted C5-only rerun can use a new snapshot. Snapshot provenance prevents live edits from changing a running analysis or predictions from becoming enforceable attribution.

## Data and safety

- Revisions are tenant-scoped: `id`, `tenant_id`, `submission_id` (claimed-submission FK), `revision` (≥1, unique per submission), `transcript_revision`, JSON `speakers[{speaker_id, role, display_name}]`, `actor_person_id` and `created_at`. Cover the table in backup catalogues/parity tests; migrations and implementation are later slices.
- Supersede user history; never update prior revisions. Erase map rows with recording erasure and person deletion beside call-name erasure; retain content-free audit history. Phase-3 channel preferences are also append-only (`tenant_id`, `person_id`, `revision`, `you_channel: 0|1|null`, `created_at`).
- Fictional fixtures only in Git/checks; no customer-data checks, secrets, profile edits, activation, staging or production work here. Existing consent, retention, provider, professional and recipe gates continue to apply.

## Reversal cost

Changing shared API enums, snapshot fields or provenance requires coordinated backend/UI and recipe-consumer changes. Preserve prior revisions, frozen plans, historical reports and existing hashes; a later channel recipe change needs governed approval.

## Evidence

- [Fixed rev 3 contract](/AUT/issues/AUT-624#document-parent-plan-rev3), revision `da009f49-2e08-40b9-a8cf-dfd1cd96c5cb`; source facts pinned at `f86df7f`, rechecked at `38aed8ed`.
- [CTO N1–N8 brief](/AUT/issues/AUT-624#document-decision-brief), revision `e7301533-e92f-43e8-9ffb-c69e2059eb8f`; [R1–R8 brief](/AUT/issues/AUT-615#document-decision-brief), revision `6cbf3709-d0f7-4875-8ae5-ccdb8e2c9754`.
- [CEO option A](/AUT/issues/AUT-311#comment-d8d49a59-ea5a-47ec-8fa2-68e6b0b8af00); [ADR 0036](0036-layered-sales-xray-report.md) supplies the section layout and separate-endpoint pattern.

## Owner

CTO owns the accepted architecture of 30 Sep 2026; CEO decided option A. Chief of Staff owns any pilot-evidence escalation.

## Supersedes

Rev 2 D1 and the old naming holds are superseded by fixed rev 3. D2–D12 and AUT-615 R1–R8 retain force. This ADR does not supersede or edit ADR 0036.

## Trigger to revisit

Revisit option B only on pilot evidence of wrong predicted names before v7 ships, through Chief of Staff. Review phase-3 channel design/cost after S3, or revisit shared contracts and rubric enforcement only through their existing decision and activation gates.
