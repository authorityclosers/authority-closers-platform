# Default onboarding page completion regression

Date: 2026-09-13 (Asia/Kolkata). Status: focused tests and static checks passed;
full learner regression and canonical browser acceptance pending.

Independent review of the password activity-return slice found that existing page
regressions exercise onboarding recovery panels, while completion regressions
mount OnboardingForm directly. Neither proves that the default OnboardingPage
passes its navigation props into the actual form through a canonical profile load.

`activity-onboarding-page.test.tsx` adds eight cases: skip and finish through the
actual default page for a normalized activity UUID, settings precedence, duplicate
activity fallback retaining the known course, and default home. It checks the
server profile read, explicit save command with the current revision/step, and the
completion link destination and label. A hoisted mocked API covers the form's
module-level default client; the test does not inject navigation props into the
form directly or replace the form implementation.

This addition changes no product source. After the user resumed work, all eight
cases passed under Node 24.19.0 with one Vitest worker, file parallelism disabled,
and a 256 MiB Node heap limit. Scoped Prettier and ESLint with zero warnings passed.
A subsequent learner TypeScript check passed in a separate process with a 384 MiB
heap limit. The formatted test's SHA-256 is
`21bea7f3a4cb08888a1bad1ecb161ce3d0ec83ca0120ff51ed7885fd5ae0b63d`.

Receipts under `D:/Projects/authority-closers-release-transfer/2026-09-11-recovery`:

- `activity-onboarding-page-focused-20260912T204859Z`: formatting, eight passing
  tests and zero-exit ESLint. ESLint emitted no output.
- `activity-onboarding-page-types-20260912T205104Z`: zero-exit learner TypeScript
  check with no output, bound to the same test bytes.

The prior 139 passing targeted cases and the original 13-file validated snapshot
remain evidence for their original exact scope. These eight cases passed in a
separate run, not a combined 147-case run. The earlier memory-precheck refusal at
`activity-onboarding-page-focused-20260912T202434Z` remains retained as not run;
the successful later run supersedes its pending-test status. The local checkpoint
preserves this tested scope while the shared test-slot hold continues. Include the
new file in the full learner regression before release integration.

No runtime, database, browser, build or deployment was started. Full learner and
canonical draft/session acceptance remain held by the release task. This test is
not evidence of real authentication, RSC transport, PostgreSQL persistence or
browser return behavior, and does not complete the broader goal.
