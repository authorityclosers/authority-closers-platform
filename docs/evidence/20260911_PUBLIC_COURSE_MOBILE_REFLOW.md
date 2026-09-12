# Public course mobile curriculum reflow

Validated 2026-09-12 as a separate slice after course-authentication checkpoint
`dc4b2a7216651697762417aef5fb14f358099e08`. The evidence filename preserves the
2026-09-11 defect-discovery date; execution dates below identify the resumed run.

On a 320px screen, the first module title occupied about 85px of the 214px
available inside its 258px header and overlapped the activity count. Two nested horizontal flex rows and
generic module-card padding caused the collision. The phone-only correction
removes the extra outer padding, puts module number/title/count on separate
rows, uses the full available title width and increases title line height.

The 21 added CSS lines are scoped to `.public-program-storefront` inside the
existing `max-width: 760px` breakpoint. There are no markup, course content,
authentication, membership, enrollment, progress, provider or schema changes.
The controlled basis is the mobile/accessibility requirement in AC-UXA-01 and
the free-first UI quality requirement in `V02_REVENUE_RELEASE_CUT.md`, using the
controlled-source register already recorded in the recovery checkpoint.

## Measured regression

The new Playwright regression reads the real same-origin public program API,
then compares every rendered module ID, title, number and activity count. It
measures title/number/count rectangles and wrapped text fragments, containment,
phone title width/line height, wide horizontal layout and document overflow.
Contexts remain unauthenticated; unexpected mutating requests are blocked and
reported. No fixtures are published or accounts enrolled by this test.

| Width | Before | After | First title width after |
| --- | --- | --- | --- |
| 320px | 23 violations, including seven overlaps | No violations | 250px of 250px available |
| 390px | 16 phone readability/layout violations | No violations | 320px of 320px available |
| 768px | Passed | Passed; every measured module property identical | Existing horizontal layout |
| 1440px | Passed | Passed; every measured module property identical | Existing horizontal layout |

The initial unchanged-source run had **two failed and two passed** cases; both
phone failures are retained as the regression baseline. The final run had
**four passed** cases and no document overflow or mutating requests. All four
final full-page images were visually inspected. The earlier element-cropped
images included the sticky site header over the curriculum; the final capture
uses the unmodified page at scroll origin and supersedes those images.

Focused learner UI validation passed **102 tests in seven files**. Scoped
Prettier and Python Ruff checks/format passed. TypeScript/application behavior
was not changed; the immediately preceding 1,578-test learner suite remains
recorded in the separate authentication checkpoint, not counted as a new run
for this CSS slice. Independent review found no P0/P1/P2 defects in the bounded
CSS/test change.

## Evidence and release boundary

Recovery packet: `D:/Projects/authority-closers-release-transfer/2026-09-11-recovery`.

- `runtime-resume-20260912T180702Z`: verified missing old process handles, preserved
  prior logs and restored all three local apps/API using the managed launcher.
- `public-course-reflow-before-20260912T180850Z`: unchanged stylesheet SHA256
  `46d94f81bfd37299c6bd9a73b7783c249e59c594077417e8507c0367dc2618cf`, failure
  measurements and original images.
- `public-course-reflow-after-20260912T181001Z`: first passing geometry run;
  element crops are superseded for visual review.
- `public-course-reflow-after-20260912T181246Z`: final passing geometry, exact
  source hashes and four full-page images.
- `public-course-static-20260912T181118Z`: 102 focused UI tests and formatting.
- `public-course-mobile-checkpoint-paths-20260911.json`: exactly three paths:
  stylesheet, browser regression and this evidence document.

This supersedes the mobile curriculum defect observation in
`20260911_FREE_COURSE_AUTH_CONTINUITY.md`; historical evidence remains intact.
The change is a local source checkpoint for separate release reconciliation.
It does not prove deployment, email-link continuity or the full course-delivery
journey, and does not activate any blocked capability.
