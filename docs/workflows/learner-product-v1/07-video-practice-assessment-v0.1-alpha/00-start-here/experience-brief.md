# Experience brief

## Outcome

Help an enrolled learner move through one module as a visible, recoverable
learning loop:

`Roadmap → Watch → Check understanding → Quiz/Test → Reflect → Implement → Human review → Improve/Retry`

The loop must make the next safe action obvious, retain context when the
browser or connection changes, and never overstate what the system knows.

## Actors and boundaries

| Actor | Goal | Allowed authority |
| --- | --- | --- |
| Enrolled learner | consume approved lesson material and submit their own work | server-authorized self-scoped reads and idempotent mutations while online |
| Assigned human reviewer | review an explicitly assigned implementation submission | server-authorized assigned-reviewer action with provenance; no inferred identity |
| Browser/PWA | render and recover the experience | presentational state and approved local recovery only; never canonical authority |
| Media policy/delivery seam | decide whether approved media may be played | capability/policy response only; no provider activation in this package |

No real learner call, recording, external AI, external media provider,
notification provider, or native store package is in scope.

## Platforms

| Surface | Baseline composition | Required truth |
| --- | --- | --- |
| Desktop Chrome | persistent learner rail; two-column activity shell; outline beside task | keyboard and pointer paths are equivalent; fullscreen/PiP/speed are feature-detected |
| Responsive PWA | one-column task-first layout; contextual back; safe-area-aware bottom navigation | installed/standalone is optional browser presentation, not native-app evidence |
| iOS Safari / Home Screen | `playsinline` media when approved; Safari-native fullscreen/PiP where supported | never promise a control the current WebKit surface does not expose; use a labelled fallback |
| Android-compatible Chrome PWA | browser media controls and install/update affordances where available | install, update, background, and offline behavior are conditional on browser policy |

## Module and activity model

The route receives a version-pinned learning projection. A module roadmap shows
safe titles, order, current state, and prerequisite reason. The first loop uses
these stable activity kinds:

1. `VIDEO` — approved instructional participation evidence; page open and seek
   alone never complete it.
2. `KNOWLEDGE_CHECK` — one authored check at an approved video cue; feedback is
   deterministic and not an AI judgement.
3. `QUIZ_TEST` — authored low-typing questions or ordering/matching; submission
   is revisioned and online-authorized.
4. `REFLECTION` — learner-authored text with durable draft/revision behavior.
5. `IMPLEMENTATION_CHALLENGE` — supported evidence of an intended action; it
   does not prove the real-world action occurred.
6. `REVIEW` — learner self-review or an explicitly assigned human review; no
   fabricated coach, reviewer, score, or certainty claim.
7. `IMPROVE` — one explicit next behavior and an authorized retry/next task.

The canonical learning projection, activity policy, draft revision, evidence
submission, and assigned-reviewer policy determine which of these are
available. The visual sequence is not an authorization rule.

## Data and privacy boundary

Canonical facts (activity state, watched intervals, authored-answer
submission, draft revision, evidence submission, reviewer result, and
completion) are online server-owned records. Local storage may hold a bounded,
encrypted recovery envelope only when the approved draft policy allows it; it
is labelled local/unsynced, scoped to the learner context, and never treated
as canonical. Do not cache credentials, session tokens, protected API
responses, reviewer data, evidence files, or signed media URLs in a service
worker cache.

## First-value and exit

Entry requires an authenticated enrolled learner and a readable, authorized
module projection. The learner can exit to the module or home at any safe
point. A successful improve submission closes the loop only when the
canonical projection says so and then names the next authorized task. It does
not claim mastery, competency certification, or a guaranteed real-world
outcome.

## Open gates

- approved lesson media and provenance;
- captions and transcript source, locale, and retention policy;
- playback-session/resume policy and evidence threshold;
- assessment interaction schema and any official result semantics;
- assigned-reviewer role, privacy, and append-only result contract;
- offline cache allowlist and local-draft retention/cleanup;
- exact iOS Safari, Android PWA, keyboard, zoom, orientation, background, and
  assistive-technology evidence.
