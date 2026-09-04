# Media vertical slice implementation evidence

Status: implementation evidence only. Provider activation, provider callbacks,
external storage, CDN/live playback, and production deployment remain
unavailable in this slice.

This record supersedes earlier wording that described mounted callbacks or a
durable provider inbox. Those capabilities are not implemented here and must
not be inferred from service seams or tests.

## Implemented, bounded seams

- `ac_platform.media` owns tenant-scoped asset/version state, upload intents,
  checksum and MIME verification, quota reservations, supersession, private
  rendition metadata, caption/transcript objects, playback grants, and resume
  state.
- HTTP composition keeps actor and tenant scope on the authenticated
  transaction and does not accept identity from request fields or headers.
- Upload completion treats caller duration as untrusted metadata; it never
  makes that value the canonical version duration.
- A video can become READY only when a local/test processor supplies a finite,
  bounded duration measured by that processor. The test copy adapter's default
  is a deterministic fixture measurement; opting out leaves the video
  non-READY. Provider-declared duration is not accepted.
- Worker source, output, caption, HLS graph, file-count, stderr, head-work, and
  temporary-disk limits are bounded. Temporary-disk reservations use an atomic
  process ledger and release reserved bytes as measured workspace files become
  real; failed cleanup is surfaced to a retryable lifecycle hook.
- HLS validation follows only private relative playlist references and tracks
  playlists and segments in the returned object inventory. It performs no
  network or provider fetch.
- Generic upload intents accept only the bounded local token/header contract.
  The future S3-compatible adapter requires the exact approved SigV4 query,
  credential scope, timestamp, the required `host` plus upload signed-header
  set, upload headers, host/path, expiry, and resolver-owned endpoint answer
  set.

## Explicitly unavailable gates

- The provider webhook route is unmounted. Inbox-first raw-envelope
  persistence, quick acknowledgement, and asynchronous worker processing are
  required before it can be exposed. The direct provider READY service seam
  also rejects provider-terminal READY until a separate internal measurement
  path exists.
- Staging and production composition reject enabled provider settings and all
  injected media runtimes/dependencies. Local/test seams are contract-test
  adapters only. No in-process literal seal or issuer can create immutable
  activation; an externally attested boundary is a later gated slice.
- No provider SDK client, credential-bearing transport, DNS peer binding,
  signed application delivery handler, session/grant/CORS/range route, CDN,
  recording, scanner, or live playback path is activated by the default app.
- Lifecycle cleanup signaling is retryable in the current service seam; this
  record makes no claim of durable production outbox/inbox persistence or
  complete cleanup while a storage deletion remains unavailable.

## Verification

Counts are refreshed with the current worktree before review. PostgreSQL
integration/database checks remain skipped when no safe configured PostgreSQL
test URL is available; no deployment or provider contact was performed.

- Focused media/provider/service/composition tests: `107 passed, 1 warning`
  with `uv run pytest -q tests/unit/media/test_provider_foundation.py
  tests/unit/media/test_media_service.py tests/unit/http/test_app_composition.py`.
- Extended media/settings/boundary tests: `263 passed, 1 warning` with
  `uv run pytest -q tests/unit/media tests/unit/application/test_settings.py
  tests/unit/http/test_app_composition.py`.
- Full unit suite: `755 passed, 1 warning` with `uv run pytest -q tests/unit`.
- Security and integration suites: `32 passed, 92 skipped` with
  `uv run pytest -q tests/security tests/integration`; skips are PostgreSQL
  cases because no safe configured test URL was available.
- Database suite: `75 passed, 21 skipped` with `uv run pytest -q tests/database`;
  PostgreSQL cases were skipped because no safe configured test URL was
  available.
- Ruff: `All checks passed`; mypy: `Success: no issues found in 117 source
  files`; `git diff --check`: passed.

The detailed foundation evidence is recorded in
`docs/evidence/MEDIA_PROVIDER_FOUNDATION_IMPLEMENTATION_EVIDENCE.md`.
