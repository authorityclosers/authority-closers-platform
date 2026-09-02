# Research scan and source manifest

Research date: 2026-09-03
Workstream: `AC-WF-LL-07`
Status: implementation-facing evidence and inference; not a product-policy
supersession

## Authority and fetch discipline

The source order from `AGENTS.md` was respected: Master Index, BRD, AC-IMP-00,
AC-IMP-01, AC-IMP-03, AC-IMP-04, and AC-IMP-05 precede the supporting PRD, IA,
UX, UI, SRS, data/tenancy, API, security, QA, DevOps, admin, telemetry,
Mobile/PWA, and ADR/risk sources. The repository's
[`CONTROLLED_SOURCE_REGISTER.md`](../../../../traceability/CONTROLLED_SOURCE_REGISTER.md)
provides the exact Drive IDs/URLs; local implementation mirrors and knowledge
records are used here for interpretation. A Drive/Docs connector was not
callable in this task, so this package makes no Drive upload, edit, or link
claim.

## Controlled sources used

| Source ID / exact Drive ID | Local mirror or contract | Applied boundary | Confidence |
| --- | --- | --- | --- |
| Master Index — `1gC6BdFZ2LfjrpjM-qPKcX1qWMTUBSAXo3b-AlaOYqus` | `docs/traceability/CONTROLLED_SOURCE_REGISTER.md`; trusted-read artifact | precedence, controlled-document status, source order | high |
| BRD — `1HEp7QN4u3c_636uACznnkruYHhGYHAJWXH7Dlfjybpk` | register plus `docs/knowledge/v0.1-alpha/SRC-000-control-authority.md` | founder-approved business boundary | high |
| AC-IMP-00/01/03/04/05 — exact IDs in the register | `docs/workflows/v0.1-alpha-experience/` and `docs/knowledge/v0.1-alpha/` | implementation controls, state safety, hostile-finding normalization, handoff and evidence | high for local interpretation |
| PRD — `1vZGxiP5GRA7He0gA7oF6hmTeHqoEZUIJko_QBUtDW_k` | `.artifacts/research-drive/01-workflow-catalog.md` | P0 loop and future capability boundary | high for repository interpretation |
| IA — `1VLJTswU2sqlimfoSIROVvlJ9Z6ue-6Dd45oEcu1ddhs` | `.artifacts/research-drive/01-lms-information-architecture.md` | route hierarchy and module/player composition | high for repository interpretation |
| UX research — `1M_IlSgZwWfHVk1IU3JBzY-EhT3RIfXO07WII8MbwxPM` | `.artifacts/research-drive/03-evidence-based-learning-experience-research-2026-09-01.md` | evidence/inference separation and learning-loop rationale | medium-high |
| UX states — `10HzU7kLk78WBHd_Y23jYaP0rIaScq7gW27e5D7D-08E` | `docs/workflows/v0.1-alpha-experience/02-ux-state-spec/behavioral-spec.md` | named loading, lock, offline, expiry, recovery states | high |
| UI system — `1y7yCqro9ABW8Yn61ZVmnLV8eGlelcq3BisCDTx40SsI` | `docs/workflows/v0.1-alpha-experience/03-visual-contract/design-system-contract.md` | tokens, semantic components, accessibility gates | high |
| SRS — `1qE_ASXOBN-AAuIglfs4-5Fi_HN3x-jDItBYdb95Ou2g` | `docs/knowledge/v0.1-alpha/SRC-040-engineering-contracts.md` | revision, idempotency, deterministic route behavior | high for repository interpretation |
| Data/tenancy — `1SUxNYTu30NXwBEbk7os1OBVn4H5qBky-LnzLuOvwaYw` | `docs/knowledge/v0.1-alpha/SRC-050-trust-operations.md` | tenant/person/activity scoping and audit separation | high for repository interpretation |
| API/MCP — `1kWawS57AGVv7jT5Kp2V0Mk8kK0B6BwPzlG6KiAOtpt0` | `docs/knowledge/v0.1-alpha/API-003-learning-evidence.md`; existing route contract | learning/draft/evidence seams; conditional playback | high |
| Security — `1rFTiq7BI4dpLLMIDacC8qMhpAbAmOct8W_I65Ydqbmw` | `docs/security/AUTHORIZATION_MATRIX.md`; route contracts | self/assigned-reviewer authorization, safe origin, privacy | high |
| Mobile/PWA — `1wxYkUGdHchtSYFpiXxGWQoaT95D4y4LO_qZG7MlEsoI` | `docs/knowledge/v0.1-alpha/JRN-05-resilient-web-pwa.md`; route contracts | browser/PWA resilience and native boundary | high |
| QA/release — `1DUx9JIHNC1KCR62Qso6KTFPoBxmfhU6GSuNqSl87hBg` | `docs/workflows/v0.1-alpha-experience/05-handoff-qa/qa-release-checklist.md` | evidence and release gates | high |
| ADR/risk — `1cNE-8DB0iX28U5IR_StkO-JGE2TPG-pbKn6LQ-bZSaY` | `docs/adr/0024-0028*.md`; `docs/knowledge/v0.1-alpha/SRC-060-decisions-risk.md` | bounded scope, canonical progress, no provider coupling | high |
| AC-UXA-01 — `1ZRyNPkkfc8DsBAlpKE9ksb6Oi-nB9BX-` | `docs/knowledge/v0.1-alpha/SRC-030-state-interface-assurance.md` | three-layer state model and a11y assurance | high |
| AC-SVAL-01 | exact controlled source required before any official scoring/evaluation | this package records a gate only; it does not activate scoring | high |

## Public platform and accessibility evidence

The links below support platform behavior and accessibility mechanics. They do
not define Authority Closers business semantics.

| Evidence | Source | Design consequence |
| --- | --- | --- |
| Timed text tracks use the HTML `track` element and WebVTT; availability is conditional on an approved source. | [MDN `track`](https://developer.mozilla.org/en-US/docs/Web/HTML/Reference/Elements/track) | Render captions only when a valid authorized track exists; transcript is a separate availability state. |
| Safari supports inline playback when `playsinline` is used; fullscreen paths differ between inline and native controls. | [Apple: Delivering Video Content for Safari](https://developer.apple.com/documentation/webkit/delivering-video-content-for-safari) | Feature-detect inline/fullscreen behavior; never promise the same controls on every Safari surface. |
| Safari exposes WebKit presentation modes and a support check for PiP. | [Apple: Adding PiP to Safari media controls](https://developer.apple.com/documentation/webkitjs/adding_picture_in_picture_to_your_safari_media_controls) | Show PiP only when the current video and platform report support; otherwise omit or explain availability. |
| Standard document PiP availability is observable through a browser capability property. | [MDN: `pictureInPictureEnabled`](https://developer.mozilla.org/en-US/docs/Web/API/Document/pictureInPictureEnabled) | No hard-coded “PiP works” promise in copy or assessment logic. |
| Fullscreen is a browser API with permission/policy and user-gesture constraints. | [MDN: Fullscreen API](https://developer.mozilla.org/en-US/docs/Web/API/Fullscreen_API) | Fullscreen is an optional presentation state and must not change progress semantics. |
| Playback rate is a media-element property and may vary by implementation. | [MDN: `playbackRate`](https://developer.mozilla.org/en-US/docs/Web/API/HTMLMediaElement/playbackRate) | Speed options are present only when supported; rate never changes evidence thresholds. |
| Service workers can cache resources for offline operation; background work is browser-controlled and may be stopped or retried. | [MDN: Offline and background operation](https://developer.mozilla.org/en-US/docs/Web/Progressive_web_apps/Guides/Offline_and_background_operation) | Cache only an allowlisted read shell; do not turn browser background behavior into a canonical-write guarantee. |
| Installation is a browser/OS-mediated PWA action, not a native package claim. | [MDN: Installing web apps](https://developer.mozilla.org/en-US/docs/Web/Progressive_web_apps/Guides/Installing) | Android install CTA and iOS Home Screen guidance are conditional, dismissible, and honest. |
| `env()` exposes safe-area inset values where the browser provides them. | [MDN: CSS `env()`](https://developer.mozilla.org/en-US/docs/Web/CSS/Reference/Values/env) | Pad fixed navigation and action regions with `safe-area-inset-*`; verify on real devices. |
| Page visibility changes can be observed when a document is hidden or visible. | [MDN: Page Visibility API](https://developer.mozilla.org/en-US/docs/Web/API/Page_Visibility_API) | Backgrounded playback/checkpoint behavior is explicit; hidden time is not silently treated as watched evidence. |
| Orientation locking is conditional and browser/security-context dependent. | [MDN: `ScreenOrientation.lock()`](https://developer.mozilla.org/en-US/docs/Web/API/ScreenOrientation/lock) | Prefer graceful portrait/landscape reflow; do not require orientation lock for task completion. |
| WCAG 2.2 requires reflow at narrow widths and supports text resize, focus, input, and target-size criteria. | [W3C WCAG 2.2](https://www.w3.org/TR/WCAG22/) and [Resize Text](https://www.w3.org/WAI/WCAG22/Understanding/resize-text.html) | Test keyboard, focus, 200% text, 320 CSS px reflow, non-color status, and touch targets before approval. |

## Evidence versus inference

| Type | Observation | Confidence | Package inference |
| --- | --- | --- | --- |
| Controlled product fact | The v0.1 loop is `VIDEO → REFLECTION → IMPLEMENTATION_CHALLENGE → REVIEW → IMPROVE`; progress is server-owned. | high | Keep one semantic ordered loop and separate local recovery from canonical writes. |
| Controlled capability gap | Approved media, caption, transcript, playback, reviewer, and assessment contracts are incomplete or mixed-evidence. | high | Use explicit `gap_blocked`, `capability_unavailable`, and `awaiting_review` states; no fake controls or identities. |
| Platform fact | Browser media and PWA APIs expose capability checks and platform-dependent behavior. | high | Controls are conditional and do not alter learning state. |
| Learning research | Retrieval/application and reduced extraneous processing are useful hypotheses. | medium | Make the next authored action obvious; do not claim a learning outcome from a UI pattern. |
| Design inference | One current task plus a visible module roadmap helps resume and orientation. | medium | Desktop uses two major columns; mobile collapses the roadmap behind a labelled disclosure. |
| Design inference | Offline interruption is safer when the learner can see local/unsynced work. | medium | Preserve approved local text with explicit `unsynced`; block canonical submit and provide copy/retry. |
