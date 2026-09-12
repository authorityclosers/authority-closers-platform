# Studio lesson video approval — local implementation

Date: 2026-09-09. Implementation tree: `codex/local-staging-dev-bridge`.
This work is **not** in Sol's immutable release candidate
`afab2fed7dcd68dd4eef8d1fdb7ccf330957643d`. No staging/production acceptance is
claimed for it. The managed localhost API was restarted successfully, preserving
existing accounts/content and migrating the disposable sandbox from 0023 to 0024.

## Behavior implemented

- Course-scoped ready-video library: the caller's uploads or videos already
  approved for the exact course. Tenant-wide authority does not reveal unrelated
  instructors' private uploads. Filtering precedes bounded cursor pagination.
- Coach/Admin HTTP routes for library, current video and explicit approval.
  Normal opaque session/context authentication; fresh persisted Studio grants;
  commit before successful response; no provider/object/playback URL projection.
- Existing binding history is reused, with expected-current-binding conflicts,
  same-key receipts (including historical superseded/revoked receipts), locked
  source eligibility and same-transaction audit. Original actor permissions stay
  unchanged. Only an exact active internal invocation authorizes the scoped binder.
- Reserved technical demonstration asset OR version identities cannot be chosen
  or replaced through this ordinary course workflow. Drafts are not implicitly
  published. Provider enablement and content review are not bypassed.
- Shared Coach/Admin editor mounts the video controls before the content form for
  saved VIDEO activities. Loading, empty, draft/read-only, denied, conflict,
  approval and ambiguous-result states use existing tokens and ActionButton.
- Unconfirmed approvals lock editor navigation and retain exact request/key in
  browser memory only. Current-state GET never acts as a command receipt. Recovery
  identity is person/tenant/session, separate from authority-sensitive remounts;
  changing assignments does not lose the request. Fresh access denial hides all
  private rendered metadata. Different verified identity/session/tenant clears
  recovery; normal logout fully navigates. A transient failed session read is not
  treated as proof of logout.
- Migration 0024 adds a scoped latest-upload-intent index without changing history.

## Executed verification

| Check | Result / actual scope |
| --- | --- |
| Four focused Python unit/relational/HTTP files | 192 passed, 26.24s |
| Existing media service, public/staging film imports, activity-delivery authorization | 171 passed, 51.49s |
| Studio library + selection PostgreSQL files | 23 passed, 19.71s; required loopback PG, random migrated disposable schemas |
| Real concurrent approval writers | Observed PostgreSQL blocking; different commands conflict, exact retry returns one binding and one audit |
| Full composed app on PostgreSQL | Real opaque cookie issued through canonical identity service, normal context selection, scoped learner role, committed approval read from fresh DB session, same-key retry; no dependency overrides |
| Latest-intent query plan | Natural planner uses scoped index with 2,500 historical synthetic intents; no forced planner settings |
| Video client/component | 47 passed; response validation, privacy, pagination, late promises, exact retry, unload protection |
| Real course-editor component integration | 50 passed; includes navigation locks and permission removal/restoration retaining the second VIDEO's exact request |
| Development proxy | 87 passed; exact video routes, UUIDs, bounded unique query keys; unrelated legacy media routes remain unavailable |
| Existing Coach routing and local transport/privacy regressions | 46 passed |
| Admin + Coach TypeScript | Both passed |
| Focused Python mypy / Ruff / format | Passed |
| Focused frontend ESLint / Prettier | Passed; lint explicitly targets the Admin app directory for Next's link rule while including shared files |

The PostgreSQL tests create synthetic metadata, not uploaded playable objects.
They prove binding/auth/transaction behavior, **not** processing or playback.
The cookie test provisions an isolated verified test person and issues the session
canonically; it does not exercise an external email/OAuth provider.

Independent review identified and then verified fixes for cached metadata after
access denial and capability-sensitive recovery clearing. No remaining
Critical/Important findings in that review scope. Backend review requested 37
additional source/technical-identity write-path regressions; all pass.

## Browser and remaining release work

Initial real Chrome inspection found only one accessible synthetic draft with one
REFLECTION activity and incomplete content provenance. It had no VIDEO activity,
so no published picker/save visual proof could honestly be captured. Existing
editor at 390x844 and 1440x1000 hydrated with no overflow or console/page errors.
Evidence: `.tmp/local-platform/coach-video-picker-j1gpbui_/smallproof.json` and the
two screenshots in that directory. No mutation in this baseline.

A subsequent explicitly scoped local check added exactly one optional VIDEO via
normal visible Studio controls to that synthetic draft: `Local video approval UI
check`, resource `b9d8806f-c7b4-4920-9cf7-b91d6557bd83`. Its instructions identify it
as synthetic local test content, not Dipak's content. Existing modules/activity
were preserved; exactly one authoring POST, no publication/provenance/binding
mutation. The new draft video panel rendered at 390x844 and 1440x1000 with no
horizontal overflow, console/page errors or blocked requests. Root visually
inspected both screenshots. The owned Chrome tab was left open for the user.
Evidence: `.tmp/local-platform/coach-video-picker-local-vhwyyak_/smallproof.json`
and `coach-video-picker-local-{390x844,1440x1000}-draft.png`. This proves the real
draft guidance and integration, **not** the published picker or approval flow.

An additional real same-origin browser read caught a missing development proxy
allowlist: both new video endpoints returned 403 before reaching the API. The
shared Admin/Coach proxy was corrected with exact route/method matching and a
bounded unique `limit`/`after` query contract. No broad route or privilege bypass
was introduced. Rechecking through the actual authenticated Coach browser then
returned HTTP 200 for both endpoints: zero ready library choices; the created
activity returned `version_status: draft` and a null binding. The original 403
and corrected 200 observations are both preserved in that same JSON evidence.

Still required: published-course picker/save browser acceptance with real ready
instructional media; normal upload/processing/provider activation; source preview;
the complete draft content-review/publication workflow; comprehensive player and
cross-device acceptance; independent exact-artifact staging/prod rollout and Drive
release evidence. Current technical-film delivery remains a separate capability.

Recovery is same-document only, not durable across browser termination. This slice
does not claim that every browser/proxy failure can be resolved without restoring
authority or that historical activities outside the editor's bounded version list
already have a standalone recovery screen.

## Course-builder usability iteration (2026-09-09, localhost only)

Shared Coach/Admin lesson creation now uses one compact, keyboard-operable format
disclosure with the existing five canonical kinds, reusable LearningSymbol SVGs
and semantic theme tokens. The title is visibly required. Confirmed module saves
offer an explicit next step to add the first/another lesson; no implicit write is
performed. Outline icons identify lesson formats. Save feedback distinguishes
confirmed saves from subsequent unsaved edits without hiding recovery messages.
Format and required-state controls remain locked while creation is unresolved.
Course-list and editor boundaries use learner/coach-facing wording while retaining
the existing access, review, publication and video authorization gates.

Verification: all 437 Admin app tests passed (17 files, including 53 course-editor
tests); Admin and Coach TypeScript checks passed; scoped ESLint and git diff
whitespace checks passed. The root-directory ESLint invocation emitted its
Pages-directory configuration warning, with no lint violations. Independent
review found the mutable required checkbox during unresolved creation; the fix
and regression were re-reviewed, with no remaining Critical/Important findings
in this scope.

Actual Coach browser checks covered desktop 1440px, mobile 390px and 320px,
light/dark theme, native disclosure Enter behavior, Tab reaching the title, and
radio keyboard focus. No horizontal overflow was measured. Root inspected the
candidate screenshots. This pass performed no course-save, upload or publication
mutation. Admin behavior was covered by shared-code tests/typechecking, not a
separate signed-in Admin browser walkthrough in this iteration.

Local screenshots and measured JSON:
`.tmp/local-platform/new/coach-creation-ux-20260909-qa1/candidate-final-*`.
These are local evidence, not uploaded Drive release evidence. These uncommitted
changes are excluded from release candidate
`452ee2923b27edcec00da7816d699b162bf65450`. Full new-course creation, real video
upload/processing, content review/publication and end-to-end live acceptance remain
required; this iteration does not claim those workflows are finished.
