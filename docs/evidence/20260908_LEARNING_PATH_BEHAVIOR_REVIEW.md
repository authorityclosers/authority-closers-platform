# Learning path: independent behavior and code review

Date: 2026-09-08. Scope: uncommitted localhost changes in the single `d2de`
implementation tree; no deployment, push or live-data changes.

## Actual execution path reviewed

`/learn/[programSlug]` mounts `LiveLearningPath`, which renders `LearningModules`
and `LearningActivityNavigation`. The module route mounts `LiveModule` and the
same activity component. The older `HomeLearningPath` helper is not substituted
as proof of this redesign.

Reviewed independently from the production author:

- The changed functions above, `learningPathContinueTarget` and
  `CourseProgressSummary` in `learner-runtime.tsx`.
- `learning-journey.module.css`, including narrow layouts, focus, native
  chapter disclosures and OS/user reduced-motion behavior.
- Shared original `LearningSymbol`/`ProgressOrbit` SVG components and styles.

The reviewer changed only `app/lib/learner-ui.test.ts` and this evidence entry.

## Findings and dispositions

- Offline course copies previously disabled activity children but still exposed
  module footer links. Mixed cached identity/program responses also needed to
  disable fresh-looking rows. The author now propagates overall offline state
  through both actual route owners and blocks activity/module links.
- The main course CTA still fell back to the first module when every activity
  was locked or the module was empty. The author fixed it: existing actionable
  activity first, otherwise a chapter with nonlocked content, otherwise the
  local course-outline anchor. It no longer contradicts the disabled outline.
- Hard-coded Free Course/Module 1 presentation was removed from these generic
  enrolled-course views. Titles, order, positions and activity IDs remain from
  the supplied server response.

No unresolved Critical/Important finding remains in this **scoped code review**.
Authentication, enrollment, completion predicates and mutation APIs were not
changed by the reviewed presentation patch. Decorative artwork does not award
completion; unknown progress remains unknown in the shared progress primitive.

## Tests and limits

`app/lib/learner-ui.test.ts`: **84 passed**, including 16 added cases. Coverage:
exact route/order rendering; locked/unpublished exclusion; review-pending read
navigation without mutation authority; offline copies and parent-disabled state;
native chapter expansion; truthful completed counts; empty state without
invented rewards; and actionable/reviewable/locked/empty main-CTA selection.

Node 24, Vitest single worker, no file parallelism, 512 MiB heap; 15.44 seconds.
An initial unrestricted launch failed before collection with native VirtualAlloc
exhaustion. It is not counted as a test failure or pass. A bounded rerun succeeded;
no user browser or unrelated runtime was stopped. Scoped ESLint passed after
renaming a test-local variable reserved by Next's lint rule; Prettier applied.

These are actual-component rendering and behavior contracts, not browser layout,
keyboard-event, native-device, production performance or full-release acceptance.
The author/projection agent owns separate mounted-browser desktop/mobile proof.
