# Authority Closers — Media Provider Foundation Evidence

**Worktree branch**: `codex/media-provider-v01`
**Date**: 2026-09-04
**Capability gate**: `AC-GOV-AUD-001` / `GAP-MEDIA-001`
**Status**: bounded foundation only; provider activation is not claimed

## Delivered boundary

This slice adds a provider-neutral media foundation around the existing media
contracts and SQL lifecycle. It is intentionally inert: staging and production
application composition rejects enabled provider settings and injected media
runtimes, and does not mount a provider callback route. This repository has no
activation issuer or in-process seal. An immutable, externally attested
activation boundary is a later gated slice; governance references below are
evidence only and cannot activate a provider here.

- `media/config.py` validates environment/settings input, private S3/MinIO
  endpoint and bucket fields, exact approved endpoint hosts (rejecting
  loopback/link-local/private/unapproved targets), and provides the
  composition-time public DNS answer/rebinding check, exact HTTPS delivery/CORS
  origins, short-lived TTLs, quotas, range policy, and activation references.
  Disabled or unapproved input remains fail-closed; references alone never
  select a provider.
- `media/storage.py` keeps the S3-compatible provider transport unavailable in
  this slice. The provider SDK is not imported and credentials are not passed;
  default and unapproved provider compositions remain
  `UnconfiguredPrivateObjectStorage`/unavailable.
- `media/scanner.py` keeps the existing fail-closed scanner default and adds a
  metadata/checksum-bound local signature scanner alias; it does not claim
  malware-provider activation.
- `media/processing.py` defines bounded profiles and quotas, deterministic
  local/test HLS multi-rendition manifest metadata, caption passthrough, and an
  injected FFmpeg command boundary. Test bytes are explicitly fixtures and are
  not a playable-video claim.
- `media/lifecycle.py` provides append-only supersession/retirement hooks and
  a deletion worker that consumes due lifecycle events scheduled by an
  explicit retention policy. Object references are tenant-key validated and
  completion is replay-idempotent; failed output cleanup is represented by a
  retryable lifecycle event/hook, while the in-memory hook is test evidence
  rather than a durable production outbox. The worker never deletes canonical
  SQL history.
- `media/policy.py` provides short-lived HMAC application-route delivery URLs,
  exact-origin CORS, and single-byte-range policy representations. The service
  never calls a storage adapter's direct read-URL method and remains unavailable
  because no app delivery route is composed in this slice. URLs contain no
  provider credentials and are tenant/session bound through the
  existing opaque authorization context.
- `media/telemetry.py` provides a bounded exporter port, in-memory test sink,
  and a best-effort local JSONL exporter (not a durability guarantee). Events
  exclude object keys, URLs, tokens, and learning progress; exporter failures
  are fail-soft by default.
- `media/service.py` preserves tenant-scoped processing, idempotent rendition
  identity, caption supersession, and lifecycle hook boundaries. Source,
  rendition, caption, avatar, HLS playlist, and segment objects are verified
  for metadata/checksum/aggregate-byte bounds and offered to retention hooks
  through a bounded inventory; failed-worker cleanup records a retryable
  lifecycle event/hook when prefix listing/deletion fails and does not claim
  durable completion without a production outbox. Runtime composition in
  `media/runtime.py` supplies
  fail-closed scanner/processor defaults and maps validated limits into the
  service/worker boundary.

## Evidence executed

From the repository root, using the checked-in `uv` project environment:

```text
uv run pytest -q tests/unit/media/test_provider_foundation.py tests/unit/media/test_media_service.py tests/unit/http/test_app_composition.py
107 passed, 1 warning (StarletteDeprecationWarning from the installed FastAPI/httpx compatibility seam)

uv run pytest -q tests/unit/media/test_media_service.py tests/unit/media/test_provider_foundation.py tests/unit/http/test_app_composition.py tests/security/test_http_boundary.py tests/unit/http/test_operations_routes.py
145 passed, 1 warning (StarletteDeprecationWarning from the installed FastAPI/httpx compatibility seam)

uv run pytest -q tests/unit/media tests/unit/application/test_settings.py tests/unit/http/test_app_composition.py
263 passed, 1 warning (StarletteDeprecationWarning from the installed FastAPI/httpx compatibility seam)

uv run ruff check packages/python/ac_platform tests
All checks passed

uv run mypy packages/python/ac_platform
Success: no issues found in 117 source files

git diff --check
passed

uv run pytest -q tests/unit
755 passed, 1 warning (StarletteDeprecationWarning from the installed FastAPI/httpx compatibility seam)

uv run pytest -q tests/security tests/integration
32 passed, 92 skipped (PostgreSQL integration URLs were not configured)

uv run pytest -q tests/database
75 passed, 21 skipped (PostgreSQL database URLs were not configured)
```

The focused tests cover disabled composition, non-local rejection of enabled
settings and injected runtimes, reference-only inert composition,
private/unapproved endpoint rejection, incomplete and deployment-insecure
configuration, DNS SSRF/rebinding rejection, HLS ladder/playlist/segment
inventory and caption passthrough, quota rejection including authoritative
caption bytes, caption provenance/checksum binding, prefix cleanup after a
processor fails before returning, retryable cleanup lifecycle events, FFmpeg
command safety and bounded worker stderr/temp files, preflight workspace
budget reservation, validated measured video duration for READY/playback and
heartbeat, exact upload-intent path/query/header checks including SigV4 `host`
signing, verified caption-copy
head metadata, URL expiry and tenant binding, CORS/range rejection,
tenant-key validation and replay-idempotent retention scheduling,
timestamped/body-bound webhook signatures, absent provider webhook mounting,
and telemetry redaction/fail-soft behavior.

## Explicit non-claims and remaining gates

- No S3/MinIO credentials are present in the repository, logs, tests, or docs.
- No staging or production provider is activated, contacted, or provisioned.
- The provider webhook HTTP route is not mounted. Inbox-first raw-envelope
  persistence, quick acknowledgement, and asynchronous worker processing are a
  later gate; direct local/test service callbacks are not a public capability.
- `GAP-MEDIA-001` remains open: approved media/caption source, provider limits,
  immutable externally attested activation approval, retention/resumability
  decisions, a reviewed app delivery route/session/grant handler, and real
  processing evidence are still required before activation. No deployment
  composition in this repository can satisfy that approval today.
- The local/test activation verifier is only a compatibility seam for direct
  unit tests. It is not an issuer, seal, or production authorization mechanism;
  non-local app/runtime composition rejects it and provider activation remains
  unavailable.
- Any future public provider callback must require a fresh timestamped,
  body-bound signature. The current direct service helper retains a legacy
  raw-body form only for trusted local/test callers; no HTTP route accepts it.
- The local transcoder writes deterministic fixture-shaped HLS objects; it does
  not establish codec, audio, playback, CDN, or live-streaming support.
- The FFmpeg adapter is an injectable worker boundary. Running FFmpeg against
  real media, scanner activation, CDN setup, and provider recovery evidence are
  intentionally outside this slice.
- Cleanup retry events are lifecycle hooks with an in-memory test sink here; a
  durable transactional outbox/retry worker must be supplied and reviewed
  before cleanup durability can be claimed.
- Media telemetry is observational only. It cannot create canonical playback,
  progress, completion, payment, or access state.
