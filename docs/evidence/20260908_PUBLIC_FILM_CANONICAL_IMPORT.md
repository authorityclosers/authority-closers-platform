# Canonical public-film import — source and isolated test evidence

This slice adds a separately approved public-film demonstration importer, not a
production invocation, arbitrary upload facility, enrollment command, or Watch
completion policy. The package contains two **12.032-second excerpts**, not full
films or Dipak instruction.

## Implemented boundary

- `media/public_film_import.py`: deterministic tenant-owned catalog identity,
  attribution/disclosure, two optional VIDEO activities, real opaque-session
  resolution with the existing normal role projection, and fresh tenant-wide
  Studio authoring/publication checks.
- Canonical `AsyncCatalogApplication` creates/publishes catalog content;
  `MediaService` registers inspected sources as PROCESSING, validates them before
  READY, and appends approved activity bindings. An import savepoint and the
  canonical audit append share the caller-owned transaction.
- A sealed lease covers the exact actor, root transaction, import savepoint,
  service/storage/processor, two versions and their designated activities. Each
  use rechecks persisted session/lifecycle/tenant rights, including immediately
  before READY and binding approval. Ordinary media authorization is unchanged.
- Replay checks immutable intent, catalog provenance/content and current media
  inventories/approval history. It does not repair or adopt divergent history.
- `python -m ac_platform.media.public_film_import` reads only configured package
  roots and a hidden-stdin existing session; it requires explicit deployment,
  release, tenant, version, manifest and command intent. Production additionally
  requires `--allow-production`. No result is printed until commit succeeds.

## Executed locally

- 48 relational/CLI tests passed: `tests/unit/media/test_public_film_import.py`.
- 196 combined tests passed: the new importer plus existing staging import,
  staging runtime, media service and phase-two delivery suites (43.48 seconds).
- Scoped Ruff and mypy passed. One existing Starlette/httpx deprecation warning.

These tests use real ORM transactions and canonical services with tiny structural
media fixtures; they do **not** establish codec correctness or live VPS serving.
PostgreSQL concurrency/real-byte deployment evidence is recorded separately by
the executing reviewer. This agent performed no runtime restart, operational
database import, remote deployment, browser action, or Git commit.

## Dated addendum — 2026-09-09 — current-package asset/version guard

The current package now has a manifest-owned deterministic asset/version guard
at generic `MediaService.bind_activity_media`. It rejects fixture-to-ordinary
published-course replacement, both partial identity mixes, unauthorized replay
or reapproval, and ordinary video replacing the current protected approval;
prior history remains unmodified. Existing sealed import/replay behavior and
the old staging importer are unchanged.

The scoped changes are limited to `media/service.py`,
`media/public_film_manifest.py`, `tests/unit/media/test_public_film_import.py`,
and `tests/unit/media/test_public_film_manifest.py`. Validation reports **218
tests passed** across those two tests plus `test_staging_fixture_import.py` and
`test_activity_delivery_authorization.py`; Ruff check/format passed for the
four files, and mypy passed for the two production files. Review found and
fixed a replacement-case gap; an independent reviewer reran four selected test
cases and found no remaining Critical/Important issue in this current-package guard.

No migration, config, activation, DNS, or production manual-data changes were
made. This is hermetic SQLite relational-contract evidence with tiny test
fixture bytes—not 4K codec delivery, VPS serving, or current-release
acceptance.
