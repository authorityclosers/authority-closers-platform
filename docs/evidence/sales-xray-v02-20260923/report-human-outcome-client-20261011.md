# AUT-1677: prepared human outcome read/save boundary

Continuation source: `a6f7aa4`; owner outcome request in the strike inbox,
11 October 04:50 IST. The binding spec and earlier controlled-source fetch
receipt in `report-pillars-word-20261010.md` remain the source basis. This
slice finishes a client boundary while canonical persistence waits for the
reviewed migration chain. It mounts no route or editor and claims no outcome
API, prospect-stage write, production acceptance or manager authority.

## Behavior

`report-call-outcome-client.ts` prepares explicit reads and commands for
`/v1/conversation/prospects/calls/{submission_id}/outcome`. Responses bind the
exact call, person, tenant and session. A recorded fact needs a human basis,
lock, revision, actor and aware audit time. Revision zero with null value and
null provenance is unrecorded; an absent or malformed API is unavailable.
Only an explicit server `can_edit: true` permits the client command.

The command freezes entered values and the pre-read outcome, membership and
human-stage revisions before transport. A response must retain that person
link and exactly the requested reason/date/decimal/currency. A changed fact
needs the next outcome revision and current human actor. An idempotent fact
keeps its revision, original actor/time and stage provenance. Other link,
revision, actor, value or clock changes cannot acknowledge a save. The client
does not assign a prospect or derive a deal stage.

Transport uses only the fixed same-origin path. The default 2.5-second bound
includes streamed JSON reading, capped at 16 KiB with strict UTF-8. Caller
cancellation, stalled transport/body, redirects, HTTP failures and malformed
responses return content-free states. An uncertain write has no automatic
retry or optimistic success; the caller must reload before another command.
Human value parsing now detaches deal amounts/currencies from mutable drafts.

## Validation

- 108 focused Vitest cases pass across the new client, human value codec and
  existing controlled editor. These cover scope mismatch, missing/AI provenance,
  moved links and stage edits, idempotence, exact human values including
  Devanagari, timeout/body limits, cancellation and late replies.
- Incremental TypeScript checking, cached changed-file ESLint, Prettier and
  `git diff --check` pass. The initial test-file formatting parse error was
  corrected before tests ran; no pass is claimed for that attempt.
- No displayed component, route or styling changed. Existing screenshot proof
  remains historical; this change adds no browser, build or production claim.

Backend adoption must still provide append-only transactional storage, audit,
optimistic link/stage conflicts, current account admission and canonical rep or
assigned-manager command authority. Billing roles and AI speaker labels do not
supply those grants. Admin and `sx.rep_week.v1` remain on the recorded service
handoff until mounted reads and PostgreSQL authority/audit evidence exist.
