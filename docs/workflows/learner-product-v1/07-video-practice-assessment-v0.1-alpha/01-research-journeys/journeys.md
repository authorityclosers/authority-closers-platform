# Learning-loop journeys

## Journey IDs

| Journey | Actor | Entry | Exit |
| --- | --- | --- | --- |
| `JRN-LL-01` | enrolled learner | authorized module roadmap | next authorized activity after improve or explicit loop completion |
| `JRN-LL-02` | enrolled learner | video/activity interruption | safe resume or explicit recovery without losing approved local work |
| `JRN-LL-03` | enrolled learner | desktop browser, PWA install, or iOS/Android interruption | same semantic state across viewport, browser, orientation, and background transitions |
| `JRN-LL-04` | assigned human reviewer | explicitly assigned implementation submission | append-only review result visible to the learner, if policy allows |

## `JRN-LL-01` — Roadmap to improve/retry

1. `LL-MOD-01` loads the version-pinned module projection. It shows the ordered
   roadmap, current activity, safe lock reasons, and the single next action.
2. The learner opens `LL-VID-01`. If the media policy is not ready, the page
   remains an honest blocked-media state. No play icon, duration, transcript,
   captions, or completion control is invented.
3. When an approved playback session exists, the learner may play, pause, seek,
   change speed, open captions/transcript, enter fullscreen, or enter PiP only
   where capability checks allow. Resume position and watched-interval evidence
   remain separate server-owned facts.
4. An authored `LL-KC-01` may pause at a configured cue. The learner selects an
   answer and receives authored feedback. The UI does not infer ability, rank,
   mastery, or an AI score.
5. `LL-QZT-01` presents authored single-choice, ordering, matching, branching,
   evidence-chip, or confidence interactions where the activity schema permits.
   The learner can review answers before an explicit online submit. A failed or
   incomplete attempt keeps the attempt and offers a bounded retry.
6. `LL-REF-01` captures the learner's reflection. Draft, saving, saved, conflict,
   offline, and retry states are visible. `Save` never implies completion.
7. `LL-IMP-01` asks for one supported implementation evidence statement or
   approved structured response. It does not prove the real-world action or
   accept an unapproved call recording/upload.
8. `LL-REV-01` shows `Awaiting human review` until an assigned reviewer result
   exists. A reviewer is shown only from the assignment projection; no coach or
   AI is fabricated.
9. `LL-IMPR-01` asks the learner to name one change and offers `Retry` or `Open
   next authorized task`. Completion is shown only after the canonical result;
   the route never manufactures access.

## `JRN-LL-02` — Resume and recovery

| Interruption | Required response | Unsafe claim prohibited |
| --- | --- | --- |
| Refresh or route change while playing | re-read the authorized activity and display canonical resume position when available | “watched” from a local timestamp alone |
| Media source processing/error | keep module and task context; show retryable or terminal media state | fake player controls, transcript, or completion |
| Captions/transcript absent | show unavailable status or hide the control while retaining the task | fabricated transcript or auto-generated caption claim |
| Dirty reflection/evidence text | retain visible text; save online with revision; local recovery only if approved | “saved to account” before server acknowledgement |
| Connection lost | mark stale/offline, allow safe reading or local draft only, block canonical submit | queued/background canonical write promise |
| Session expired | clear protected projection; retain only approved local draft and intended return route | showing protected activity payload or silently retrying mutation |
| Revision conflict | show server and local versions separately; require explicit merge/keep choice | last-write-wins overwrite |
| Browser/PWA update available | defer reload while dirty, submitting, or in active playback/check; explain when safe | destructive reload over learner work |

## `JRN-LL-03` — Responsive PWA continuity

### Desktop Chrome

- Persistent Home/Learn/Progress/Settings rail; media/task column plus concise
  roadmap column; no more than two major columns.
- Fullscreen and PiP controls are optional and feature-detected. Keyboard focus
  remains inside the player or dialog until the user exits it.
- Space toggles play/pause only when focus is on the player; arrow keys seek
  only when the focused control supports it. Text inputs keep native editing
  behavior.

### Responsive PWA / iOS Safari / Android Chrome

- One-column order: context → roadmap disclosure → media/current activity →
  captions/transcript → response → status → primary action.
- Bottom navigation and sticky primary actions include
  `env(safe-area-inset-bottom)` and never cover captions, errors, inputs, or
  submit controls.
- Portrait is the default. In landscape, the player may expand if the browser
  supports it; if not, the task remains usable inline. Orientation lock is never
  required.
- Install prompts are optional. Android can expose a browser install action;
  iOS exposes labelled Home Screen guidance where applicable. Standalone mode
  is a browser display mode, not evidence of native iOS/Android code.

## `JRN-LL-04` — Human review boundary

1. The learner submits implementation evidence online through an authorized,
   append-safe command.
2. Until a reviewer assignment is returned, show a neutral waiting state and
   the learner's own submitted evidence status only.
3. An assigned reviewer may add a review note/result within the permitted
   contract. The UI labels the source and time without exposing unsupported
   identity or private tenant data.
4. The learner can read the result when visibility policy allows and then open
   `Improve`. A review result never becomes an autonomous score, mastery claim,
   or access grant.
