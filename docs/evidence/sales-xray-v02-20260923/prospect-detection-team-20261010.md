# Strike B: detected prospects and organisation customer scope

Source: binding final-xray-structure-2026-10-09.md (section 2), AUT-1677,
AUT-1588 / AUT-1590 / AUT-1592, owner Pulse order AUT-1701. PR #414 merged as
4885aaff4bb84b0699cbb030c2bbfed835fddd3f and is incorporated at 54ea7fa.
No new tables, migrations, dependencies or other-strike files were changed.

## Implemented

`ProspectStore.ensure_detected` verifies retained canonical C2/C5 (including
retained C5 recovery), source binding, an evidenced sales purpose and a prospect
role. Under the exclusive recording fence it creates one distinct Detected
customer and a detected call membership. Concurrent runs and retries reuse the
active membership; matching names/companies never merge people. Explicit human
unlinking suppresses subsequent automatic recreation. Internal, unanalysed,
unclear and privacy-withheld-purpose calls create no detected customer.

Existing C5 company/industry/role/team-size facts retain literal text and native
quote/time. Missing names remain Unknown; the row label says name was not heard.
Phone/email remain unknown until a person types them. Separate profile extraction
can append supported values through the existing writer. Detected name updates
cannot replace a person's name edit. No completed C5 payload is changed.

The private, same-origin POST `/calls/{id}/detect` supplies a Report-view fallback.
The six-pillar Deal control invokes it and reads the resulting canonical state.
A Detected link is not called confirmed. One explicit tap posts the expected
revision to `/{prospect_id}/confirm`; the server records confirmation metadata
and an audit event. Repeated confirmation is a no-op. Stale first confirmation
fails closed. Confirmation does not turn every AI value into a locked person
edit. The Prospect detail also has this action. Clients verify the persisted
receipt and reload; failures use the existing corner notice with an explicit retry.

Changed field evidence comes from a source-readable, earlier append-only row
that the current row supersedes. Withholding the previous source removes that
relation. Person locks still win; readable later differing candidates remain
Contradiction evidence. No historical rows are overwritten.

Active organisation owner/admin/member/learner identities share customer
records and may explicitly link their own retained call to an existing customer.
Personal and operations workspaces retain their prior scope. Call/audio/quote
rights and owner-only person editing remain governed by the existing checks.
Shared reads therefore withhold inaccessible call facts instead of granting
new source access. `can_edit`/`can_confirm` control the interface. Workspace
switching clears the previous customer's display and cancels pending reads.
Call counts and last-call labels explicitly describe visible history; unavailable
colleague calls are not described as a customer having no calls.

## Verification

- 17 focused disposable-PostgreSQL regressions passed across detection, store,
  library, field history and privacy safety. Four final detection cases pass
  after the last source/confirmation adjustments: concurrent creation, distinct
  customers, confirmation CAS/idempotency/unlink, team linking/person locks,
  bounded adapter writing without C5 changes, privacy and Changed history.
- The actual merged registry and writer are used by the adapter integration
  test. Its broker is fictional: off dispatches nothing; one admitted synthetic
  response appends an Observed field. Zero real provider requests.
- 155 focused frontend tests passed, including confirmation, shared read-only
  controls, six sections, source/lock rendering and workspace-switch isolation.
  Additional confirmation receipt validation is checked separately. App
  typecheck, changed-file ESLint, Python ruff and strict module mypy pass.
- The complete CI set is green at 54ea7fa, including compiled acquisition,
  Report playback/relogin and all Python shards. This integration commit still
  needs latest-head CI before watchdog eligibility.

## Remaining boundary

Rollover: PR #420 merged at 08:52:58 UTC as 73614f5. The carried integration is
e4abe94 on a fresh gate-started branch, in nondraft PR #427. Latest-main focused
reruns pass: 156 frontend tests, four detection PostgreSQL cases and app
typecheck. Report and Prospect browser proofs also pass at 390/1440 in light/dark
after the shell update; fictional screenshots are in shots/report-latest-main
and shots/prospects-latest-main under the strike folder. No page errors,
external/API requests or overflow. Hosted verification returned a Cloudflare
Access login redirect; no authorized browser session or bypass is used.
The visible-history wording correction passes the nine Prospect screen tests
and changed-file ESLint. This receipt supplements the earlier merged-head proof.

The view-time fallback is not universal post-C5 dispatch. Strike C PR #421 owns
`reporting_pipeline.py`, `inference_worker.py` and processing/provider scheduling.
It also owns the charging path. Those files were inspected, not edited.
Universal automatic detection and profile job/provider/settings activation need
that owner's hook. The alternative of write-on-GET or an implicit ORM listener
would hide canonical writes and complicate source/erasure fences; neither was
introduced. A separate bounded `prospect-profile/1` adapter and source-fenced
`ensure_detected` entry are available for the hook. Provider admission, durable
job state and the end-user on/off/cap setting remain integration work.

No production/staging data or servers were changed, no deployments or manual
merges were performed, and no real calls were sent to a new provider. The
retained corpus Report proof is in report-pillars-screen-20261010.md; new
profile persistence/detection proof is fictional and local until release.

## Dev check after authorized merge

Open an authenticated completed, evidenced sales call. In Where the Deal Stands,
expand the prospect control: it should say Detected until Confirm prospect is
pressed. Reload and verify the same customer ID, confirmed status and retained
quotes. Open Prospect's Information, inspect all six sections and a source quote.
Type a field edit; a later conflicting readable call must preserve its lock.
Another active member of the organisation can find that customer and link their
own call. Private colleague calls/quotes must stay unavailable; shared customer
pages must withhold owner-only edit controls. Switch workspace while loading:
the old customer and its drafts/quotes must disappear immediately.
