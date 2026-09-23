# SX-WS-01: canonical workspace and live-connected local review

Public sanitized architecture edition, version 1.1. Reference repository base: `eb4d6ac48173d82efa9ca24ec15696a686465027`. This reference identifies source, not a deployed release. Confidence in the architectural direction is 0.90; application integration remains gated separately from the executable model.

## Decision

Production navigation identifies a call and content section. API truth determines whether the workspace is opening, active, held, ready or unavailable. The local developer workbench uses the real production-target controller and components through the fixed live bridge. Live, Observed and Presentation modes are visibly distinct.

Live means the latest authorized actual API observation. Observed means an immutable prior observed response set plus captured UI microstate, under current resource authorization. Presentation means a permitted UI-only variation over real authorized content, such as section, reader, focus, viewport or motion. A held view never pauses or rewinds a backend job. Completed work does not prove an earlier running or queued UI observation. Uncaptured history is unavailable.

## Product routes

Canonical routes remain `/?call=<opaque UUID>` and `/sales-xray?call=<opaque UUID>`. Sections are `overview`, `prospect`, `moments`, `skills`, `next-call-plan`. Call navigation pushes history; accepted new-upload call binding replaces; section changes replace without scrolling/remounting; background stage changes make no history entries. Reader, file picker, hashing/transfer, hover, focus, connection warning and observation timer are ephemeral. Developer inspection addresses do not turn these into customer-side authority.

Exact report/revision and moment links are later guarded resource selectors. They require authorized retrieval and source/revision binding. A mismatch cannot silently open another report. No prospect/journey identity exists merely because a single-call report has a Prospect section. Library filters/search must have an implemented scope; no invented API parameters or public search text are required for this slice.

Existing-call opening remains neutral through static hydration and owner checks, then opens a validated report directly or shows current progress/recovery. Invalid links are not new uploads. Restoring never recreates consent or auto-quotes. Temporary read failure is not report invalidation; explicit denial/deletion/mismatch removes affected content. Audio expiry disables playback without discarding an independently authorized report. Old/new publication coexistence requires real API identity support.

## Shared implementation

Extract pure view derivation with parity tests, composing the existing processing projection. Move existing workspace JSX rather than copying it. AcquisitionStudio retains all operational effects. Production view-port is a pass-through; an explicitly excluded development module selects a display view only. Captured responses are not passed off as live public API responses and are never assigned into operational React state.

The separate local control page does not overlay product pixels or require an iframe. It shows source/mode/capture time/last authorization state and source revision. Local URLs contain opaque session-bound selectors, never payloads, arbitrary destinations or authorization flags. The bridge owns history in memory. HMR restores only a descriptor and safe local UI choices after fresh checks, never write actions.

## Data and security

The fixed-origin bridge keeps normal authenticated access. A process-level analysis-read-only policy denies operational writes, with only explicit authentication/context exceptions. Unknown routes and methods fail closed. The inner Next process has no independent API upstream. Environment-file precedence and actual build outputs require verification, not only a hidden link or runtime boolean.

Capture is opt-in, minimal and memory-only. Per-call/session bounds cover frames, raw JSON, commands, lifetime and authorization. Resource permission is checked on each selected historical frame and under a short real-time lease while visible. Exact historical report/transcript artifacts need continuing authorization, not merely current call access. Scope change/revocation purges. Uncertain access masks. No guarantee is made about immediate physical memory erasure or external copies.

Response fingerprints are integrity checks, not proof of a remote server. Real origin/provenance comes from the trusted bridge collector. Actual response sets reuse existing application parsers; a fictional parser is only a regression fixture. A batch of responses is not inherently atomic. No newer transcript is paired with an older incompatible report. Credentials, raw audio, HARs, storage-state exports and operational data do not enter this public package.

## Microstates and visual work

The hierarchy is route -> observed workflow -> observation health -> microinteraction -> viewport/content/motion. The complete proposed catalogue is in contract.json. Eligibility rejects contradictory combinations rather than multiplying arbitrary variants. Hashing and transfer can have separate observed events while sharing one visual surface. Native file pickers require actual user interaction. Saved language comes from authorized report binding; a query cannot generate or relabel content.

The shell direction is reusable production-target black sidebar, red accent, white canvas and editorial hierarchy. Home/Calls are current-scope destinations; Reports is a supported ready filter when implemented; Prospects/Coaching select content within an actual call. Unsupported Insights/multi-call features remain unavailable. No identity, score, credit, probability, notification or revenue value is fabricated. Shell expansion follows the working seam; it is not a separate demo.

One persistent audio dock, clear focus restoration, meaningful status announcements, reduced-motion support and readable long code-switch text are required. Scroll is allowed where needed. Six-width actual captures and pixel comparisons do not replace source binding, interaction, accessibility or no-write assertions.

## Bounded delivery and rejection criteria

The delivered source package provides the typed model kernel, pass-through/development interface, command grammar and fictional fault tests. The integration plan is in INTEGRATION.md; complete application acceptance remains in acceptance.json. The kernel does not install a bridge or alter app source.

Rejected alternatives: route-per-stage authority, replaying historical bodies as public live responses, duplicate rendering/controller implementations, iframe protection changes, backend pause/reruns for styling, and a new router/global-state/worker framework.

A small offline compiled benchmark compares equal payloads and delays before/after the shared seam. Request graph, wrong-view frames, validated report paint, layout shifts and audio remounts are observed separately. No speedup or provider-quality result is assumed. Two-phase private baseline review separates evidence-ready from human-accepted; an edit or lineage change invalidates prior acceptance.

Stop after an existing authorized call, five sections, valid reader, held/reopened actual frame, safe HMR, honest missing history and passing auth/reset/build gates. If historical access or production exclusion cannot be proved, retain read-only Live and mark history unavailable. Staging, provider acceptance and deployment are separate authorizations.
