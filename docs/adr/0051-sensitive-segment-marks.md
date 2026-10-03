# ADR 0051: Sensitive-segment marks

Date: 2026-10-02. Status: accepted (CTO, AUT-519 plan rev 1, 30 Sep 2026);
step T1 implemented in AUT-520. Reference-only: this record names no call
content. Proof is by IDs, counts and hashes.

## Context

Research issue ETH-03 (AUT-518) found a sensitive disclosure quoted in a Sales
Xray report. Stored drafts, checkpoints and retained C5 versions are append-only
history and must not be rewritten. Containment therefore needs a durable,
audited fact that says "withhold this segment", written by a named operator and
applied at read time on every surface that serves the transcript or quotes it.

## Decisions

- **D1: the mark is data.** `conversation_sensitive_segment_marks` holds one row
  per action, keyed by `(tenant_id, recording_id, transcript_revision,
  segment_id)`. Columns: `id` (the command intent ID), `category`
  (`SENSITIVE_FINANCIAL` | `SENSITIVE_LEGAL`), `action` (`mark` | `release`),
  `supersedes_mark_id` (required on `release`, unique, so a mark is released at
  most once), `source` (`operator` | `generation`), `actor_person_id`,
  `reason_ref` (a short reference such as an issue ID, pattern
  `^[A-Za-z0-9][A-Za-z0-9 ._:#/-]{2,79}$`, never content), `audit_event_id`
  (unique) and `created_at`. Database checks enforce every enumeration, the
  release shape and the reason bounds. Update and delete are refused by ORM
  hooks and by the PostgreSQL trigger
  `prevent_conversation_command_mutation()` from migration 0030. A release is a
  new row; a mark is effective while no release supersedes it. The migration
  (`20261002_0067`) is forward-only. Marks hold no content, so recording
  erasure keeps them.
- **D2: written only through the platform API.** The platform-scope capability
  `platform_content_safety_manage` joins both `capability_grants` checks in the
  same migration (the 0054/0060 pattern) and is granted with the capability
  CLI, never with SQL. Routes live under `/v1/platform/sensitive-segments/…`
  on the admin surface, behind `platform_projection` and `require_safe_origin`.
  Each write takes an `Idempotency-Key`; the command intent ID is derived from
  the operator, the key and the segment, so a same-key replay returns the same
  rows without a second write, and a same key with a different change is a
  409. Each row has one audit event in the recording's tenant naming the
  operator and the `reason_ref`. No route or error returns segment text, and
  validation errors on these routes omit the request input.
- **D3: withhold at read time; never rewrite stored data.** A pure guard
  (`sensitive_segments.py`, step T2) runs on every reader payload after
  projection. With no effective marks the payload is byte-identical to today.
  Marks apply to any recording that serves the same `transcript_revision`,
  because duplicate uploads reuse the retained C2 transcript. `effective_marks`
  therefore returns the unreleased marks of the recording or of any recording
  sharing the revision.
- **D4: the withheld set W\*.** W\* is the marked segment IDs plus every
  segment of the served transcript sharing a normalised word 4-gram (NFKC,
  `casefold()`, tokens `[\w'-]+`) with a marked segment's text. Over-withholding
  on a marked call is accepted; a stop-word refinement is a later option.
- **D5: a shape-preserving marker.** `WITHHELD_MARKER = "[Withheld for
  privacy]"` (three tokens, so it never matches a 4-gram, and names no
  category) replaces `quote`/`text` on any dict whose `segment_id` is in W\*
  (rule A), transcript segment `text` whose `id` is in W\* (rule B), and any
  other string of four or more tokens sharing a 4-gram with marked text
  (rule C). Keys, IDs, timings and list lengths never change. The web parsers
  keep accepting the report; no web change is needed for containment.
- **D6: the neighbour rule is kept.** Root marks both the disclosing segment
  and its neighbour, so the audit trail names both.
- **D7: generation inputs.** Until T4 ships input masking, any path that sends
  a marked recording's C2/C4 to a provider again returns 409 (new plans and the
  C5 benchmark). Retained-C5 revalidate/correct makes no provider call and is
  read through the guard.

## Consequences

- Containment is an additive, audited fact; history is superseded, never
  overwritten, which keeps report hashes and restore parity intact.
- The marks table joins the backup parity catalogue as contract
  `ac-postgres-parity-v40` at head `20261002_0067`.
- The validity of a `transcript_revision` is decided by the recording's
  non-erased C2 checkpoints; segment IDs are checked against that checkpoint.
  Erased checkpoints keep existing marks effective but accept no new ones.
- Re-marking an effective segment is a no-op that returns the existing mark,
  whatever category is requested; changing the category means release, then
  mark.
- Steps T2 (guard and reader surfaces), T3 (Root grant and marks on staging)
  and T4 (generation-time marking and census) follow the AUT-519 plan.
