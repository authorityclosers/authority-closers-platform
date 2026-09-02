# Media vertical slice implementation evidence

Status: implementation evidence only; provider activation and production deployment remain gated.

## Scope delivered

- `ac_platform.media` now owns tenant-scoped asset/version state, upload intents,
  checksum and MIME verification, quota reservations, supersession, private
  rendition metadata, caption/transcript objects, playback grants, and resume
  state.
- `ac_platform.http.media` composes the slice onto the existing authenticated
  transaction. It does not accept actor or tenant identity from request fields
  or headers.
- Playback for an asset not owned by the caller requires an explicitly injected
  learning-scope authorizer; the default runtime does not guess course access.
- Upload completion, caption creation, and playback-token issuance use bounded,
  actor-scoped idempotency keys; provider webhook replays do not append duplicate
  applied-audit records.
- Media playback heartbeat is resume evidence only. Existing learning playback
  sessions, watch intervals, and canonical progress remain the official course
  completion boundary; the media slice stores only a last-position resume hint.
- Provider callbacks use a separate media route, HMAC verification, durable
  provider-event inbox state, and no provider payload is copied into audit data.
- The service validates HTTPS on all adapter-produced ephemeral URLs and verifies
  processor-produced rendition protocol/MIME metadata before making it playable.

## Fail-closed seams

The default application runtime uses `UnconfiguredPrivateObjectStorage`,
`FailClosedScanner`, and `FailClosedProcessor`. The in-memory storage and copy
processor are explicit test adapters only. Real storage, scanning, processing,
recording, and provider activation require deployment composition and their
separate governance gates.

## Evidence

- Focused unit, composition, boundary, and media suite: `56 passed` with
  `uv run pytest -q tests/unit/media tests/unit/http/test_app_composition.py
  tests/database/test_model_registry.py tests/security/test_http_boundary.py`.
- Full repository suite: `899 passed, 122 skipped, 1 warning` with `uv run pytest -q`.
- The migration is `20260902_0013_media_contracts`, chained after
  `20260901_0012`; it is forward-only and includes PostgreSQL immutable
  version-identity, current-version scope, and current-version delete-protection
  triggers.
- A PostgreSQL migration/integration run was not claimed locally when no safe
  configured PostgreSQL test URL was available. No deployment was performed.
- Integration note: this branch adds `20260902_0013_media_contracts`, while
  planning commit `8c6248ce` adds `20260902_0013_planning_analytics`; both descend
  from `20260901_0012`. Integration must renumber/rebase one revision and repair
  the Alembic chain. This branch intentionally does not rewrite the planning
  task's history.
