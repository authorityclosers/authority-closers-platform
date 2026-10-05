# ADR 0054: Product updates and notifications

## Context

What's new currently reads six handwritten `changelog.ts` entries and stores
seen state on the device. The owner accepted AUT-423's product updates policy
(plan revision 1, 30 September 2026). AUT-433's technical plan revision 3 specifies
decisions D1–D8. This records those decisions; AUT-468 implements only the store.
ADR 0050 is already taken, so this uses the next available number, 0054.

## Decision

1. **Store (D1).** `product_updates` is append-only versioned history. Columns:
   `id`, `note_key`, `version`, `supersedes_id`, `release_id`, `source_pr`,
   `note_date`, `title`, `items`, `audience`, `major`, `feature_key`, `status`,
   `created_by`, `created_by_person_id`, `created_at`, `published_at`.
   Titles contain 1–60 characters; items contain 1–4 strings, each at most
   200 characters (PR notes later allow 1–3). Audiences are `everyone` (default),
   `org_admins`, `testers`. Plan targeting is a later extension, not an inferred
   audience rule. Status is `draft`, `approved`, `published`; `published_at` exists
   exactly when published. Creators are `seed`, `deploy`, `admin`.
   `(note_key, version)` is unique; version 1 has no predecessor, later versions
   require one; each row has at most one successor. Editing, approving and
   publishing insert new rows. PostgreSQL triggers and ORM guards reject
   updates and deletes.
   `update_seen` has `id`, `person_id`, `note_key`, `seen_at`, unique by person
   and lineage and append-only. It belongs to the account across devices.
   `notifications` has `id`, `person_id`, nullable `tenant_id`, `kind`,
   `dedupe_key`, `title`, `body`, relative-path `href`, `urgent`, `created_at`,
   `read_at`. Kinds are `report_ready`, `analysis_paused`, `invite_received`;
   `(person_id, dedupe_key)` is unique. Only `read_at` may change, once from
   null to a timestamp. Deletes are refused. Person and tenant references use
   foreign keys. `platform_updates_manage` is explicit platform authority,
   not a membership role. Migration 0075 seeds the six original notes as
   published version-1 rows and advances backup parity to v46 (133 tables).
2. **Visibility (D2).** Staging and production select the highest published
   version per lineage; development selects the latest version and labels
   unpublished versions as drafts. Organisation admins must be active owners
   or admins of registered organisations. Testers use `InternalTesterPolicy`;
   absent policy admits nobody. Code registry feature resolvers filter notes;
   unknown keys hide them. Plan resolvers come later.
3. **Bell without fan-out (D3).** At read time, visible notes are grouped by
   `release_id` into one release entry. It is read when all its notes are seen.
   The notification table stores product events only. Publication therefore
   does not write one row per person, and audience changes apply immediately.
4. **PR text (D4).** A `## User-facing note` section contains `Title:`, 1–3
   plain-language grade-8 bullets, optional `Feature:`, or `none`. One stdlib
   parser serves the future check and writer. The check refuses missing or
   malformed notes and `none` for changed non-test Sales Xray app files.
   Older PRs receive a warning. Studio sync creates an empty section that
   UI Guard fills before approval.
5. **Wording approval (D5).** The watchdog adds `note-approved` when merging
   with CEO merge approval. UI Guard notes stay drafts until the CEO labels
   the PR or approves in Admin Updates. The CTO checks wording during review.
6. **Release-bound publication (D6).** CI collects notes and approval labels
   from the last 200 merged PRs and bakes JSON into the API image. Collection
   failure produces an empty file and warning; notes do not block releases.
   After migrations, staging deployment and production promotion run an
   idempotent writer; rollback skips it. Missing lineages become drafts or
   approved notes; an unedited deploy draft can be superseded by approval;
   lineages whose newest version is approved are published. Text is never
   overwritten. Writer failure warns without blocking release. Admin approval
   publishes immediately only in the environment where the row already exists
   with its code. Each environment owns separate rows.
7. **Dev (D7).** At the plan's decision time, the dev `/v1` proxy used staging
   (AUT-243), so dev read staging notes. DV1 (AUT-477) separately enables the
   writer on a development back end for draft previews. This slice changes
   neither routing nor the deployed screen.
8. **Channels (D8).** Email and WhatsApp remain off: no outbox or sender.
   What's new displays visible notes, the bell groups releases and events, and
   corner cards show only major notes or urgent events, at most one update card
   per session with permanent dismissal. Channel activation is later work.

## Alternatives

- Repository note files were not chosen: the owner selected the PR field,
  and files would make studio PRs mixed scope.
- Reading GitHub from the host during deployment was not chosen: the engine
  token is Actions-read only, and another token would require a secret change.
- Per-person release rows were not chosen: publication fan-out would create
  another source of seen state.
- Reviving AUT-71 announcements was not chosen: that plan is parked; any
  resumed work should reuse these tables rather than add `announcements`.

## Consequences

Historical text and read evidence survive edits and retries. PostgreSQL enforces
item shape and string bounds with an insertion trigger; a portable JSON array
count CHECK and model item validation let SQLite
build and exercise the store. Notification history has one allowed transition.
The first slice introduces no routes, grants, writers or screen changes.
Backup contracts retain historical heads while adding all three tables.
Seen and notification rows remain for as long as the person exists, with no time-based purge; approved person deletion must erase both in the same transaction through a future narrow trigger bypass scoped to a transaction-local setting naming the deletion approval, while normal mutation remains refused (CTO decision, 5 October 2026); P2 adds no deletion path or migration.

## Reversal cost

Migration 0075 is forward-only. Reversing storage requires a later migration or
the verified restore path, preserving audit-critical history. Routes and writers
can change independently in their assigned slices.

## Evidence

- [AUT-423 policy, revision 1](/AUT/issues/AUT-423#document-plan)
- [AUT-433 design, revision 3](/AUT/issues/AUT-433#document-plan)
- [AUT-468 store card](/AUT/issues/AUT-468)
- `changelog.ts` at `dc25878`, unchanged at source pin
  `d8da579226496c731f1a216ca72ce9bcc9233c61`
- [Store verification](../evidence/AUT-468-product-updates-store.md)

## Owner

CEO owns product policy and wording approval; CTO owns technical design.
Platform Lead implements this store slice.

## Supersedes

No ADR is superseded. This records AUT-433 D1–D8; later UI work replaces the
handwritten changelog and device-only seen state.

## Trigger to revisit

Plan targeting, activating external channels, changed approval policy, a
separate development back end, or an approved retention and erasure policy.
