# Registration browser CI gate

Status: applied in the release integration checkout and independently reviewed.
The focused process, HTTP, report and workflow fixtures passed on Windows. This
follow-up is separate from the frozen course-auth and mobile source checkpoints.
It changes CI/test infrastructure only and has no product, provider, schema,
membership, enrollment, consent-policy or runtime configuration activation.

## Intended gate

The existing application `pnpm validate` command ends with production builds.
Two required steps then install Chromium through the existing locked Python
Playwright 1.58.0 package and run only the three registration browser cases.
The test URL and required flag are scoped to the latter step. Earlier ordinary
pytest invocations may still skip optional browser cases; those skips cannot
stand in for the required gate.

The controller uses the generated learner standalone server, adding only the
normal `.next/static` and `public` assets as the existing Dockerfile does. It
requires fresh asset destinations and a fresh evidence directory. It never
copies UI node_modules, repairs traced dependencies or changes link types,
permissions or ACLs. Node is required to match the existing CI pin, 24.19.0.

The server binds only `127.0.0.1:3181`. A conflicting listener causes failure;
the runner never discovers or kills processes by port. Readiness requires the
owned process to remain live and `/register` to return HTTP 200 with the
registration control, without following redirects. Readiness and test execution
have deadlines. POSIX child sessions and Windows unnamed jobs own their child
trees; the Windows bootstrap waits for job assignment before spawning the
command. Cleanup errors cannot produce a pass. SIGINT/SIGTERM run cleanup.

The pytest subprocess receives an explicit test file and writes a fresh bounded
JUnit report. Success requires exit zero, all three exact case names, and no
skips, failures or errors. Missing Playwright or a missing/noncanonical URL in
required mode fails. The report rejects duplicate/missing cases, stale output,
entity declarations and oversized XML.

Each browser context has no session state and blocks service workers. Requests
outside the selected origin and all mutating methods are blocked and reported.
Only the exact same-origin Google-start GET is intercepted with HTTP 204. No
Google exchange, API server, account creation or enrollment is performed. A pass
would establish production-rendered form readiness and explicit consent fields,
not real Google or email/new-device acceptance.

## Windows standalone failure retained

The preceding root standalone attempt is retained at
`course-auth-root-standalone-20260912T183119Z` in the recovery packet. Node
24.19.0 exited 1 with `EPERM stat` while resolving the copied Next-to-React link.
The original pnpm link has Directory/ReparsePoint attributes; its standalone
copy has Archive/ReparsePoint attributes. Both regular target directories exist
and contain React 19.2.8. Read-only Node inspection resolves the original link
and reproduces EPERM on the standalone link.

Pinned Next 16.3.3 creates traced symlinks without an explicit type while copying
concurrently. Node's Windows implementation infers the type from the output
target and falls back to a file link if inspection fails. The trace lists this
link before its target files. A target-not-yet-copied race is a supported
inference; exact creation timing was not captured. No dependency workaround is
part of this change. The separate `next start` three-case pass does not
supersede the failed standalone gate. Linux standalone startup remains unproved.
The original failure receipt's cleanup field remains unchanged; later process
and port observations must remain separate evidence.

## Validation status and required follow-up

Root independently inspected and applied the five-file follow-up. The first
fixture run produced 34 passes and setup/teardown errors for one oversized XML
case: pytest used its million-character payload as the generated test ID,
exceeding Windows' environment-variable length limit. Explicit short test IDs
corrected the harness without changing payloads or assertions. The fresh rerun
passed all 35 cases in 15.96 seconds, including Windows owned-process cleanup.
Both logs and the successful fresh JUnit report are retained in the recovery
packet as `registration-browser-gate-root-tests[-rerun]-20260913.*`.

The fixture tests exercise a real small stdlib HTTP child, an owned descendant,
success, early exit, a redirect to an otherwise ready endpoint, readiness/test
timeouts, occupied-port preservation, stale/missing/invalid reports and cleanup
failure. Pure contract cases cover required-mode dependency/URL failures,
request blocking and workflow ordering. They create no product data and launch
no Next or browser process.

The exact Linux production build must execute the required gate in CI. The
Windows fixtures establish ownership behavior but do not supersede the earlier
Windows standalone startup failure. Inspect the actual three-case/no-skip
results and cleanup before accepting the release.
Monitor the existing application job's 30-minute budget; the two new steps each
have five-minute bounds, and no unmeasured timeout increase is proposed here.

Deployment/image identity, migrations, backup/scanner readiness, real provider
acceptance and authenticated staging acceptance remain separate release gates.
