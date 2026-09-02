# Component and design-system contract

This is an implementation-facing visual contract only. It names semantics and
states; it does not add application code or activate a provider.

## Visual direction and tokens

Selected language: **Direction B — Momentum Workshop**, corrected pair. It
inherits the existing learner shell rather than introducing a new brand system.

| Token family | Contract |
| --- | --- |
| Canvas | warm/pale blue-gray canvas with white task surface; no gradients or glass |
| Ink | deep navy for primary text; slate for secondary copy; contrast tested in light/dark/forced colors |
| Action | cobalt/indigo reserved for primary action and current stage; never the only state signal |
| Divider | thin cool-gray borders; restrained 9–12px radii; minimal shadow |
| Type | readable system/sans fallback; no image text; title and body scale with 200% zoom |
| Space | 8px base rhythm; 16/24/32px section rhythm; no card soup |
| Motion | 100–300ms orientation-only transitions; disabled under `prefers-reduced-motion` |
| Target intent | 44 CSS px for primary touch actions; WCAG minimums remain a release gate |
| Safe area | `env(safe-area-inset-top/right/bottom/left)` with a tested fallback on fixed bars |

## Stable components

| Component ID | Name | States | Required semantics |
| --- | --- | --- | --- |
| `UI-LL-001` | `LearnerShell` | desktop, compact, standalone, offline, expired | landmarks, skip link, route heading, working destinations only |
| `UI-LL-002` | `ModuleRoadmap` | loading, ready, partial, locked, current, complete, offline | one semantic ordered list; lock reason and action association |
| `UI-LL-003` | `VideoViewer` | loading, ready, playing, paused, resume, processing, error, blocked, backgrounded | accessible video name, native/custom control parity, no completion inference |
| `UI-LL-004` | `CaptionsTranscriptPanel` | loading, captions-ready, captions-unavailable, transcript-ready, transcript-unavailable, denied | labelled disclosure/dialog, focus return, timed text only from approved source |
| `UI-LL-005` | `KnowledgeCheckCard` | ready, selected, validation, processing, feedback, retry, offline | fieldset/legend, stable option IDs, authored feedback, no AI score |
| `UI-LL-006` | `QuizTestForm` | loading, ready, validation, processing, retry, locked, offline, submitted | question grouping, tap/select alternatives, explicit submit and attempt revision |
| `UI-LL-007` | `ReflectionEditor` | ready, dirty, saving, saved, conflict, retry, offline, expired | label, `aria-describedby` status/error, revision-safe save, copy recovery |
| `UI-LL-008` | `ImplementationEvidenceForm` | ready, dirty, saving, submitted, processing, retry, conflict, offline | evidence scope and limits stated; uploads hidden/gated; no real-world certainty |
| `UI-LL-009` | `HumanReviewPanel` | awaiting, no-reviewer, reviewer-ready, submitting, saved, denied, retry | reviewer identity only from assignment; append-only result provenance |
| `UI-LL-010` | `ImproveRetryPanel` | ready, dirty, saving, locked, retry, offline, success | one explicit next behavior; canonical next destination; no mastery claim |
| `UI-LL-011` | `RecoveryBanner` | network, stale, conflict, storage, terminal, session | live status without focus theft; action and error association |
| `UI-LL-012` | `InstallUpdateBanner` | install-available, standalone, update-available, deferred | dismissible, platform-specific, never native-app promise |
| `UI-LL-013` | `CompactBottomNav` | active-route, safe-area, keyboard-open, offline | only working routes; does not cover input/actions; `aria-current` |
| `UI-LL-014` | `StatusRegion` | polite, assertive-error, processing | `role=status`/`role=alert` used intentionally; text plus icon/structure |

## Shell and responsive composition

### Desktop Chrome

- `LearnerShell` provides a persistent rail with Home, Learn, Progress, and
  Settings only for this loop.
- `ModuleRoadmap` sits beside the main activity region. The media/task region
  remains primary; no third analytics/marketing column.
- A sticky action may sit below the task, but it must not obscure captions,
  transcript, status, or fields when the window is resized.

### Responsive PWA

- Transform to one column below the compact breakpoint; retain the same
  semantic order and current/next state labels.
- `CompactBottomNav` follows the main content in DOM order, is padded by the
  bottom safe-area inset, and reserves scroll clearance.
- The roadmap opens as a disclosure/sheet; focus moves into it and returns to
  the invoking control on close. Landscape may enlarge video but is not needed
  to complete the task.

## Video and caption controls

`VideoViewer` may use native media controls or an approved accessible wrapper.
Controls are independently feature-detected:

- Play/pause and seek do not mark completion.
- Speed uses the media element/player rate only when supported and has no effect
  on watched thresholds or assessment answers.
- Fullscreen uses the available standard or Safari-native path; if unavailable,
  omit the control or say `Continue inline`.
- PiP uses standard browser or WebKit capability checks; if unavailable, omit
  it rather than displaying a dead control.
- Captions use a valid approved `track`/WebVTT source. Transcript is a separate
  content projection and can be unavailable even when captions exist.

Every control has a text label, visible focus, pointer/touch equivalent, and a
predictable focus return path after fullscreen, PiP, transcript, or check close.

## Forms and status behavior

- Each text field has one visible label and an error/status description. Do not
  use placeholders as the only label.
- Save/submit buttons are disabled only for the unsafe interval; a disabled
  action has an associated reason. A locked route is still server-denied.
- Status copy distinguishes `saved`, `submitted`, `awaiting review`, and
  `completed`. None is represented by color alone.
- Conflict UI preserves local and server values separately until the learner
  explicitly chooses/merges. Corrections supersede history.
- Offline drafts use local/unsynced language. A successful local write never
  becomes `Saved to your account`.

## Accessibility acceptance contract

- Heading hierarchy has one route heading and meaningful subheadings.
- The roadmap is an ordered list; player controls are a named group; checks and
  assessments use fieldsets/legends; forms use labels and error association.
- Keyboard order follows roadmap → player → captions/transcript → task → status
  → primary action. Focus is visible, not obscured, and not lost on reflow.
- Text and controls reflow at 200% text and 400% page zoom down to 320 CSS px.
- `prefers-reduced-motion`, high contrast/forced colors, pointer/touch,
  orientation, and screen-reader live regions are tested with browser evidence.
