# Authority Closers — Media Delivery Phase 2 Evidence

**Worktree branch**: `codex/media-delivery-phase2`
**Base commit**: `a23c93e6acebb7c6a0d31de1c3d5d7374f53be92` (`origin/main` after the final clean rebase)
**Date**: 2026-09-04
**Capability gate**: `AC-GOV-AUD-001` / `GAP-MEDIA-001`
**Status**: bounded application-delivery seam only; provider activation is not claimed

## Delivered boundary

This slice adds an explicit, provider-neutral application front door for
private media. It can be exercised with the existing in-memory test adapter,
but the shipped application does not compose it by default.

- `media/storage.py` extends the private storage port with bounded
  `iter_range()` streaming. The in-memory adapter supplies deterministic test
  chunks, while the dormant S3-compatible adapter defines a peer-checked
  `Range`/stream contract and closes the provider body. No provider SDK or
  credential-bearing transport is activated.
- `media/delivery.py` verifies the existing application HMAC token, exact
  tenant/session/activity/media-version/object-key binding, expiry and grant
  lifetime, checksum/length/MIME metadata, per-issued-URL range capability,
  and an explicitly injected server-owned grant authorizer. It emits private
  no-store/`nosniff` headers, exact-origin CORS, `HEAD`, and one bounded
  progressive byte range. Streamed responses enforce the declared byte count,
  configured chunk bound, full-object checksum where available, and a
  post-stream object-version/checksum/content-length/MIME identity check.
- HLS playlists are read only within the verified private rendition namespace.
  The existing bounded HLS inventory validator is reused; every relative
  playlist/segment and supported `URI="..."` reference is rewritten to a
  fresh application-signed child URL. External URLs, namespace escapes,
  missing objects, checksum changes, misleading version-marker paths, and
  oversized graphs fail closed. Canonical object paths are checked by
  structured `tenants/{tenant}/media/{purpose}/{asset}/{version}/...`
  components rather than substring markers.
- `http/media_delivery.py` is an opt-in `GET`/`HEAD`/`OPTIONS` installer. It
  has no provider callback path and is deliberately separate from the
  authenticated media command router. The default `create_app()` OpenAPI
  surface remains without this delivery route.
- `processing.py` exposes the same HLS URI resolver used by inspection so the
  delivery path does not grow a weaker second traversal parser.

## Explicit non-claims and remaining gates

- No S3/MinIO provider was contacted, no credentials were added, and no CDN or
  external signed URL was issued. `compose_private_object_storage()` and the
  provider transport remain fail-closed; the opt-in installer is not mounted
  by the shipped application.
- The test authorizer is only a deterministic double. A production composition
  must provide a persisted, server-owned session/grant decision and an
  independently reviewed consent, retention, provenance, provider, and
  professional-gate record under `AC-GOV-AUD-001`.
- HLS rewriting validates and signs an already-materialized private graph. It
  does not scan media, run FFmpeg, create ABR renditions, establish codec
  support, or claim live/CDN playback. Existing upload, scan, processing,
  lifecycle, and idempotency foundations remain unchanged and dormant where
  their provider/recovery gates are open.
- No durable provider inbox/outbox, cleanup worker, or production job-retry
  guarantee is introduced here. No canonical media, payment, access,
  progress, or analytics state is derived from delivery requests.

## Verification

The exact commands and refreshed results are recorded below after the phase-2
changes were applied:

```text
uv run pytest -q tests/unit/media/test_media_delivery_phase2.py
19 passed, 1 warning (StarletteDeprecationWarning from the installed FastAPI/httpx compatibility seam)

uv run pytest -q tests/unit/media tests/unit/http/test_app_composition.py
148 passed, 1 warning (StarletteDeprecationWarning from the installed FastAPI/httpx compatibility seam)

uv run ruff check packages/python/ac_platform tests
All checks passed!

uv run mypy packages/python/ac_platform
Success: no issues found in 119 source files

git diff --check
passed

uv run pytest -q tests/unit
798 passed, 1 warning (StarletteDeprecationWarning from the installed FastAPI/httpx compatibility seam)

uv run pytest -q tests/security tests/integration
32 passed, 92 skipped (PostgreSQL integration URLs were not configured)
```

Focused tests cover progressive streaming, one bounded range, `HEAD`, exact
token/path/origin/expiry rejection, per-issued-URL range denial for
progressive/caption/HLS-child URLs, oversized/undersized/byte-mutated/version-
mutated storage adapters, HLS master-to-playlist-to-segment child-token
rewriting, external/missing HLS child rejection, misleading version-marker
paths, the dormant S3-compatible range contract with a local double, the
opt-in HTTP route and preflight, and absence of the delivery route from
default application composition.
