# Approved read-only lesson playback — 2026-09-07

## Scope and authority

Implemented only in `apps/learner-web/app/components/learning-loop-runtime.tsx`,
with a new mounted interaction test and this evidence/isolated browser harness.
The root owner's shared heading, `labelledBy`, compact unavailable/blocked
notices and existing presentation tests are preserved. No API contract, CSS,
proxy, runtime flag, deployment, provider, upload, account or progress state was
changed. The workflow implementation skill guided mounted behavioral testing
and the explicit separation between local playback and canonical completion.

Read authority: `http/learning.py` `_allowed_actions`, `install_learning_http`,
`get_activity` and conditionally registered playback mutation routes;
`media/service.py` learner descriptor delivery; `media/signing.py` and
`media/policy.py` fixed application delivery envelope. An approved descriptor
does not imply that `complete_video` or the Watch policy exists.

## Capability contract

- `available` / `in_progress` VIDEO plus an approved, playable server descriptor
  and valid bounded application delivery metadata may open read-only playback.
  Visible copy: “Playback only — progress is not recorded for this lesson.”
- `complete_video` retains the existing tracked start → heartbeat → finish →
  authoritative activity refresh → evidence submission flow. Both post-start
  and pre-submit activity reads now reject a changed capability/context.
- Explicit local media props cannot open read-only playback or override a server
  blocked/unavailable descriptor. The pre-existing explicit adapter remains
  usable only without a server descriptor and with `complete_video` already
  authorized. Other activity kinds, locked/completed states and malformed or
  unavailable delivery fail closed.
- Mode, activity/enrollment/catalog version, binding/media version and source
  identify one player instance. Replacement/unmount invalidates old epochs and
  pauses playback; expiry/denial additionally clears buffered media. The central canonical-write guard is always false in
  read-only mode and after unmount. No playback event, retry, seek, reconnect,
  native end, visibility event or cleanup can create read-only learning writes.

## Exact delivery constraints for the next bridge slice

The native player consumes only a separately supplied `delivery.progressive_url`
with descriptor content type `video/mp4` or `video/webm`. `delivery.protocol`
may be `progressive` or HLS-primary with that progressive fallback. The primary
`manifest_url` is never loaded. Absolute HTTP(S) source parsing rejects userinfo,
manifest-like paths/query markers, and percent-decoded manifest paths. There is
no HLS adapter, automatic bitrate switching or derived rendition URL.

Read-only application expiry parsing is narrower:

- URL <= 8192 characters; absolute HTTPS; no username, password or fragment;
  path starts exactly `/v1/media/playback/`; exactly one `token` query value.
- Token <= 4096 characters; fixed `AC-MEDIA.<base64url JSON>.<43-char base64url>`
  envelope. This is bounded metadata inspection, **not signature verification**.
- `typ=AC-MEDIA`, `token_type=playback`; safe-integer nonnegative `iat`, later
  safe-integer `exp`, lifetime <= 3600 seconds, `iat` no more than 30 seconds in
  the future. Expired or invalid expected application metadata denies playback.
- Activity ID/version, asset/version, binding and enrollment match the server
  descriptor/current activity. A nonempty delivery grant ID is required. The
  key is a string <= 2048 characters and must equal the decoded path suffix.
- These checks only restrict the server-provided capability. The authenticated
  byte endpoint still verifies the signature, current session/person/tenant,
  enrollment/entitlement and approved binding on each request. No token is
  logged, persisted, projected as progress or sent to a learning mutation.

Captions preserve the existing server-issued ready captions/subtitles source
URLs and language labels; retired rows are excluded and missing lists are safe.
Caption URLs are neither derived nor bridged. Signed video expiry stops the
whole player, including its caption tracks. No caption/HLS transport adapter
has been added or activated.

## Expiry and recovery

The bounded expiry timer pauses and clears `src`/buffered media, then requires
reopening through the module. Offline invalidates the epoch and stops playback.
Reconnect reads the activity before allowing resume; changed source/grant,
scope or mode, and 401/403/404 denial, remove the player and require reopening.
Network failures remain retryable. A media-element error does not expose HTTP
status, so retry must refresh the descriptor before loading again. Read-only
never offers “Retry server save”. Late tracked start/finish results cannot
submit into a newer read-only/unmounted context.

Native `playing` restores the playing state after genuine buffering. Normal
`suspend` (browser stopped fetching) is no longer mislabeled as buffering.

## Verification

Focused tests run on bundled Node 24 / pnpm / React 19 / Vitest happy-dom, with
native media methods mocked only in the mounted unit tests. The command is:

```text
pnpm --filter @ac/learner-web exec vitest run app/components/learning-loop-runtime.test.tsx app/components/learning-loop-playback-interaction.test.tsx
```

Acceptance covers native/custom play, time updates, pause, seek, end, unmount,
reconnect, retry, expired/invalid metadata, explicit-prop non-escalation,
401/403/404 denial, stale refresh/start/finish, native buffering recovery and
the existing tracked completion flow, including Strict Mode effect replay.
Final focused result: **50 passed** (31 mounted + 19 existing), 2.73 seconds.
Scoped ESLint, learner typecheck and formatting passed. Ruff for the evidence
harness passed; `git diff --check` is recorded with the final handoff.

Browser harness: `uv run python docs/evidence/qa_alpha_read_only_player.py`.
It launches fresh headless Chrome contexts against existing local development
UI at `http://learner.localhost:3100`, blocks all real API writes/external
requests, and supplies synthetic read descriptors/envelopes. Reviewed local
Caminandes MP4 bytes are fulfilled in-process, not uploaded or fetched from a
live media endpoint. Four serial cases cover 320/dark, 390/light, 390/dark and
1440/light, native decode/clock advancement/end, no horizontal overflow, zero
attempted mutations and reconnect denial removing the player.

The first run (`run-20260907T144121Z`) passed all four behavioral cases and
decoded 1920×1080 / 12.032 seconds, but is **superseded for theme evidence**:
browser color scheme alone did not set the app preference. Its early-frame
captures also exposed the normal-suspend buffering label. Follow-up development
iterations caught a source-clearing Strict Mode replay issue (fixed and tested)
and a harness callback-signature issue: Playwright passed its Request into a
default `source` argument, so the local media fixture returned 404. The harness
now uses a factory returning a one-argument route callback. Neither failed
attempt is claimed as a passing browser run. The final harness
explicitly sets/asserts the app theme and captures after clock advancement.
No screenshot/report contains an actual session or signed production URL.

### Accepted browser evidence — four cases across two runs

- `screenshots/alpha-read-only-player-2026-09-07/run-20260907T145242Z/`:
  320/dark, 390/light and 390/dark each completed decoded 1920×1080 / 12.032s
  playback, native end, zero attempted writes, no horizontal overflow and
  synthetic reconnect 403 removing the video. Playing/denied PNGs exist for
  all three. This is a **partial run, not a successful aggregate JSON report**:
  the fourth case timed out waiting for dev-server `networkidle` before player
  execution. Earlier seek-after-screenshot timing was also corrected so an
  already naturally ended clip is not sought backward while still paused.
- `screenshots/alpha-read-only-player-2026-09-07/run-20260907T145556Z/report.json`:
  the remaining 1440/light case passed independently, **1 case / 0 failures**,
  with the same playback/end/denial assertions. Its two PNGs are alongside the
  report. Navigation uses DOMContentLoaded plus the exact mounted player-ready
  locator rather than waiting for an HMR development server to become idle.

Thus all four cases have passing behavioral evidence, at the distinct times
above; no fictitious single-run 4/4 report is asserted. A redundant all-case
rerun was canceled before this desktop-only completion. Current source is
frozen for the root owner's subsequent transport integration. Independent
reviewer reported no Critical/Important findings and 111/111 across the broader
player/presentation/shell focused suites. Final scoped diff check is clean.

## Known delivery gap / not claimed

Authenticated localhost-to-staging media is **not enabled or proven**.
Descriptors currently retain absolute staging HTTPS URLs; a loopback host-only
bridge handle is not the staging session cookie. The development authenticated
bridge allowlist has no `/v1/media/...` capability and its forwarded headers
omit `Range`. This change intentionally does not rewrite signed URLs, copy
cookies, widen the proxy or weaken same-origin/session verification. The next
bridge slice must also account for this player's strict HTTPS delivery metadata
parsing: a naive rewrite to an HTTP loopback URL will fail closed.

Browser fixture playback proves native MP4 decoding and the mounted UI, not
server signature/session authorization, staging release readiness, ABR/HLS,
native-app behavior, production performance or canonical completion activation.
