# Scoped Studio admin HTTP: local implementation evidence

Date: 2026-09-07. Scope: local worktree implementation and tests only.

## Implemented boundary

The admin learning HTTP adapter consumes the shared `StudioAuthorization`
service for `catalog_read`, `catalog_write`, `catalog_publish`,
`learner_diagnose`, and `learning_review`. Other privileged actions retain the
existing named admin checks. No learner role, generic permission projection,
enrollment, platform permission mapping, or provider state is changed here.

Readiness and program lists require a server-resolved `StudioAccess`. Their SQL
filters the selected tenant and allowed program IDs before counts, ordering,
pagination, oldest-draft selection, and truncation calculations. Global content
is included only when the shared authorizer explicitly reports legacy global
read access; immutable global version filtering remains in place.

Program detail checks collection visibility and then authorizes the exact
persisted program. Publication resolves the real program from the selected
tenant's version row, checks the exact publication permission, and only then
reserves or replays the command ledger. A revoked assignment therefore cannot
recover an earlier publication response through the replay branch.

The admin host, Origin, ETag, idempotency, audit, and response-redaction gates
remain in place. `CapabilityDenied` is translated only into the existing
`admin_authorization_denied` HTTP 403 contract. No fallback is attempted, and
other authorization or infrastructure failures are not intercepted. The
learner diagnosis route remains absent because its canonical redacted query is
not implemented. A program assignment cannot authorize an unfiltered tenant
diagnosis or review action.

## Local validation

Command:

```text
.venv/Scripts/python.exe -m pytest tests/unit/http/test_admin_learning_routes.py tests/unit/http/test_admin_studio_capabilities.py tests/database/test_catalog.py -q
```

Result: **55 passed**. The only warning is the existing FastAPI/Starlette test
client deprecation warning.

The new relational HTTP tests use persisted grants, revocations, memberships,
programs, and versions in SQLite with foreign keys enabled. They prove:

- A program assignment filters out an older alphabetically earlier draft before
  a one-record collection limit and all readiness aggregates.
- Explicit tenant and program reads exclude global content and other tenants.
- A publication assignment does not imply catalog read or publication of a
  different program; revocation is checked before command replay.
- Owner/admin global immutable reads and support's restricted Studio permissions
  remain compatible with the existing role behavior.
- Program-scoped diagnosis/review assignments do not grant unfiltered access,
  corrections, or enrollment administration.
- Exact-action denial cannot fall back to a broader collection result; an
  unknown persisted actor retains the existing admin denial code without ledger,
  catalog, or audit calls.

The existing route tests continue to cover the admin-host/Origin boundary,
publication provenance, ETag and idempotency behavior, replay behavior,
correction supersession, and enrollment audit behavior. Existing direct catalog
read-model tests now supply explicit `StudioAccess` instead of a tenant UUID.

Ruff lint and formatting checks pass for the four changed Python files.
These SQLite tests are not PostgreSQL concurrency or migration evidence, and
the publication boundary tests isolate the domain publication service. They do
not claim end-to-end frontend admission or runtime activation. No remote write,
push, CI trigger, grant provisioning, or deployment was performed for this
checkpoint.

## 2026-09-08 local integration checkpoint

The separate authenticated self projection is `GET /v1/me/studio-access`.
Legacy `/v1/me` and `/v1/context` payloads and generic role permissions are
unchanged. The frontend validates all three identities together, retains exact
tenant/program descriptors separately, gates protected children until session
resolution, and restricts a scoped learner to Studio navigation and exact
program actions. All real `/v1/admin/*` routes retain the admin-host boundary.

The explicit local sandbox uses normal password login, the real selected tenant
and the real `ac_session` cookie. Its trusted native loopback transport supplies
the fixed admin Host; browser-forwarded identity and authority are not copied.
Both login forms wait for hydration and use POST. Native HTTP/HTTPS/NET/TLS
debug logging is refused, including cached startup masks, before session headers
reach the native transport. The managed launcher clears inherited debug and
bridge credentials and starts only the isolated learner/admin loopback pair.

Latest local checks: 59 Python admin/catalog boundary tests; 154 admin frontend
tests across eight files. The latter excludes the separate real-wire test that
binds port8000 while the managed local API is running; that test was verified
earlier with the port explicitly released. No live publication was performed.

The additional local avatar bridge permits only canonical original-avatar PUTs
and processed WebP reads. It validates exact loopback envelope, session, content
type, bounded byte length and actual SHA256; aborts stalled reads/transfers;
and never forwards native diagnostics, redirects or upstream upload bodies.
Default non-sandbox private reads retain their prior transport. Local learner
transport/bridge/privacy regression checks: 165 passed; learner typecheck and
targeted ESLint passed. The root independently reviewed this transport and
reported no Critical/Important finding. Backend intent/processing/ownership
remain canonical; the bridge does not authorize images by URL structure.

Visible disposable-profile Chrome proofs use real signed-in local API data:

- Video: actual3840×2160 decoding, 48 frames and advancing time; UI start,
  pause, seek, captions and fullscreen. The first check did not have a rate
  control. A second real run checked the newly available1.5× control and
  restored1×, with46 decoded frames and advancing time. CDP user-gesture
  button invocation is not native-input certification.
- Photo: synthetic input, zoom and normal Save produced a decoded512px WebP.
  Later read-only checks retained the user's current portrait. The original
  `04-retained-after-reload-desktop.png` is a premature skeleton capture and is
  **not acceptance evidence**. `05-retained-new-document-desktop.png` waits for
  a new document and fully loaded profile, then separately compares fresh
  profile-avatar asset/version before/after. The mobile editor Save control is
  within its844px viewport; no subsequent test replaced the current portrait.
- Arcade: all seven renderers received real server editorial feedback and
  advanced; mobile Next actions remained visible. Exit warns about unsaved
  rounds, without inventing loss of credits or course progress. A separate
  Chrome keyboard probe verified native ArrowDown radio selection, initial
  prompt focus, feedback focus and next-prompt focus. Dark/emerald styling uses
  the shared action token across hub and focused drill at1440/390; initial
  light/cobalt was restored through Settings and verified in a new document
  against the two exact appearance preference keys (read-only inspection).
- Course/module: real My Learning enrollment links produced before/after
  viewport screenshots at1440/390. Native chapter details expand/collapse,
  actual module/activity links navigate. The initial320px check used
  `innerWidth` and missed a15px overflow from the existing global body's320px
  minimum width with desktop scrollbars. A journey-only mobile ancestor rule
  (`body:has(.overview)`) removes that minimum without clipping content or
  altering unrelated routes. The corrected acceptance uses
  `documentElement.clientWidth`; the course and existing long module title now
  fit320px without horizontal overflow. `final-*-mobile320.png` are the accepted
  final captures; earlier `after-*-mobile320.png` are not the final overflow
  proof. No activity response or course-progress
  mutation was submitted. Light/cobalt after images are separately named
  `after-light-*`; existing dark after and all before images remain intact.

Screenshots are in `screenshots/local-video-playback-20260908`,
`screenshots/local-avatar-browser-20260908`, `screenshots/arcade-focus-20260908`
`screenshots/arcade-interactions-20260908`, `screenshots/arcade-theme-20260908`
and `screenshots/learning-path-20260908`. The earlier Arcade review
baseline is preserved. These are localhost development proofs, not deployed,
native-device, official scoring, wallet, or PostgreSQL-concurrency certification.
No push, CI trigger, deployment or remote state mutation was performed.

## 2026-09-08 practice engine client checkpoint

The separate `practice-engine-api.ts` transport implements the seven canonical
profile, progress and attempt operations with caller-owned idempotency keys.
It snapshots mutation payloads before awaiting, uses same-origin cookies,
no-store and redirect refusal, and bounds request/response bytes and elapsed
time. It does not generate rewards, issue automatic retries or infer streaks.
The existing editorial-preview client remains unchanged except for additive
strict public-content schema exports.

Strict response validation rejects hidden answer fields, stored/purchase/course
flag contradictions, mismatched pinned sets, duplicate/foreign prompt state,
inconsistent acknowledgement/completion, duplicate receipts, unpaired pending
timezone fields and impossible counts. These are wire-coherence checks, not
client reward policy. Fifty focused tests passed; learner typecheck and scoped
ESLint passed. This checkpoint validates the client contract only: the new
server engine and UI route were not yet activated or exercised by this check.

## 2026-09-08 activated practice engine browser proof

After the managed local migration and API activation, the real disposable
Chrome session passed `local-practice-engine-browser-proof.mjs`. The script
verified the synthetic learner and exact academy before each write, then used
normal UI actions to save the initially absent Asia/Kolkata practice timezone,
start two `next-move` attempts, submit six responses and acknowledge six feedback
results. Existing avatar/version and the two appearance preferences were
unchanged. No other account setup or service mutation was performed.

Fresh authenticated GETs confirmed no award before completion. The first
completion returned 10 credits and 30 XP, matching the wallet delta. A new
document restored saved feedback and the next unacknowledged prompt; reopening
the completed attempt changed neither its state nor the wallet. Completing a
second same-family attempt added no receipt or wallet award. Purchase and
course-progress flags remained false. No external request was observed.

Eighteen actual viewport captures and the bounded assertion results are in
`screenshots/practice-engine-2026-09-07T20-05-33-480Z/` (`proof.json`). All
1440/390/320 captures passed document client-width and prompt-body overflow
checks; active buttons remained in their viewport. Representative start,
choice, feedback, completion and no-reward replay images were visually reviewed.
The script uses CDP user-gesture DOM activation, not native-input certification.

Two earlier invocations stopped before any practice write because a new Chrome
target briefly exposed a complete `about:blank` document. The script now waits
for the exact learner origin/path as well as document readiness before identity
checks; only the completed run above is acceptance evidence. Recovery-component
regressions independently reran with 25 tests passing. No push, CI trigger,
deployment, purchased-credit activation or official scoring was performed.

## 2026-09-08 bounded follow-up status

The shared SessionStep footer correction centered the completed desktop action.
The first hub follow-up exposed the global body's 320px minimum when a desktop
scrollbar left 305px. Root corrected that single shared rule and removed the
earlier Learning Journey exception. Actual hub screenshots then fit320px;
read-only course, long module and loaded profile regressions independently
reported client305/scroll305/body minimum0. Their captures and passing result
are in `screenshots/shared-body-320-2026-09-07T20-19-37-254Z/`.

The follow-up used trusted native CDP mouse input to expand recent rewards,
start one gaps attempt and choose a radio option; native ArrowDown changed the
choice. A subsequent Enter-driver omission was corrected. Native X/Escape then
exposed an actual focus bug: the dialog closed in the same document but left
focus on BODY, while Keep practising returned it correctly. Root fixed the
cancel path to close natively and restore focus. A fresh completed native
response/acknowledgement proof after that fix is **not yet established**.

Partial captures in `screenshots/practice-followup-2026-09-07T20-17-10-083Z/`
show centered completion, wallet/rhythm, temporary dark CSS and the truthful
exit warning; that directory is not a passing end-to-end run. Dark/reduced-motion
browser emulation and the temporary DOM theme selector were restored without
writing appearance preferences. On resumption, read-only progress showed that
concurrent visible-browser interaction had completed the original gaps attempt
and created another. The script did not perform or claim that completion and
stopped without touching the newer unanswered attempt. The original portrait
and saved appearance were not modified.
