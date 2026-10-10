# AUT-1678 implementation evidence

This strike starts at `b6033ad3d3d55f928547e2901785e6e239357bdc`. Its binding definition is the owner’s final Sales Xray structure dated 2026-10-09, §§3, 5, 6, 10 and 12. The module is a provisional read model, not the completed Coaching capability.

## Current behavior

### Call-specific slice (11 Oct owner request)

`GET /v1/me/coaching/calls/{submission_id}` is API ready. It uses the same private account/workspace admission and narrows the retained library to exactly the signed-in person's selected call. Admin and manager report access cannot bypass Coaching privacy. Each request reads exactly one authorized report, then builds one focus, supporting call moments, a structured lesson, one practice and a next-call mission. The across-call learner focus is not changed. One call suffices; sparse or clean reports have an explicitly labeled general practice when no source recommendation exists, rather than an unsupported weakness or a "not enough evidence" dead end. Withheld evidence remains unavailable.

The derived result has a bounded two-minute process cache keyed by person, tenant, submission, creation time and the freshly authorized report envelope. Membership, source ownership, retention, revocation and withholding are checked before every cache lookup. Changed report/source/withholding data changes the key. Responses and errors remain `private, no-store`; the cache never grants access. No canonical state, jobs, audit history, providers or credits are written by this read.

Local API proof: 74 Coaching unit cases and 6 disposable PostgreSQL cases passed, including exact selected-call reads, admin exclusion, cached withholding and revocation. Ruff and mypy pass. New coverage is in `test_call.py` and `test_call_coaching_postgresql.py`.

`/coaching?call=<submission_id>` renders the call's four narrative pillars and links back to its Report and My coaching. Normal hosting loads the entire result on the server in one request to the fixed deployment API origin, forwarding only the request's account cookies and surface host; there is no shared page/data cache, redirect forwarding or credential logging. The already-authorized server result renders before client account bootstrap and prevents a duplicate Coaching fetch during hydration. A later account/workspace/session change rejects and clears it; a response's opaque session ID is bound separately from the reusable derived projection. Static preview skips request-only server functions and uses the same single authenticated client read. Both modes degrade missing routes to a corner recovery card; optional display fields get safe defaults, while source/mission/identity mismatches fail closed. Invalid call links never fall through to another coaching read.

Call UI proof: 25 focused Vitest cases, ESLint, TypeScript and the static-preview production export pass. Fictional browser proof at 390/1440 in light/dark verifies four pillars, one server read, zero Coaching refetches during hydration, cleared skeletons, Devanagari fonts, no overflow/eager audio/page errors, and source/corner retries. All local server/browser processes are stopped. Shared shell/Report files are untouched. This is not authenticated deployed owner verification.

### Anonymous Team coaching

`GET /v1/me/coaching/team` and `/coaching?view=team` show anonymous counts of source-linked report suggestions in the fixed eight-skill taxonomy, plus an explicit unclassified category for legacy suggestions. Current organisation owner/admin authority is re-read from active membership before reading team reports. Personal accounts and ordinary members are denied; a role downgrade takes effect on the next read. Each retained report still passes source, retention and withholding checks, so a new report is included when the view is read again. Duplicate uploads count once per owner/source and the recent 40-call bound is disclosed. A qualitative report state alone never counts as a mistake, success or mastery.

The aggregate response has no rep names/IDs, call IDs/links, quotes, focus text, root causes or missions. Its person/session identifiers belong only to the requesting account. The frontend ignores source-supplied labels and uses the controlled taxonomy. This slice does not activate coach duties, named rep Coaching, assignments or sharing: those require canonical, revocable sharing/grant records and review. Owners/admins still cannot read another rep's private call Coaching through the own-call API.

Team proof: 77 unit cases, the earlier 6 PostgreSQL cases plus the new Team PostgreSQL case, and 29 focused Vitest cases pass. The new database case checks owner/admin aggregates, member denial, no teammate private Coaching access, source withholding and immediate role downgrade. Shared transcript revisions correctly share withholding even across recordings; the fictional test honours that canonical privacy rule. Ruff/mypy, ESLint/TypeScript and the static export pass. Final fictional Call + Team browser proof covers both views at 390/1440 light/dark, one server read, no hydration refetch, no overflow/eager audio/page errors and call source/corner retry.

`GET /v1/me/coaching` uses the signed-in account/workspace on the exact Sales Xray host. It accepts no person, workspace or call selector. Coaching is open under AUT-1678 to Personal and human organisation memberships; operations and processing identities are excluded. It does not inspect payment providers, charge credits, call AI, write progress, or renew claims. Responses and errors are private and uncached.

Own retained acquisition history is read through the existing call-library scope and `AcquisitionReports.report`. An organisation administrator’s teammate access never becomes personal learner history. Canonical source, proof, report, ownership, live membership, retention and withholding checks remain authoritative. Withheld references cannot produce playable Coaching evidence.

The adapter connects a report’s first next-call mission to an assessed skill only when its exact evidence uniquely identifies one supported report dimension. Ambiguous prose does not establish that link. Older C5 reports often omit dimension evidence: their source-bound improvements, missed opportunities, objection analysis or closing analysis can still supply a provisional call suggestion and mission. It is labeled as an unlinked report suggestion, never a recurring assessed-skill weakness. The existing overview mission, replacement behavior and practice are retained where available; otherwise the learner rehearses and tries the report’s own suggested change. No `story`, new prompt, provider call or Coaching table is required for this read. Unknown, conflicted, inapplicable or unsupported dimensions do not become failures. Duplicate source uploads count once. Comparable assessed-skill suggestions require a validated durable C5 evaluator receipt: recipe, prompt, model, profile, qualitative pack, language and repair/benchmark boundaries are retained. Legacy/recovered/unlinked reports and unclassified suggestions stay separate.

The learner replay keeps one supported mission across dates and minor new findings. The latest 40 retained calls bound each read, and truncation is disclosed. This is **not durable mission persistence**: loss of retained history can change the replay result. Source-bound call/skill/mission contracts reject crossed source identity and duplicate skills.

The `/coaching` page uses the existing operational page kit and semantic tokens, Devanagari-capable fonts, skeletons, progressive disclosure, and a corner retry card. Evidence loads only on click, seeks to its source timestamp, stops at the excerpt end, and pauses other Coaching players. A workspace/session change remounts the learner view; stale identity responses are rejected. The six narrative pillars expose one practice, a complete structured text lesson, one mission, unknown progress and a provisional path. Agreement/reflection saving is explicitly unavailable.

The `/coaching?focus=<skill>` report destination accepts only the eight supported skill identifiers. It adds the report's context without changing the active mission, reading another person, or creating an unsupported skill diagnosis. Client query reading sits under Suspense so both the normal standalone app and CI's static preview export remain valid. A route loading boundary declares `aria-busy` and disappears when the account read completes. Shared sidebar and Report links belong to Strikes A and B.

The lesson source is the approved owner specification’s impact framework and own-call comparison/practice principles. `dipak_report_v1.json` is an unapproved candidate and is not represented as an approved knowledge base. These lessons do not claim Dipak media provenance. Catalogue contracts admit only revision-bound reviewed tags, confirmed Dipak provenance and valid durations; unreviewed proposals are unusable. The metadata review also binds the exact item and full proposed tags by hash; changing tags, rationale, provenance, duration or title requires a new attributable review. Approval boundaries revalidate copied/constructed models and reject a coerced creator flag.

`python -m ac_platform.coaching.index_import <export.db> <new-private-package.json>` reads an owner-exported SQLite index in read-only mode. It restricts metadata triage to the requested categories and exported aliases, excludes documents/directories, and emits a private, noncanonical review package without overwriting an earlier package. The metadata snapshot hash is not a content revision. Creator, duration, skill and gap tags stay unknown; a folder named Dipak cannot confirm the creator. No content is fetched and no provider is called. The first private export yielded five media candidates, none eligible for recommendation. AI content tagging and a persisted review queue are not active.

## Media and Academy foundation

`media.py` defines source identity/revision/hash, duration, provenance and permission references; timestamped Hindi/Marathi/English transcript spans; provider approval/cost references; transcript quality review; proposed skill/topic/gap tags; and immutable, attributable approval/rejection receipts. A review binds the full proposal and timestamped transcript hash. Changed source, text, timestamps or tags require a fresh review. Clips contain contiguous existing spans and exact transcript excerpts. Invalid, rejected or unreviewed segments never become recommendations. The selector returns at most three specific, non-overlapping matches, with each review's relevance explanation and takeaways; an unmatched/unclassified focus returns no media and retains the text lesson.

Preview planning takes an explicitly resolved entitlement/credits allowance and durable usage revision. It returns a full, limited or locked source window without consuming usage or inspecting a payment provider. Internal/free/unlimited full access is supplied by the Coaching entitlement. The future server stream must enforce the window and reserve durable usage; a client player cannot enforce access by itself. No preview policy is invented, no paywall is activated, and no video/audio bytes are stored by these contracts.

`academy.py` resolves an explicitly reviewed program/version/module/activity mapping through the existing public `GET /v1/programs/{slug}` response contract. It validates membership and version before producing the actual Academy course/lesson paths. Missing routes, changed versions and missing modules/activities return an unavailable result. It never guesses a course by title or grants enrollment/progress. The configured Academy read helper and actual reviewed mappings are still needed for live recommendations.

These are tested domain contracts, not a persistent media library/review queue or live playback capability. The exported catalogue contains only two Dipak-category media items and three broad Sales items; it cannot supply the requested 3–5 Dipak proof batch. Content, streaming authorization, approved transcription route and canonical storage remain activation requirements.

## Proof

Focused tests live in `tests/unit/coaching/`, `tests/database/test_coaching_postgresql.py` and `apps/sales-xray-web/app/coaching/*.test.*`. They cover uncertainty, focus stability, duplicated sources, explicit version boundaries, ambiguous source links, review provenance, private cookie/host/selector access, teammate isolation, withholding/revocation, workspace changes and audio recovery. Database proof uses disposable schemas from `AC_TEST_DATABASE_URL`; all committed calls and quotes are fictional. Ruff, mypy, Prettier, ESLint, TypeScript and focused pytest/Vitest are the local checks. CI supplies full suites and production compilation.

The follow-up local proof has 61 Coaching unit tests, 4 PostgreSQL cases and 13 Vitest tests. The exact `AC_SALES_XRAY_STATIC_PREVIEW=1` production build passes through `ac-heavy`, including `/coaching`. Final fictional browser proof at 390/1440 light/dark verifies report-focus context, cleared loading, no overflow/eager audio/page errors and source/corner retry; browser/server are closed. Media boundaries revalidate copied/constructed inputs, reject negative usage and nonboolean access flags, and require aware review timestamps. This is not a real media transcription or authenticated deployed owner-history proof.

Private strike notes, offline corpus counts and fictional local browser artifacts live outside Git at `/home/acdev/strikes/1678/`. Corpus content must never enter evidence, Git, GitHub or chat. Offline adaptation is not an account-authorized deployed journey, a provider test, or a mastery validation.

## Remaining activation requirements

- Shared migration/model ownership is held by another strike (see the current holder in `NOTES.md`; #414 was followed by #421). Durable learner/skill profiles, focus revisions, diagnosis revisions, missions, practice history, relevant opportunity observations, skill evidence links, reflection/feedback and media review receipts need dedicated canonical tables and superseding audit history. Analytics and unrelated domain tables cannot substitute.
- Current report labels are not relevant-opportunity success verdicts or root-cause diagnoses. No approved threshold rules were supplied for mastery/regression. These stay unknown until reviewed comparable behavior evidence and rules exist; content completion, call count and dates cannot advance mastery.
- Strike A owns the sidebar entry. This follow-up does not edit the shell.
- The requested index export is available privately, but contains no Content library entries, content revisions, durations or verified creator provenance. Content review, approved tagging and canonical catalogue storage remain necessary; metadata triage never creates a recommendation.
- Strike A's shared page kit and `app/ui/sx-tokens.css` exist at this continuation's base. This strike reuses them without editing them. The Windows AC Orchestra skill and authorized normal Pro browser remain unavailable on this server; installed browser automation is metered and excluded by the subscription-only rule. Bounded local work continues.

The initial private read-only slice merged in #423 on 2026-10-10. This follow-up preserves that access rule and repairs legacy report display. This session does not merge, deploy, read secrets, or mutate staging/production. After the approved merge and normal ui-lane sync, open `/coaching` while signed in; inspect the evidence, lesson and mission, then change workspace. Full strike acceptance still needs the requirements above.

Owner placeholder-media handoff (11 Oct): `dataset.py` reads optional, read-only
`/home/acdev/datasets/synthetic-v1/coaching-media/<topic_id>.json` exports under
`ac.sales-xray.coaching-dataset-topic/1`. The topic ID is stable for replacement
by Dipak's real recording later; this version accepts only explicitly labelled
neutral placeholders. It does not generate speech or alter the dataset/spool.
The owner script remains the provenance reference; the neutral narrator must
never be identified as Dipak's recorded voice.

Each normalized export carries the existing `MediaTranscript` (exact source
hash/revision/duration, timestamped spans, route/activation/cost references and
an attributable quality review), proposals and exactly their current human
`SegmentReview` records. A changed proposal or transcript invalidates approval.
`Narration` supplies a safe relative MP3 path inside this root, exact SHA-256,
byte count (maximum 20 MiB), duration and `verified` timing receipt. Pending,
failed, missing or unreviewed audio produces no clip recommendation. An attributable `PresentationReview` approves the exact whole export hash
(excluding the review itself), binding narration receipts, current tag reviews
and slide content. Missing/rejected or changed presentation approval remains
unavailable. A slide references a retained transcript segment and contains title/bullets; only slides
from the selected segment IDs are returned. JSON files are bounded at 512 KiB
and the read at 100 topics. Parsed topic snapshots use a bounded 100-entry
cache keyed by device/inode/size/mtime/ctime; every read checks current file
revisions and narration existence again, so a replaced/revoked export is not
served from an old snapshot. Symlink JSONs and escaping media paths are excluded.
This export is a reviewed source handoff, not an invented canonical queue or a
substitute for future database history. Exporters must retain review history
and publish immutable media bytes and atomic current topic snapshots.

Call and My Coaching include up to three exact skill/gap matches in the same
account read. Malformed/missing files leave the structured text lesson intact;
no dataset path or arbitrary media URL reaches the browser. Source playback
uses `/v1/me/coaching/media/<topic>/<transcript_hash>/<current_review_id>/source`,
with fresh current Sales Xray account/workspace admission and exact current
review checks. Source bytes are hashed before the first byte and streamed from
the same open descriptor; single byte ranges are supported. Replaced exports,
revoked reviews and wrong hashes cannot reuse an old route. Responses are
private/no-store. This current route exposes only the explicit
`AUT-1678-open-access` Coaching entitlement. Limited playback must wait for
server-enforced durable usage/credits policy; browser segment pausing is only
navigation, never access control.

The player marks `Placeholder · neutral narration`, says why the reviewed cut
fits, supports slide navigation, exposes transcript/takeaways, fetches audio
only on Play, stops at the selected cut, pauses other Coaching audio and offers
Try again on errors. It does not infer mission completion from listening.
Actual playback proof awaits Strike F's verified artifacts; local test media
and browser fixtures are deliberately fictional. No paid API, deployed source
or database change is introduced by this adapter.

Current placeholder-slice evidence: 93 Coaching unit cases and the three
focused PostgreSQL Call/Media cases pass (96 together); the final Media case
also proves My coaching returns clips and rejects changed reviews/bytes. Across
completed slices there are eight focused PostgreSQL cases. All 33 Coaching
Vitest cases, ruff/mypy, ESLint/TypeScript, Prettier and static-preview production
export pass. Final fictional Call/Team proofs at 390/1440 light/dark verify
placeholder labels, slide navigation, source retry, no eager audio, exactly one
server Coaching read, no hydration refetch, no overflow/page errors and corner
retry. Browser/server processes are closed. The actual placeholder directory is
absent; these proofs do not certify Dipak content, source timing or deployment.
