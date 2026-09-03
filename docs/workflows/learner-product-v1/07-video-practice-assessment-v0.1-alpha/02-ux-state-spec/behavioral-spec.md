# Behavioral specification

Status: `spec_ready` for a docs-only design handoff; media, assessment,
reviewer, and runtime evidence remain gated.
Stable screen IDs in this document must match the state matrix, PlantUML source,
asset manifest, and any later implementation.

Flow IDs used across the package: `FLOW-LL-01` module roadmap and sequence;
`FLOW-LL-02` video/captions/transcript/resume; `FLOW-LL-03` knowledge checks
and quiz/test; `FLOW-LL-04` reflection/evidence/review/improve; and
`FLOW-LL-05` PWA/install/update/offline/auth recovery.

## State layers

Render the intersection of three different facts; never collapse them into a
single spinner, badge, or inferred stage:

1. **Presentation state** — loading, playing, paused, drawer open, focus,
   orientation, reduced motion, install/update banner.
2. **Canonical business state** — authorization, activity order, media policy,
   watched-interval evidence, authored answer submission, draft revision,
   evidence submission, assigned-reviewer result, completion, and next action.
3. **Recovery/operator state** — offline/stale, retryable/terminal error,
   session expiry, storage failure, conflict, provider/gate hold, and
   reconciliation.

Analytics events are downstream observations. They never create or mutate a
canonical state in this package.

## Screen and route contract

| Screen ID | Surface | Route | Owner | Primary purpose |
| --- | --- | --- | --- | --- |
| `LL-MOD-01` | Module roadmap | `/learn/{programSlug}/module/{moduleId}` | learning projection | orient, resume, and expose safe prerequisite actions |
| `LL-VID-01` | Video viewer | `/activity/{activityId}` | media policy + activity service | play approved media and show honest playback/resume states |
| `LL-CAP-01` | Captions/transcript | `/activity/{activityId}` | media policy/content | toggle approved captions or transcript without inventing content |
| `LL-KC-01` | In-video knowledge check | `/activity/{activityId}` | authored activity schema | answer one cue-bound check with deterministic feedback |
| `LL-QZT-01` | Quiz/test | `/activity/{activityId}/assessment` | authored activity schema | complete an authored low-typing assessment and submit online |
| `LL-REF-01` | Reflection | `/activity/{activityId}` | draft service | write and save a self-scoped reflection |
| `LL-IMP-01` | Implementation evidence | `/activity/{activityId}` | evidence service | record supported evidence without real-world certainty |
| `LL-REV-01` | Human review | `/activity/{activityId}` | assigned-reviewer policy | wait for or read an explicitly assigned human result |
| `LL-IMPR-01` | Improve/retry | `/activity/{activityId}` | learning projection + evidence service | choose one next behavior or retry an authorized task |
| `LL-PWA-01` | PWA/install/update/offline | `/offline` or shell overlay | browser/PWA shell | explain install, update, stale, and offline boundaries |
| `LL-AUTH-01` | Auth recovery | `/session-expired` | identity/session service | reauthenticate and return to an intended safe route |

## Primary transition path

`LL-MOD-01 ready` → `LL-VID-01 ready/playing` → optional `LL-KC-01 feedback` →
`LL-QZT-01 submitted` → `LL-REF-01 saved` → `LL-IMP-01 submitted` →
`LL-REV-01 awaiting_review/review_saved` → `LL-IMPR-01 saved` → canonical
`next_authorized_task` or a bounded completion summary.

Any transition can branch to `loading`, `locked`, `permission_denied`,
`retryable_error`, `terminal_error`, `offline_or_stale`, or
`unauthorized_or_expired` as defined in the matrix. A stage label never grants
access and a local interaction never marks canonical completion.

## Module roadmap and navigation — `LL-MOD-01`

- Read the pinned program/module version and ordered activity projection from
  the server. Show safe titles, current/complete/locked state, prerequisite
  reason, and the next authorized action.
- Desktop uses a concise adjacent outline. Compact layouts use a labelled
  `View module path` disclosure or bottom sheet. The full outline follows the
  main task in DOM order when opened.
- A direct URL to a locked or unpublished activity fails closed, retains safe
  module context, and names the prerequisite action. It never exposes a
  protected activity payload.
- Modules 2–4 can remain topology-only/locked in v0.1. Do not fill empty
  modules with placeholder lessons or claim future breadth.
- There is one semantic ordered list. Visual summaries may repeat it but are
  presentation-only to screen readers.

## Video viewer — `LL-VID-01`

### Ready and loading

1. Load activity authorization, content revision, media policy, and safe
   resume metadata in parallel. Keep the player frame, outline, and below-media
   task region in place while loading.
2. A playable state requires an approved source, policy decision, scoped
   short-lived playback session, and authorized activity action. If any gate is
   absent, use `blocked_media` or `capability_unavailable`; do not render fake
   controls.
3. Use an accessible HTML video element (`playsinline` where supported) or the
   approved player primitive. The design does not select a provider, manifest,
   codec, signed URL, or retention policy.

### Controls and platform capability

| Control | Desktop Chrome | iOS Safari/PWA | Android-compatible PWA | Contract rule |
| --- | --- | --- | --- | --- |
| Play/pause | show when media session is ready | inline or Safari-native path, user gesture as required | browser/player path | never equates play with completion |
| Seek | show if policy/player allows | browser/player path | browser/player path | seeking alone cannot create watched evidence |
| Speed | show only when `playbackRate` and player policy allow | feature-detect; hide if unsupported | feature-detect | speed does not alter thresholds or assessment state |
| Fullscreen | standard Fullscreen API or native control | Safari/WebKit path where available | standard/native path where available | presentation-only; preserve route and focus on exit |
| PiP | standard API where available | WebKit presentation mode where available | browser policy/API where available | show only after support check; no fallback promise |
| Captions | approved `track`/player control | approved `track`/native control | approved `track`/player control | caption availability and locale are content facts |
| Transcript | panel/drawer when approved | panel/drawer when approved | panel/drawer when approved | transcript is not fabricated from a missing track |

Controls may be supplied by the browser's native media UI or by an approved
accessible wrapper. The visual reference must not imply that a custom control
is implemented before its platform contract is verified.

### Resume and watched evidence

- On entry, prefer the canonical activity resume position and revision. A local
  last position is at most a recovery hint and must be labelled local/stale.
- Resume is distinct from completion. Completion is determined by the versioned
  server policy for unique instructional coverage; page open, duration elapsed,
  seek, hidden-tab time, or a UI percentage cannot complete the activity.
- A playback session expires or is revoked independently of the activity route.
  Offer bounded refresh/retry and preserve safe module context.
- When a checkpoint is sent while online, the UI can show `Saving watch
  progress`/`Evidence processing`. It must not show `Complete` until the
  canonical projection confirms it.
- When offline, keep the cached poster/outline only if allowlisted. Do not
  promise offline video, captions, transcript, or canonical resume unless a
  separately approved media-download contract exists. A local position is
  never submitted in the background.

### Background and orientation

- On `visibilitychange`, preserve UI state and pause at an authored check. If
  the browser keeps playback alive in the background, hidden time is not by
  itself completion evidence; reconcile on return.
- On orientation change, retain the current media position and focus target.
  Portrait is the default. Landscape may enlarge the player when supported;
  failure to lock orientation leaves an inline usable player.
- Exiting fullscreen/PiP returns focus to the invoking control or nearest
  meaningful player control. Do not navigate unexpectedly.

## Captions and transcript — `LL-CAP-01`

- Captions are timed text from an approved locale/source. The toggle has a
  programmatic name and reports `On`/`Off`/`Unavailable` in text, not color
  alone. Captions are not optional decoration when required by the content
  contract.
- A transcript panel is a separate authorized content projection. It can sync
  the current cue only when timing metadata is available; otherwise it is a
  readable ordered transcript with no fake highlighting.
- If the source is missing, stale, processing, or denied, explain the boundary
  and offer retry/support where applicable. Never auto-generate or invent a
  transcript/caption claim in this package.
- On mobile, the transcript is a full-width disclosure or sheet; its close
  action, scroll region, and return focus are keyboard and touch reachable.

## In-video knowledge check — `LL-KC-01`

- An authored cue may pause playback and present one question with stable
  option IDs. The check is a task interruption, not a modal used to hide
  player errors.
- Selection is reversible before submit. Submit is explicit and online; the
  selected option may be held locally as `unsent` during a network loss, but
  it cannot become canonical through service-worker/background sync.
- Feedback is authored and deterministic (`Correct according to this lesson`,
  `Review the explanation`, or an equivalent approved copy). Do not render a
  model confidence, ability score, mastery, rank, or reward.
- A failed check returns the learner to the cue/explanation with a bounded
  `Try again` action. Repeated attempts are not silently collapsed into a
  canonical pass.

## Quiz/test — `LL-QZT-01`

- Render only the server-authored `interaction_schema` revision. Supported
  shapes are single choice, ordered steps, pair match, branching scenario,
  evidence chips, and confidence check; dragging must have select/tap
  alternatives.
- Show progress through authored questions as orientation, not a score or
  mastery meter. Preserve selected options while the learner reviews.
- `Submit assessment` is an online, idempotent, revision-aware mutation. A
  retry reuses the same intent; it does not duplicate a submission.
- Feedback is deterministic and content-authored. An official score,
  evaluator, or competency result is a separate AC-SVAL-gated contract and is
  intentionally absent here.
- If no questions are authorized, show an honest empty/processing state rather
  than a zero score or placeholder quiz.

## Reflection — `LL-REF-01`

- Present one labelled prompt, a text area with a purpose-specific accessible
  name, and a visible save state.
- State copy is exact and distinct: `Unsaved changes`, `Saving…`, `All changes
  saved`, `Save failed`, `Conflict`, `Offline — draft not synced`.
- Use server revision/`If-Match` for canonical save. Preserve input across a
  retry, session reauthentication, and explicit conflict reconciliation when
  the approved draft policy permits.
- Local storage failure is not a save success. Offer copy/export as a user-
  initiated recovery option if the policy allows; never hide the failure.
- Reflection is self-authored evidence, not a score, evaluation, or completion
  signal on its own.

## Implementation evidence — `LL-IMP-01`

- Ask for supported observable evidence in text or authored structured fields.
  An optional attachment/upload control is hidden or `capability_unavailable`
  until type, size, retention, provenance, and scanning contracts are
  approved.
- Keep `draft`, `submitting`, `submitted`, `awaiting_review`, and `retryable`
  distinct. `Submit evidence` is an explicit online mutation with idempotency
  and append-safe revision behavior.
- Copy must say what was recorded, not that the action occurred in the world.
  The screen never claims a call was real, a buyer acted, or a business result
  was verified.

## Human review — `LL-REV-01`

- `awaiting_review` is the truthful default after a submitted implementation
  evidence record when no assigned reviewer result is present.
- Show reviewer name, role, or identity only if the canonical assignment and
  privacy policy explicitly provide it. No “coach”, “expert”, or AI avatar is
  invented for visual polish.
- An assigned reviewer may create an append-only review note/result through a
  named authorized action. The learner view reports visibility, provenance,
  and time only where policy allows.
- Review is not an autonomous score, rank, mastery state, or access grant.
  Corrections supersede a prior result; history is not overwritten.

## Improve/retry — `LL-IMPR-01`

- Ask the learner to choose one explicit change or next behavior. Keep the
  response small and actionable; do not infer an improvement from an AI model.
- `Retry` returns to the failed/eligible authored task with preserved context.
  `Open next authorized task` reads the canonical projection and can be
  unavailable/locked.
- A successful improve write is confirmed with text and icon. The loop closes
  only when the server projection says the activity is complete; it does not
  imply mastery or a credential.

## PWA/install/update/offline — `LL-PWA-01`

- **Install available:** dismissible, platform-specific explanation. Android
  may expose the browser install flow; iOS may show Home Screen instructions.
  The product does not claim a native package.
- **Standalone:** remove duplicate browser chrome assumptions, retain safe-area
  padding, and keep the same route semantics. Standalone does not change
  authorization or content.
- **Update available:** show a non-blocking notice. Defer reload while a form
  is dirty, a mutation is processing, a knowledge check is paused, or media is
  actively playing; offer `Update when safe` and a recoverable retry.
- **Offline/stale:** render only allowlisted, owner-safe cached shell/course
  projections with a visible freshness timestamp. Block access changes,
  assessment submit, draft save, evidence submit, review writes, and video
  completion. Local approved drafts are labelled `Unsynced` and expire/purge
  under the local-draft policy.
- **Reconnecting:** re-read authorization and revisions first, then offer an
  explicit save/reconcile/submit action. Do not auto-submit.
- **Storage unavailable/tampered:** say local recovery is unavailable; do not
  claim retention. Keep the page usable where online, and offer copy recovery
  before leaving when safe.

## Auth recovery — `LL-AUTH-01`

- On `401` or explicit expiry, clear protected activity and reviewer data from
  the view, preserve only the approved local recovery envelope and intended
  route, and focus a recovery heading.
- `Sign in again` returns to the intended activity only after re-reading the
  latest authorization, activity revision, and draft/evidence revision. Any
  mismatch goes to conflict recovery.
- Do not disclose whether a protected activity, reviewer, or assessment exists
  while the session is invalid. A stale route is not permission.

## Responsive and accessibility contract

### Layout

- Desktop: persistent rail plus two-column activity shell; the current task and
  player remain first in reading order.
- Tablet/medium: compact navigation; roadmap follows the player/task; no
  clipped horizontal scrolling.
- Compact: one column, full-width primary action, contextual back, optional
  roadmap disclosure, and bottom navigation only for live destinations.
- Fixed bars and sticky actions use `env(safe-area-inset-top/right/bottom/left)`
  with a tested fallback. Content reserves clearance before the bar.

### Input and semantics

- Use real buttons, links, headings, ordered lists, fieldsets/legends,
  labels, and native media semantics. Every status has a text equivalent.
- Keyboard: logical order is roadmap → player → captions/transcript → current
  task → status → primary action. Focus is visible and never trapped in a
  closed panel. Escape closes optional drawers/overlays where supported.
- Touch: primary targets aim for 44 CSS px; drag interactions have tap/select
  alternatives; no hover-only disclosure.
- Zoom/reflow: test 200% text and 400% page zoom down to 320 CSS px. No loss of
  content/functionality or two-axis scrolling for ordinary text/actions.
- Contrast, forced colors, reduced motion, screen-reader announcements,
  focus-not-obscured, caption readability, and error association are release
  gates rather than visual assumptions.
