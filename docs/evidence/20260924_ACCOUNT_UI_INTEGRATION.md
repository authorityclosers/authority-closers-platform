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

## Shared login checkpoint

The `6e13ea81` UI checkpoint replaces the separate login form with the shared compact account component, opens authentication immediately after file selection, and preserves the same File through Back and sign-in. The root integration explicitly opens the canonical profile gate after successful inline authentication. The obsolete separate login implementation is removed.

The integrated optimized build, lint, and 87 focused account/login/profile/fixture tests pass. The compiled browser run now verifies the complete local selection, OTP, required profile, original-byte upload, processing, exactly-once allowance settlement, report, reload, second-context login, saved-call discovery, actual retained audio playback and deletion. Its final sign-out step exposed a stale harness selector: the account menu now includes the saved profile name. The harness now addresses that visible name and awaits the actual menu. Full acceptance remains pending its rerun, including logout and private-endpoint denial; the partial run is not reported as a pass.

## Completed local browser gate

The subsequent frozen UI integration through `006bcd48`, including the preserved staging recovery implementation and account fixture adaptation, passed the required compiled browser gate. Its 24 assertions include the real logout button returning 204, private endpoints denying the logged-out browser, and an unrelated browser denied access. The observed journey uses 98 local HTTP receipts, zero API response interceptions, zero provider network requests and no browser page errors.

The same original audio bytes remain browser-local until email authentication and required profile completion. There are zero pre-authentication or pre-profile upload/plan writes. The canonical usage and completion settlement are each created once, and a fresh browser context finds the same account's saved call and plays its retained audio. Email delivery, challenge verification, the native socket and paid provider network are explicit test adapters, as described above.

The integrated web suite passes all 412 tests. The optimized build and ESLint pass, and Python type checking reports no issues in 310 source files. Final formatting repairs change only layout/quoting in source and tests. Sanitized machine receipts are saved beside this evidence under `sales-xray-v02-20260923/account-required-browser-proof.json` and `account-required-browser-receipt.json`.

This completes local account-journey acceptance; it does not establish staging/production deployment or coaching-v5 report quality.
