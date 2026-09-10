# Local authenticated staging media bridge — implementation evidence

Date: 7 September 2026. Status: bounded transport implemented; independent review and actual authenticated player integration acceptance remain pending. No commits, deployment, VPS writes, provider activation, real-user uploads, or production requests were performed by this subtask.

**Current contract:** the final session-bound registry section below supersedes
the earlier token-in-local-query mapping and logging-only checkpoints. Earlier
failed and incomplete observations are retained as history, not acceptance.

## Cause and chosen boundary

The existing local learner session correctly maps a host-only local HttpOnly handle to an ephemeral server-memory staging session. However, approved activity descriptors contain absolute HTTPS URLs on the staging learner origin. Sending those URLs straight from a localhost `<video>` bypasses the local gateway and does not send staging's host-only session. The gateway also did not allow authenticated media GET/HEAD or forward Range. Its general proxy detached the cancellation timer/listener after headers, which is insufficient for a long media response.

The fix adds a separate progressive-media transport path, not another identity or authorization system. The original descriptor and its HTTPS URL are unchanged. The player must validate that original approved source and its existing grant/expiry envelope first; only the final byte/caption transport is mapped. The gateway still requires the exact configured loopback origin, normal local handle, and existing in-memory staging session. Staging remains responsible for session, tenant, enrollment, activity, binding, version, object, and signed-token authorization.

## Files and integration API

- `apps/learner-web/app/lib/dev-api-proxy.ts` and its existing test: media GET/HEAD allowlist and separate streaming implementation.
- `apps/learner-web/app/lib/dev-media-transport.ts` and its test: canonical URL/key/query and byte-range grammar; pure transport mapping.
- `apps/learner-web/app/components/development-media-bridge.tsx` and its test: scoped client context.
- `apps/learner-web/app/layout.tsx`: resolves the existing server-only bridge configuration and serializes only its non-secret exact browser origin into that context.
- `apps/learner-web/next.config.ts` and `app/lib/dev-media-config.test.ts`: framework URL logging disabled only for a successfully validated opted-in development bridge.
- ADR-029 and the local staging runbook: appended/updated bounded transport contract.

The player owner consumes `useDevelopmentMediaTransport()` from `components/development-media-bridge.tsx`. It returns `{ enabled, resolveUrl }`. `resolveUrl(approvedHttpsSource)` returns a transport URL or null. **Null means withhold media, not fall back to the original URL.** In enabled bridge mode SSR without a current browser origin, an origin mismatch, invalid configuration, unsupported HLS, or an ineligible source returns null. Outside the opted-in development bridge the hook returns the original source and does not activate the bridge. No `NEXT_PUBLIC` bypass flag or global browser authorization object was introduced.

This agent did not edit the player, learner runtime, activity API adapter, captions/quality UI, or descriptor-expiration logic. The orchestrator owns those integration hooks. Profile, Settings, and Notifications stayed frozen.

## Security and streaming contract

| Boundary | Behavior |
| --- | --- |
| Activation | Existing `NODE_ENV=development`, explicit bridge enablement, exact loopback origin, and exact HTTPS staging learner upstream. Production/API/arbitrary upstreams stay rejected. |
| Identity | Existing random HttpOnly local cookie and memory-only staging cookie mapping. No bearer, API-key, raw staging cookie, admin handle, or cross-site media access. Upstream 401/logout invalidates local mapping. |
| URL | Only `/v1/media/playback/` with a canonical fully encoded structured immutable key (at most 512 decoded characters), a single canonical AC-MEDIA token query (at most 4096 token characters), and no credentials/fragment/extra query. Parsing does not authenticate the token. |
| Media | Success MIME restricted to `video/mp4`, `video/webm`, or `text/vtt`. Extensionless original/caption keys remain supported. HLS path suffix and playlist MIME are refused; no manifest or child rewriting occurs. |
| Request headers | Only Accept, identity Accept-Encoding, fixed staging Origin, server-held staging cookie, and optional validated Range. Browser metadata/credentials/conditionals are not forwarded. |
| Range | One canonical `bytes=start-end` or `bytes=start-`; no suffix/multipart/backward/oversized range. Start/end stay within the backend's 8 GiB bound. A 206 response must match requested bounds, total length, and declared byte count. |
| Response | Explicit safe media headers only, private no-store, no-referrer, nosniff. Redirects, compressed/malformed length, unexpected MIME, inconsistent ranges, raw error bodies, provider headers, and credential headers are not returned. |
| Streaming | Backpressure (`highWaterMark: 0`), no whole-video application buffering, 16 MiB maximum accepted chunk, exact declared-length accounting, and sanitized stream errors. |
| Lifetime | 12-second header timeout, 30-second pending-read timeout, and 30-minute whole-response cap. Request cancellation stays attached after headers; response consumer cancellation aborts upstream. Timers/listeners clean up on EOF, error, cancel, or timeout. These caps do not extend the original descriptor's token expiry. |

The backend contract was read in `http/media_delivery.py`, `media/delivery.py`, `media/policy.py`, and `media/signing.py`, plus the descriptor/caption projection in `media/service.py`. `media_delivery.py` explicitly registers both GET and HEAD for the signed delivery route. Normal backend authorization is not changed.

## Verification

Focused Vitest: **68 tests / 4 files pass**, including the existing authenticated proxy tests and new path/query/origin/cookie/header, range, MIME, timeout, byte-count, cancellation-after-headers, downstream cancel, logout/401, SSR/no-fallback, production/default-off, and logging-configuration regressions. TypeScript passes after correcting only test-fixture header-union annotations.

The streaming tests use real Node Request/Response/Web Streams with injected synthetic fetch responses. They prove the adapter's behavior, not live staging connectivity, upload readiness, or playback quality. Assertions verify the upstream body is not pulled before the downstream reader asks for it, and both incoming abort and downstream cancel still abort the upstream signal after headers have been returned.

An actual request to the running `learner.localhost:3100` development media route used **only a synthetic invalid media-token fixture and no cookie**. It returned **401**, `Cache-Control: no-store`. The unique non-secret probe marker had **0 matches before and 0 matches after** in learner stdout/stderr. Only those counts were inspected/emitted; log contents and any real credentials were not copied. No staging byte request could occur without the local session mapping.

Installed Next logging code was inspected before configuring suppression: incoming-request ignore rules do not suppress the separate fetch-warning logger, which can print a full URL. Consequently `logging: false` is used only when the existing bridge config resolves successfully in development. Normal non-bridge development and production logging are unchanged. Invalid opted-in configuration fails rather than silently falling back to an unbridged media URL. Do not enable framework fetch URL logging while using signed local media URLs, and do not export browser network traces unredacted.

Final shared-worktree validation: **609 learner tests / 44 files passed** at 20:34:43 local time (12.27 seconds). Full learner ESLint with zero warnings and learner TypeScript passed. Scoped Prettier and `git diff --check` passed. No screenshot is represented as actual authenticated media playback evidence in this subtask.

## Remaining handoff

1. Independent security/code review of these unstaged/new files.
2. Player integration after existing approved-source and expiry checks, including captions and quality transport; no direct remote fallback for null mappings.
3. Actual authenticated localhost playback/seek/pause/caption checks against already-approved staging media using the normal local sign-in flow. Restart/config reload can clear the memory-only bridge mapping, so a fresh normal login may be required.
4. Keep HLS and provider activation behind their separate reviewed gates. This implementation does not make unapproved/missing lesson media playable.

Reproduction (configured Node 24 runtime):

```powershell
pnpm --filter @ac/learner-web exec vitest run app/lib/dev-api-proxy.test.ts app/lib/dev-media-transport.test.ts app/lib/dev-media-config.test.ts app/components/development-media-bridge.test.tsx
pnpm --filter @ac/learner-web test
pnpm --filter @ac/learner-web lint
pnpm --filter @ac/learner-web typecheck
```

## Independent review correction — Next trace persistence

Status at 20:58 local: **code correction and installed-runtime regression pass;
actual restarted-server HTTP/trace acceptance is pending**. This supersedes any
inference that the prior stdout/stderr-only probe established full token privacy.
It does not erase that earlier run or its observations.

The reviewer sent a synthetic invalid no-cookie token to the actual development
route (401) and triggered batching with 55 anonymous requests. Its unique marker
went from **0 to 2** occurrences in `.next/dev/trace`, while console logs remained
at zero. Installed `next-dev-server.js` attaches `req.url` to handle-request and
memory-usage spans. `trace/report/to-json.js` flushes batches after more than 100
events. `logging: false` does not govern that reporter. No real signed token was
used, and no log/trace file was deleted or exported.

### Correction and exact dependency

- `scripts/Start-LocalStagingBridge.ps1`: sets
  `NEXT_TRACE_SPAN_THRESHOLD_MS=9007199254740991` in only the learner process's
  environment before launching Next; workers inherit it. No global environment,
  admin credential, or production behavior was changed.
- `apps/learner-web/next.config.ts`: retains validated-bridge console suppression
  and rejects enabled bridge startup when the exact trace threshold is absent
  or installed Next is not the reviewed **16.2.11** version.
- `app/lib/dev-media-config.test.ts`: missing/malformed threshold, production,
  disabled bridge, invalid bridge, and simulated unvalidated-upgrade checks.
- New `app/lib/dev-media-trace-privacy.test.ts`: fresh-process test of actual
  installed Next trace/report code, not a mocked reporter. Its negative control
  persists **221** occurrences of an invalid synthetic marker; the guarded run
  has **0 marker occurrences / 0 trace bytes**, after automatic batching and
  explicit flush. Both exercise 110 request spans, 110 child spans, and the
  largest valid span. Child-process threshold inheritance is also checked.

The control is **internal and undocumented**, not a promised public Next API.
Its implementation parses the threshold once at module import. It reports only
when a duration in microseconds exceeds the millisecond threshold times 1000;
durations above `Number.MAX_SAFE_INTEGER` microseconds already throw. The
multiplied cutoff is not claimed to be a safe integer, only finite and strictly
larger than every valid duration. The actual maximum-duration regression proves
that boundary. The managed development launcher remains webpack-based. Replaying
arbitrary externally supplied trace events is not part of this delivery mode.
Upgrade validation must examine tracing again and repeat actual HTTP evidence.

### Validation and local availability

The focused new privacy/config suite passed **15 tests / 2 files** at 20:53:19
local. The complete current learner suite passed **625 tests / 45 files** at
20:55:52 local (24.26 seconds); learner TypeScript and ESLint with zero warnings
also passed. Root's concurrent player integration remains preserved.

The fail-closed config reload had already exited the previous learner process:
tracked PID **23544** was absent and port **3100** had no listener. The tracked
workspace resolved to the intended d2de worktree. A learner-only hidden startup
attempt with scoped child environment was rejected by the execution policy
before execution (`blocked by policy`). No replacement PID was fabricated and
the process record was not changed. The admin server was not stopped or altered.
Previous logs/trace files remain intact.

Consequently **localhost learner is unavailable at this checkpoint**, and normal
local login handles need to be re-established after an allowed restart. Actual
HTTP GET/HEAD/range probes, forced request batching, and before/after marker
counts across trace files and stdout/stderr must pass on the restarted server
before any real signed-media QA. The orchestrator is handling the restart or
required user action. Staging availability is not represented as affected here.

Reproduction of the installed-runtime check (no real credentials or URLs):

```powershell
pnpm --filter @ac/learner-web exec vitest run app/lib/dev-media-config.test.ts app/lib/dev-media-trace-privacy.test.ts
```

## Final correction — opaque local registry and explicit native media upstream

Checkpoint: 21:24 local, 7 September 2026. Implementation, mounted regressions,
installed-runtime privacy regressions, and synthetic running-server HTTP proof
pass. Independent review and actual authenticated approved-media playback remain
pending. This subtask performed no commit, deployment, provider activation,
real-user write, or real signed-media request.

### Further failures retained

1. Next 16.2.11 `start-server.js` has an outer handler catch that unconditionally
   prints the incoming `req.url`, regardless of `logging: false` or the trace
   threshold. The reviewer exercised that installed listener in memory with a
   rejected synthetic handler and observed the synthetic marker. Therefore a
   signed localhost query is not an acceptable privacy boundary.
2. Next's patched fetch/HMR-cache path can execute
   `console.warn('Failed to set fetch cache', input, error)` after a background
   body-read failure. The reviewer exercised real patched fetch without network
   using `cache: no-store`, the maximum trace threshold, and a truncated
   synthetic response; the signed-query fixture marker was logged once. Proxy
   catch blocks and ordinary logging configuration do not cover that background
   execution path.
3. The first inline real-HTTP registry probe could not read active stdout/stderr
   handles with `ReadAllText` sharing. That attempt is **incomplete**, not a pass.
   The durable probe below uses explicit read/write sharing and emits only
   counts. No log or trace was deleted or copied into evidence.

### Replacement boundary implemented

The unchanged approved HTTPS descriptor passes the existing player approval,
scope and expiry checks. The client then sends only a bounded JSON POST body to
the fixed same-origin `/v1/dev-bridge/media` endpoint. The response contains
positional `{ path, expires_at }` entries, never the original URL or token.
GET/HEAD uses only `/v1/dev-bridge/media/{43-character-random-locator}` with no
query. All token-bearing legacy local delivery routes are denied. A locator is
not a credential and cannot resolve without the same valid local HttpOnly
session generation. The registry resides inside that existing memory-only
session object; replacing even an identical staging-cookie value creates a new
generation. An asynchronous POST rechecks generation before adding entries.

Registration bounds: 12 distinct canonical sources, 64 KiB body, 12-second body
timeout, 30 attempts per minute per session, 64 entries per session, eight
sessions. Source metadata rejects wrong origins, credentials, HLS, ambiguous
keys/queries, malformed scope fields, non-playback tokens, key mismatch,
expired/unsafe timestamps, more than 30 seconds future clock skew, and a grant
envelope longer than one hour. This parses untrusted metadata to withhold; it
does not verify signatures or grant access. Registry expiry cannot exceed the
original grant or local session. Logout, upstream 401, session replacement,
eviction, expiry and restart discard associated entries. Atomic additions and
bounded deduplication avoid partial or unbounded registration state.

The async hook aborts on scope change/unmount, gates every result by request
scope and current original expiry, bounds JSON responses to 16 KiB, and removes
the native source when expiry occurs. Pending, failed, malformed, unauthorized,
or stale registration never falls back to the original remote URL. Video and
captions use registered paths. Quality mapping is preserved when approved
quality sources are supplied; no new rendition policy or quality capability is
claimed. Reconnect first uses the existing activity API to revalidate the same
original authority scope, then invalidates/re-registers the local transport;
it stays paused and requires normal learner action to resume. No canonical
progress/evidence writes were added by registration or recovery.

Media upstream calls now use the explicit server-only
`fetchDevelopmentMediaUpstream` adapter from `dev-media-upstream.ts`, implemented
and separately tested by the performance agent. It uses stable Node HTTPS,
never captured or patched global fetch, and validates exact staging source,
GET/HEAD, required abort signal, one server-held staging session cookie,
identity encoding and the safe header/range allowlist. It follows no redirects,
performs no decompression/caching, strips provider/cookie/location headers,
sanitizes native errors, and keeps cancellation active through body consumption.
The Node-to-Web bridge uses a 64 KiB byte-size high-water mark and zero-buffer
outer stream. The existing gateway still applies MIME, exact content length,
8 GiB bounds, Range consistency, backpressure, header/read/total timeout and
sanitized stream errors. A default-wiring regression proves **zero global-fetch
media calls** while ordinary JSON API traffic keeps its previous global fetch
path. Trace suppression/version fencing remains defense-in-depth.

### Tests and running-server proof

- Complete learner suite: **664 tests / 47 files passed**, started 21:24:05 local,
  12.99 seconds. Full learner TypeScript and ESLint with zero warnings passed.
- Native upstream adapter: **20 focused tests passed**. The no-network installed
  patched-fetch negative control emits the synthetic marker once; the native
  truncation case has zero global fetch/console calls and generic errors.
  Repeated bridge draining without downstream consumption proves no more than
  **128 KiB synthetic buffering**, not eager MiB buffering. This is adapter
  test evidence, not actual VPS throughput or browser startup timing.
- Registry tests cover cross-session/no-session denial, legacy/query rejection,
  exact Origin/credential/JSON gates, metadata/TTL, all bounds, replacement while
  POST is pending, invalidation and body cancellation.
- Mounted **real `VideoViewer` component** tests cover pending withholding,
  progressive/caption paths, unchanged original descriptor, stale activity
  completion, unmount, 401, malformed/expanded response, expiry, StrictMode's
  cancelled first setup, reconnect re-registration with no writes, existing
  tracked completion, and production default-off behavior. These use isolated
  synthetic API/envelope/transport fixtures, not real account authorization.

The orchestrator completed a fresh managed restart after the earlier policy
denial; localhost learner on 3100 and admin on 3101 were healthy. The actual
running learner was then tested using:

```powershell
pwsh -NoProfile -File scripts/Test-LocalMediaPrivacy.ps1 -LearnerPort 3100
```

Result: anonymous synthetic-source POST **401 / no-store**, opaque GET and HEAD
with a bounded Range **401 / 401**, followed by **55/55 anonymous `/v1/me` 401s**.
No cookies were sent. Before and after, the unique synthetic POST-body marker
had **0 occurrences across 3 active diagnostic files**; total inspected bytes
were **15,726 before and after**. The script returned `passed: true`. It did not
read/export credentials or raw log contents. The anonymous probe cannot reach
upstream bytes and is not a successful media-playback claim.

### Review handoff and remaining acceptance

Owned registry changes are in `dev-api-proxy.ts`, `dev-media-transport.ts`, their
tests, new `dev-media-registry.test.ts`, `development-media-bridge.tsx` and tests.
The orchestrator-authorized minimal `VideoViewer` integration and mounted tests
were extended for async registration/reconnect without editing existing
descriptor authority checks. The performance agent owns the new native
upstream adapter and its tests. Layout, validated config and launcher privacy
guards remain from the prior checkpoint. Settings/Profile remain frozen.

Independent review must clear this complete boundary before real signed-media
QA. Then normal local sign-in plus an already-approved staging lesson must prove
actual play/pause/seek/caption/control behavior and sanitized byte/range evidence.
HLS rewriting, provider activation, missing lesson-media approvals and production
deployment are not accomplished by this development-only registry.

## Independent native-diagnostics finding and closure — 16:10 UTC

The completed review found one additional Important sink: Node 24 native HTTPS
diagnostics print a request's signed path and session cookie when inherited
`NODE_DEBUG=https`, `http,https` or wildcard masks enable that category. Synthetic
fresh-process probes destroyed the request before sending it and reproduced
both markers on stderr. Sanitized transport errors cannot cover this earlier
native diagnostic. No real credential or signed media was used.

The managed launcher now clears `NODE_DEBUG` only in the learner child before
Node starts; it does not alter the workstation or admin environment. Enabled
bridge config and the media adapter also call a shared guard before constructing
requests. The guard uses the public `util.debuglog(...).enabled` state for both
HTTP/HTTPS to detect Node's cached bootstrap mask, even when an environment
value is cleared before application import, and also rejects an unsafe current
mask using Node's exact case/wildcard/comma matching semantics. Ordinary
non-bridge development and production configuration keep existing behavior.

Fresh-process negative controls reproduced the native sink; guarded controls,
including a pre-import environment clear, emitted zero token/cookie markers.
The native adapter test confirms the request function is never called when the
guard rejects. Tests do not invent a blanket ban on unrelated diagnostic flags.

Final root validation: **697 tests / 48 files passed** in 13.39 seconds, started
21:40:06 local; full learner ESLint with zero warnings and TypeScript passed.
Independent review retested **187 tests / nine bridge files**, TypeScript and
scoped diff checks, and reported no remaining Critical, Important or Minor
findings. The prior review's Important finding is resolved, not omitted.

The code is cleared for merge, not for an authenticated-playback acceptance
claim. The managed startup settings still need to be applied before that QA;
normal sign-in, approved source delivery, GET/HEAD/206 seek, captions, playback,
reconnect/expiry and safe diagnostic observations remain live gates. The
anonymous 401 proof above remains accurately limited to rejection behavior.

## Merge and managed-runtime verification — 16:16–16:22 UTC

PR #42 passed exact candidate Application validation `34142421351` and
Control-plane validation `34142421368`, then merged at 16:22:09Z as
`ec0009ec0ea0333d7cfa266d2c353d07ddaf1268`. The same implementation worktree
integrated main without discarding its unrelated files.

The managed pair was stopped through its PID/start-time-verified controller;
old logs were retained in a private ignored timestamped directory. The normal
launcher restarted localhost only. Both health checks passed, with learner
3100 and admin 3101 bound to loopback; memory-only sessions require normal
sign-in again. Staging was not restarted by this local operation.

The final running learner passed `Test-LocalMediaPrivacy.ps1`: synthetic
anonymous registration 401/no-store, opaque GET/HEAD 401/401, 55/55 anonymous
identity requests 401. The marker remained **0 before and after across three
diagnostic files**, with **15,393 inspected bytes unchanged**. This supersedes
the earlier startup-pending status and does not turn denial evidence into a
successful media-playback claim.

## Native-diagnostics guard revalidation — 8 September 2026

The original HTTPS diagnostics correction is already present in the current
tree: the managed staging launcher clears the learner child's `NODE_DEBUG`
before startup, and both private-media configuration and the upstream adapter
invoke the shared privacy guard. Existing follow-up work also covers NET/TLS
diagnostics and local-sandbox startup. These implementation changes were
preserved during this bounded revalidation.

The first focused run found six stale configuration assertions expecting the
old "native HTTP diagnostics" message after the guard changed to "native network
diagnostics". The test-only correction updates those assertions, verifies NET/TLS
and wildcard masks on direct bridge startup, verifies direct local-sandbox
startup rejection, permits unrelated `fs` diagnostics, and explicitly isolates
the sandbox environment between cases.

On Node **24.19.0**, **140 tests / four files passed** at 02:00:52 local time:
`dev-media-native-privacy.test.ts`, `dev-media-config.test.ts`,
`dev-media-upstream.test.ts`, and `dev-api-proxy.test.ts`. Existing fresh-process
negative controls reproduce the synthetic native sink; guarded controls reject
unsafe startup, including Node's cached bootstrap mask after the environment is
cleared. Scoped ESLint (zero warnings), formatting, and diff checks passed.
No real credentials, signed requests, log contents, process restarts, or
deployments were used. This result
does not add live playback or running-process acceptance evidence.
