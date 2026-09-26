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

## Hosted build repair and mobile containment

Hosted application run `35919019052` for `7580f2c7` passed its compiled acquisition-browser gate, Python static and policy gates, and capacity simulation. Frontend validation and all four Python test shards stopped at the same prerequisite: the static Sales Xray preview tried to await request search parameters on `/auth/complete`. The Python shards did not reach their tests; these failures are not recorded as passing test suites.

Static preview export now supplies no callback flow without reading request parameters. The ordinary server-rendered callback still forwards the exact string flow to the existing validating client. The new regression tests cover both paths. Both static-preview export and the ordinary optimized production build pass locally after the repair. Hosted validation must be rerun on the successor revision.

The report review sheet also uses border-box sizing, incorporating UI checkpoint `f83b68ff`. The UI owner verified a 390px sheet and document both remain 390px wide after this one-declaration change. That synthetic preview check establishes layout containment, not generated report quality. Root includes no synthetic report fixture route in this release.

## Saved-report and account-first regression repairs

Hosted application run `35920706731` for `14d12ac3` reached the broader suites. Its compiled account browser, Python static/policy gates and capacity simulation passed. The frontend suite exposed two learner fixture assumptions about account/profile admission. The database shards exposed fresh guest upload fixtures that now correctly receive 401, the migration catalogue's two new identity/profile tables, and browser regressions. This source was not packaged for web deployment or released.

The saved-run report parser rejected the real API's nullable `execution_hold` field before reading a valid report's transcript. It now accepts only the known profile hold or null, preserving strict unknown-field and source/quote/time checks. Held direct jobs stop polling and show an explicit profile pause. The owner retained-report response now uses the same bounded recovery envelope as the acquisition report, including its immutable version. Admin retains the richer recovery audit view. Recovered drafts are explicitly labelled as retained responses rather than new analysis or human approval.

Account-first fixtures use verified canonical accounts and completed profiles for new uploads. Explicit guest denial, source ownership, cookie/origin tampering, private playback and allowance settlement remain tested. Learner tests now cover profile eligibility and show that an incomplete profile produces no upload or plan mutation. The standalone password browser test follows the visible existing-password choice on the shared sign-in form.

Local checks at this repair checkpoint:

- All three compiled legacy saved-report/standalone browser journeys passed over real loopback HTTP and isolated PostgreSQL, including report opening, retained audio playback and sign-out.
- Full Sales Xray web suite passed 418 tests after the retained-report label and accepted-plan pause assertions; the affected report contract/CallStudio suite separately passed 57 tests.
- Learner acquisition suite: 10 passed. Migration catalogue and release-guard tests: 14 passed.
- Retained C5 PostgreSQL recovery suite: 4 passed, including the exact owner-facing recovery envelope and preservation of the Admin audit metadata.
- Account library, submission HTTP and learner-plan PostgreSQL suites: 18 passed. The subsequent historical guest-claim fixture extension passed both account-library tests, preserving the original recording principal and visitor usage without another job or charge while denying fresh guest uploads.
- Static preview export, ordinary optimized production build, TypeScript and ESLint passed. Exact-source hosted checks must still be rerun after all repairs are committed.

These checks do not establish real email/SMS delivery, coaching-v5 output quality, production deployment, or complete Brain 3 coverage. No paid provider request was made by this repair checkpoint.

## Accepted-plan profile pauses

The coordinator now inspects the exact queued inference tasks it selects, including reused tasks, and publishes the bounded `account_profile_required` progress marker when their job is held before dispatch. The canonical plan remains active. Owner GET routes remain read-only and project that marker as a held presentation; they do not advance processing or enqueue work. After canonical profile completion and audited job reconciliation, the next normal scheduler tick clears the marker. The stopped browser view requires refresh or re-entry to observe resumption.

The focused PostgreSQL regression passes through the actual worker, latest-submission and direct-plan reads, profile service, reconciliation service and scheduler. It verifies zero provider calls/receipts or acquisition settlement and unchanged job/task identities, complete budget snapshot, revision and reservation count across hold and resume ticks. The existing processing-plan unit suite passes 32 tests. Full Python lint and typing pass; both new/changed plan files pass formatting. Hosted exact-source validation remains required.
