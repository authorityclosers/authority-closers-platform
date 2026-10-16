# Gold reviewer workspace — owner task ecff5661

The existing Admin reviewer workspace now supports the owner's 27-pointer
Report. Its 29 reviewable lines are the 27 pointers, Final Call Outcome and
coaching. Each line shows the saved AI draft and accepts agree/partly/disagree
or a 0–100 score, plus an opinion. Each successful save immediately creates a
gold row; another save supersedes the earlier row. The AI review is unchanged.

## Source and authority

- `/reviewer/review/<assignmentId>` remains the existing assignment URL. The
  dedicated reviewer mailbox login and cookie remain separate from account
  sessions. Existing assignment, source, owner, permission, retention, expiry,
  revocation and transcript-revision guards apply to reads and saves.
- Admin → Reviewers adds/removes standing gold reviewers, with an audit event.
  Removing a designation also revokes its existing gold assignments. No learner
  membership or enrollment is provisioned. Admin keeps its existing dashboards.
- A separate bounded reader in the existing conversation worker checks saved
  `pointer-review/1` rows once per minute. It excludes canonical sandbox tenants
  and canary calls, verifies the saved source and permission, and assigns each
  call once per standing reviewer. An advisory transaction lock and a unique
  `(recording_id, reviewer_id)` constraint prevent concurrent duplicates. It
  neither calls a provider nor sends mail.
- AI values come from the newest saved review for the exact call, run, report,
  source and transcript revision. A save binds the particular review the person
  judged, its digest, reviewer, timestamp and call object. Gold rows retain the
  review id/digest rather than copies of transcript quotes or AI text. The Admin
  gold viewer resolves the original AI value only when its digest still matches.

## Retention and history

Migration `20261016_0094`, after the existing `0093`, adds the three gold tables.
The gold service inserts a new row for every changed judgement; it has no
update/delete route. The earlier save is retained and referenced by
`supersedes_id`. Canonical application call erasure nulls every gold payload,
sets `erased_at`, and preserves provenance in the same transaction as the call
and its pointer reviews. The Report owner installed this application hook in
`2a7eff86`; H does not edit scoring or `pointer_review*` source files.
Backup/restore parity v61 includes all three tables.

The latest Report-owner handoff explicitly requests removal of the original
0094 trigger/function creation before release: the migration-safety gate refuses
`op.execute` in upgrades. The corrected upgrade uses only literal table/index
operations and keeps its constraints, revision and parent. Empty-table rollback
uses `IF EXISTS` for the old trigger objects, and refuses any retained gold
history, including already-erased rows. The earlier trigger-bearing 0094 ran on
dev before this correction; changing source does not remove those existing dev
objects. No live downgrade, revision replay or manual schema cleanup is performed.
The release operator must retain that dev/fresh-schema distinction.

All reviewer and Admin dataset reads reapply current privacy marks; dataset
reads also recheck source access. Browser retries reuse their save key. A stale
tab must reload before it can supersede a newer opinion.

## Verification

Fictional PostgreSQL fixtures exercise the real local reporting and reviewer
services, mailbox challenges through the fake mail dispatcher, HTTP origin and
session checks, immediate saves and re-saves, stale-tab refusal, wrong-source
refusal, sandbox exclusion, concurrent readers, revocation, and gold erasure.
The data-change test proves dry-run, repeat apply, an unverified new Person and
unchanged learner memberships. Model drift and the three backup consumers are
checked against migration 0094.

Focused combined check: **36 passed**, including the existing service and guest
owner regressions. Final changed-source database and frontend receipts are in
`/home/acdev/strikes/1801/gold-*-20261016-final*`. Frontend checks cover populated
29-line rendering and response validation, incremental TypeScript and touched
ESLint. Python checks cover Ruff, focused mypy and `import ac_platform.http`.

Shared Admin dev captures are taken on `127.0.0.1:3028` (Sales Xray's `:3026`
does not serve reviewer routes), desktop/phone, light/dark, after the UI commit.
The browser uses fictional reviewer/call responses and intercepts every API
mutation. Those captures verify rendering and interactions, not hosted account
access. Paths and final receipts are retained in the strike NOTES.

## Approved account change

`scripts/data-changes/designate-gold-reviewer.py` is dry-run by default and
records Suyash's approval, ecff5661, before/after and a run id. `--inspect` only
reads whether Dipak's global Person exists. An absent Person can be created
unverified with `--create-person`; the normal reviewer mailbox proof is required.
It never creates a learner membership, enrollment, session or outbound message.

The builder has no injected dev database execution context and cannot use the
Docker socket. The read-only dev Person lookup and approved dev apply are
requested through the coordinator's existing operator route. This is not a
production account-change receipt. Production apply belongs to the owner's
laptop operator after ship, snapshot and shown dry-run. Exact commands and URL
contract: `/home/acdev/strikes/1801/REVIEWER-LINK.md`.

## Final dev receipt

Backend `645c5c7e`, UI `da4fdabb`. Automatic dev pickup served exact
`da4fdabbbdbee545cb756fc4ef6a9b484960ddaa` at 06:50:15 UTC; all four checked
runtime/migration Git blobs matched. The deploy log records migration, login
and upload smoke, healthy promotion and worker restart at 06:49:30–51 UTC.
Anonymous reads of both new Admin routes and the new reviewer route return 401.

Final changed-source PostgreSQL module: **8 passed / 45.41s**. Final frontend:
**2 passed**, incremental typecheck and touched ESLint exit 0. Focused mypy:
**5 source files, no issues**. The earlier combined **36 passed** includes the
schema/registry/parity and existing worker/guest-source regressions; the eight
are a rerun, not eight additional distinct cases.

Four populated captures on shared Admin dev were visually inspected:
`gold-review-{1440,390}-{light,dark}.png` under
`/home/acdev/strikes/1801/shots/2026-10-16/`. All four check a first save and a
re-save with the exact predecessor id, with no page errors or horizontal
overflow. Every browser API mutation is intercepted fictional data. Initial
browser-library setup failure and scrolled screenshot artifacts are retained;
final captures reset scroll before capture and use the existing local browser
libraries. No new server, build or package installation was used.

The production commands and assignment URL are published in REVIEWER-LINK.md.
The approved **dev** Person inspection/apply is still pending the existing Root
Operator route: no Docker permission and no Root-seat execution context in this
builder session. Exact source/hash and dev-only execution instructions were sent
to Root1872 and the coordinator. No actual Dipak account change or production
change is claimed.

## Migration and erasure repair — 16 October

The revised PostgreSQL journey requests deletion through
`ConversationApplication.request_deletion`, then runs the real local erasure
worker. It verifies deleted call state, cleared AI and gold payloads, retained
ids and unchanged provenance, including superseded saves. Three successive
judgements preserve every earlier row. Authenticated PUT/PATCH/DELETE attempts
on the save URL return 405 without changing history. These are service/API
guarantees; arbitrary privileged SQL is not guarded by a trigger on fresh schemas.

The direct migration classifier and `migration_schema_gate.check_operations`
accept 0094 as additive and lock-safe. The full command
`uv run python scripts/ci/migration_schema_gate.py --base-ref origin/main`
was attempted and refused with **governed staging schema evidence is missing**.
That is an incomplete release check, not a passing rehearsal. The existing
coordinator/operator retains the hosted governed-artifact/Docker rehearsal
before shipping. No new ship or account-change executor is started here.

Final focused repair checks: **13 passed / 21.60s** (10 PostgreSQL, 2 gold
contract unit tests, 1 backup-parity test). Empty downgrade/re-upgrade matches
the registered schema; retained, erased gold history refuses downgrade.
Ruff, migration mypy and the required HTTP import pass. The initial additional
rollback test used an Alembic context without the repository's naming convention
and failed its schema comparison; the final test supplies `target_metadata`,
matching `db/migrations/env.py`. Both logs are retained under
`/home/acdev/strikes/1801/gold-migration-repair-*20261016*.log`.
