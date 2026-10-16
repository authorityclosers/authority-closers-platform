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
It rejects UPDATE/DELETE of gold history except the canonical call erasure:
all content is nulled, `erased_at` is set, and provenance stays unchanged.
An `AFTER UPDATE OF erased_at` trigger on `conversation_pointer_reviews` erases
every gold version for that call in the same canonical application transaction.
No scoring or `pointer_review*` source file is modified. This exact hook was
announced to the Report session through its INBOX; an optional application helper
is also available. Backup/restore parity v61 includes all three tables.

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
