# Disposable localhost access and video runtime

Date: 2026-09-07; runtime validation continued on 2026-09-08. Worktree: `C:\Users\Suyash\.codex\worktrees\d2de\authority-closers-platform`.

## Boundary

Local coding/testing only. No push, CI run, staging/production deployment, real account grant, provider activation, operational SQL repair, or official progress/scoring change was performed for this slice.

`development/seed.py` continues to reject everything except the explicitly acknowledged `ac_runtime` connection to `127.0.0.1:55432/ac_local_sandbox`, with external side effects held, fake mail, no media provider, and no inherited libpq overrides. The existing `ac_platform` database is preserved. Only the three existing `@ac.localhost` synthetic identities qualify.

## Implemented fixture commands

- Real password authentication, persisted five-minute admin session, canonical academy selection, and session revocation before returning. No setup token is printed or stored outside canonical hashed session state.
- Canonical first-manager bootstrap and exact program-scoped `catalog_read`, `catalog_write`, `catalog_publish` grants for the synthetic coach. Coach membership remains `learner`; no tenant-wide or global catalog grant is created.
- One tenant-owned synthetic Studio draft, created through `AsyncCatalogApplication`, without fabricated content-review/publication evidence. Replays preserve subsequent UI content/title edits.
- Exactly two fictional eligibility facts for the synthetic learner/coach and the package-owned published technical film version. The notice explicitly says these are not evidence about real learners.
- Canonical audited `ManualEnrollmentGrantCommand` calls; normal free-course self-attestation remains restricted to the foundation course. Session-linked fixture audits supplement the canonical immutable enrollment provenance.
- Stable intent IDs; changed eligibility, changed identity/ownership, revoked coach grants and revoked enrollment/entitlement state are refused rather than repaired. Failed access setup rolls back its savepoint.

The parent independently reviewed these commands before local application, with no Critical/Important finding.

## Actual disposable PostgreSQL proof

The initializer was applied successfully using the pre-existing DPAPI-protected synthetic-account credential. Existing `sandbox.json` was preserved until successful completion, then augmented with Studio program `a980466f-9152-57df-ac31-6bb9ab5f0471`.

Independent read-only verification returned:

- Database `ac_local_sandbox`, role `ac_runtime`, migration `20260907_0019`.
- Two active manual film enrollments and two explicitly synthetic eligibility facts.
- Coach role `learner`, with precisely three grants scoped to the single Studio program.
- Tenant-owned Studio version remains draft.
- All fixture setup sessions revoked.
- Both academy and operations audit chains valid.

## Runtime failures found by actual HTTP testing

1. Media authorization loaded the complete technical prerequisite graph, but the fixture resolver accepted only two VIDEO rows and rejected its four non-video rows. The resolver now validates all six exact package-owned activity definitions. Media binding/descriptor/byte delivery remains limited to the two approved films.
2. Local signed delivery accepted an HTTP loopback origin, but the lower `EphemeralMediaUrl` value contract and byte-request reconstruction rejected it. An explicit default-false loopback-only construction flag is now propagated through issuance and verification. Default HTTP rejection, HTTPS behavior, credential/fragment/invalid-port checks remain intact.
3. The local native streaming bridge used chunk-count queue sizing. It now uses a 64 KiB byte-sized queue, bounded declared/observed bytes, independent inactivity/total deadlines, cancellation teardown and sanitized stream/API errors. It never uses Next's patched fetch for signed media.
4. The installed Next adapter constructs the internal request URL from its loopback bind address. The media bridge now accepts only the two exact internal bind origins when the browser Host is exactly `learner.localhost:3100`; a forwarded host cannot turn an unknown origin into authorized local access. Unknown hosts, ports, schemes and forwarding disagreement remain denied.

Acceptance clients disable inherited HTTP proxies and avoid assertion output containing credentials or signed manifest content. Signed-media access logging/tracing remains disabled in the reviewed managed local launchers.

## Validation

- Synthetic identity/access unit suite: **30 passed** (real SQLite relational constraints, commands, provenance and audit; not PostgreSQL concurrency proof).
- Enrollment/authorization/catalog/film-import regression run before the final three negative assertions: **193 passed**.
- Full-graph and URL-contract focused media regression: **80 passed**.
- Complete media and synthetic-account regression suite: **403 passed**, with one existing Starlette/httpx deprecation warning.
- Native local streaming/privacy/presentation tests: **60 passed**.
- Actual PostgreSQL fixture commands and read-only verification: passed as above.
- Actual HTTP byte acceptance: **passed against both direct API and learner Next proxy**. Normal password login; approved descriptor for each of the two films; MP4 Range 206 with verified header bytes; HEAD with no body; HLS master, variant and MPEG-TS segment bytes; anonymous delivery denied; normal logout. Learner-proxy acceptance passed again after the synthetic credential rotation below.
- Scoped Python Ruff and learner helper ESLint checks passed. Learner full typecheck reached an unrelated concurrently edited Practice Arcade test callback type error; no media/helper error was reported by that run.
- Separate browser decoding/control verification subsequently passed in the
  projection agent's `scripts/verify-local-video-playback.mjs`: decoded
  3840×2160 video, 48 presented frames and 1.458 seconds of advancing playback;
  seek, captions and fullscreen passed. Evidence:
  `screenshots/local-video-playback-20260908/01-paused-decoded-frame-desktop.png`.
  Newly changed custom speed controls remain a separate follow-up; these results
  do not establish official Watch completion or production playback.

## Local login incident containment

During a separate browser check, submitting a password form before hydration triggered native GET form navigation. The parent and admin agent corrected their respective forms to use POST and disable inputs until hydration.

Only the three exact synthetic `@ac.localhost` accounts were rotated through the canonical password-reset service. The transaction authenticated the replacement credential and verified **zero unrevoked sessions** afterward. The new credential was installed into the existing local DPAPI-protected credential file; the invalidated predecessor remains encrypted, never printed. No real account was modified.

A read-shared scan checked all seven direct `.tmp/local-platform/*.log` files and both Next development log files for the invalidated password, URL-encoded and double-encoded forms, plus sensitive query-value patterns. **Nine files checked; zero matching values.** The two `.next/dev/trace` files were absent. No log content needed rewriting or deletion and the running local pair was not interrupted.

No production-readiness, official Watch-completion or full course video availability
claim is made. Browser playback evidence applies only to the exact synthetic
local technical-film course described above.
