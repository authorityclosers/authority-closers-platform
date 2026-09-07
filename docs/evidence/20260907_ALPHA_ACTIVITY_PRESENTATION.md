# Alpha lesson presentation and support navigation — September 7, 2026

## Implemented locally; not a live media claim

The user's supplied mobile lesson screenshot showed two copies of the lesson
title, an oversized engineering-status panel, a raw media-binding reason and
generic storage diagnostics before useful lesson actions. This change keeps one
activity title, uses compact plain-language unavailable/restricted states, moves
published video notes into an accessible disclosure below the player, and retains
the responsive module path. No media is fabricated or marked complete.

For a video with no dirty response, stale draft or pending cleanup, the generic
device-storage notice is a native disclosure. Actual recovery content, dirty
drafts and cleanup failures remain visible. Non-video prompts, editors and
explicit Save/Submit actions retain their existing order and behavior.

The floating Help widget is removed. Human support remains reachable through
the navigation/account surfaces. No unconnected AI control replaces it. Practice,
usernames, streaks and competition are tracked as later functional slices after
video delivery, not implied by this UI change.

## Verification

- Three new mounted/server-rendered activity tests cover the single heading,
  lesson-note order and parent labeling; preserved reflection editor order;
  and the closed generic storage disclosure for a non-editable video.
- Focused activity/shell/insights run: **61 tests in three files passed** in
  3.98 seconds. Prior activity/clarity/UI run: **88 tests in three files passed**.
- A formatting warning in the new test was corrected; scoped Prettier and
  `git diff --check` then passed.
- `scripts/qa_alpha_activity.py` final accepted presentation run:
  `screenshots/alpha-activity-interim-2026-09-07/run-20260907T144509608226Z/results.json`.
  **16/16 cases**, unavailable/restricted video at 320/390/768/1440 in light/dark,
  Chrome 152.0.7977.82. Sixteen PNGs, no horizontal overflow, page/console errors,
  real writes, unknown APIs or external requests. Actual `data-theme` and computed
  colors were verified, not inferred from the requested browser color scheme.
- The harness checks title/copy, accessible notices, module-path keyboard use,
  disclosure behavior, touch targets, reduced motion and absence of floating Help.
  Fresh contexts load no user profile, cookies or saved session. Synthetic reads
  are explicitly labeled; these are not staging/production playback measurements.
- Earlier diagnostic runs are preserved. Some exposed harness/theme-selection
  mistakes and were not counted as acceptance. After handoff, import/line-layout
  lint issues were corrected without changing fixture content or assertions;
  Ruff lint/format and Python compilation passed.

Root visually inspected the final 390px dark unavailable lesson and 1440px light
restricted lesson, including readable wrapped copy and keyboard focus. Fixed
mobile navigation appears at the browser viewport position in full-page images;
the remaining scrollable page is not evidence of duplicated navigation.

The related playback implementation has separate mounted/native-video tests.
Real VPS media installation, authenticated delivery, progress recording and
production release must not be inferred from an unavailable-state screenshot.

## Evidence publication

[Local Alpha refinement QA folder](https://drive.google.com/drive/folders/1yIaDR8V5JNG8u98OGh_uZVYrpSiQGP6v)
is explicitly labeled **LOCAL QA — NOT LIVE**, separate from the existing
`851ebc8` staging release and its before/live records. All **60 files** (profile
before/after and activity screenshots plus their three reports) were uploaded;
each ID/name/byte-count/parent was read back and matched. The register includes
source SHA-256 hashes: `screenshots/alpha-refinement-drive-register-2026-09-07.json`.

Independent review found no Critical/Important issue, independently passed
111 tests across five scoped suites, and inspected the final responsive/theme
captures. A current exact-head CI run and immutable deployment are still required
before this presentation change is called live.
