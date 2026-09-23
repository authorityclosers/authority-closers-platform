# Account UI integration checkpoint

The committed UI checkpoint `7d7d393f` is integrated with the account/profile API and versioned coaching successor. Historical UI merge conflicts retain the reviewed multi-file staging and inline sign-in components. Account-first integration opens authentication after local selection and returns false from unauthenticated analysis admission. The selected File and its identity remain in the shared pending-selection context.

The report client now accepts optional dimension transcript evidence, preserving absent legacy fields and explicit empty unknown arrays. Observed/conflicted dimensions with supplied evidence require a reference. Source IDs, quotations and native times are checked against the available transcript; rubric citations remain separate.

Compiled browser testing discovered a missing low-cardinality telemetry vocabulary entry for `email.identity_login_code.v1`. The actual email worker delivered the synthetic code but then raised while recording completion. The exact known job type is now allowed; arbitrary identifiers and unknown job kinds remain rejected.

## Checks and limits at this checkpoint

- Focused account UI tests: 103 passed initially, with one test requiring adaptation to immediate sign-in; all 11 standalone tests passed after that adjustment.
- Report contract: 28 tests passed, including absence versus empty evidence and invalid source/quote/time rejection.
- Telemetry: 19 tests passed including login-code completion telemetry.
- TypeScript, ESLint and optimized Next build passed. Changed UI files were formatted.
- The compiled real-cookie HTTP/PostgreSQL browser journey is still in progress. Early runs exposed and repaired the telemetry failure, cross-loop test diagnostics and stale form selectors. No claim of full browser acceptance is made by this checkpoint.

This local test uses fictional audio, a synthetic email delivery adapter and a synthetic provider broker; it does not send a real email, SMS or paid provider request. It must not be described as production verification or report-quality acceptance. The separate UI studio's development worktree is untouched by this integration.
