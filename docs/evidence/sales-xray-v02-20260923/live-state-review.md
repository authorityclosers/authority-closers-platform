# Live-connected processing review

The local workspace uses the same AcquisitionStudio and ProcessingExperience render path as the production-target app. The fixed-origin bridge supplies actual authorized VPS reads. This is a development integration, not a claim that this UI or the v0.2 engine is deployed.

## Run and review

With Node 24 and the repository's pnpm toolchain on PATH, run `pnpm dev:sales-xray:review` (or `scripts/Start-LocalSalesXrayProductionBridge.ps1 -ReviewOnly`). Open `http://salesxray.localhost:3016/__review/`, sign in normally in the local workspace, and choose an owned call ID or call URL. The controls stay in a separate page. Each captured processing observation opens the actual app with a session-bound opaque fragment selector; the fragment never sets server state. Five report sections use the normal call URL and `section` parameter.

The review launcher blocks analysis mutations before upstream fetch. Login/logout/context changes retain their normal explicit routes. The inner Next process has no independent API rewrite while review mode is enabled. Stop only the tracked pair with `scripts/Stop-LocalSalesXrayProductionBridge.ps1`.

## What the first slice covers

- Current live call/report and its five sections remain actual API reads.
- Opt-in capture retains allowlisted submission/source identifiers and actual processing facts only. Report/transcript text, credentials, profiles, raw audio and provider response bodies are excluded.
- Captured automatic processing observations can be reopened through the shared production renderer. The selected display data never replaces operational React state. Historical action buttons cannot issue commands; the bridge independently denies analysis writes.
- Bounds: 16 local sessions; 128 observations and 16 MiB serialized data per session; 4 MiB response ceiling; 30-minute hard capture expiry, including idle expiry; 30-second authorization lease. Every frame read rechecks the actual source, call and access. Reset, identity/context changes, source changes and denied access purge the affected capture. Late requests are fenced to their original capture epoch.
- Development code is selected only by the explicit webpack development launcher. The normal module is a passthrough. The webpack cache includes the mode so a normal launch cannot supply stale cached modules to a review launch.

## Boundaries

A completed call cannot reconstruct its earlier loading states. Unobserved states are unavailable. This slice does not capture pre-upload file-picker/hash/transfer microstates, manual plan/consent states, past report revisions or every UI interaction. Capturing a progress response is not a recording of all browser-local timing and interaction state. Report-ready observations open the currently authorized live report, never an invented historical report. Account-authenticated real capture still requires signing in normally; no cookies are copied from production.

## Verification

- Node 24: 26 bridge/store/service checks passed, including zero upstream writes for denied processing routes, bounded payloads, cross-session/source/access denial, reset races, a late failed read after a new capture, and idle retention expiry.
- Development-port tests cover strict fragment grammar, source binding, unavailable observations, authorization lease expiration, rejected report/manual-plan observations, and production passthrough with no review fetch.
- A clean isolated production build passed with `AC_SALES_XRAY_REVIEW=1` deliberately inherited. Its emitted server/static JavaScript contained neither the development frame-fetch path nor the development-only validation string/module. Local dev output was not used as production evidence.
- Actual local bridge smoke: health confirmed read-only mode; controls loaded with CSP/frame denial; unauthenticated capture required sign-in; zero page errors and no processing started.
- Browser fixtures intercept every API read before network: completed live data is deliberately different from the selected historical C2/C4/C5/held response. These checks validate the integration/rendering and absence of operational mutations; they are synthetic browser evidence, not authenticated VPS/provider acceptance.
- Final focused frontend run: 94 checks passed. TypeScript, focused ESLint and the final isolated production build passed after adding the development cache-mode key. The emitted production JavaScript again contained no review implementation markers.
- Observed C2/C4/C5/held browser checks passed at 320x568, 375x667, 390x844 and 1440x900. Each selected observation remained distinct from the completed live fixture and issued zero mutations. Short screens intentionally scroll within the shared app shell; the checks scroll to the footer and prove all processing actions remain reachable, at least 44 pixels high, with Privacy & support above fixed navigation. This is not a universal device-compatibility claim.
- The 320-pixel selection initially matched no configured viewport. It is now an explicit case, and the harness fails if the selected run executes no checks. The successful 320x568 rerun produced 12 result records for four states; the earlier empty result is not acceptance evidence.

No paid provider request, production deployment, business setting change, release approval renewal or report-quality claim follows from these checks.
