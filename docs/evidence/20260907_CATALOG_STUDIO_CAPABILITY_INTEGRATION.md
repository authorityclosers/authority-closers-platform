# Catalog Studio capability integration — local candidate

## Scope

Implemented in the existing d2de worktree, based on 2c56de938753a669265c4dda0d08ad9f3cb2ed0b. This task changes only catalog application authorization and adds a focused relational test module. Shared Studio authorization and HTTP integration are separately owned by the parent orchestrator. No commit, push, CI run, deployment, real identity grant, or remote database operation was performed. The current user direction is localhost-only until the complete experience is ready.

Tenant-scoped AsyncCatalogApplication commands now use StudioAuthorization.require. Existing-resource commands authorize the actual program; new-program creation requires academy-wide catalog_write. Program-version and module identifiers are resolved only within the selected academy. Supersession and prerequisite references cannot probe an unassigned program. CapabilityDenied becomes CatalogAccessDeniedError.

The lower CatalogService and SqlAlchemyCatalogUnitOfWork do not have a second actor-permission gate, so no permission-enriched ActorContext was introduced. Existing canonical scope, draft/publication, provenance, digest, ETag, ordering, supersession and transaction behavior remains intact. Global authoring/seed authority remains separate and unchanged: platform_catalog_write does not become catalog_write. Membership.role and learner pins are not rewritten.

## Validation

Command: uv run pytest tests/unit/catalog/test_studio_capabilities.py tests/unit/catalog/test_services.py tests/unit/authorization/test_capability_application.py tests/unit/media/test_staging_fixture_import.py -q --tb=short --maxfail=1

Result: **149 passed in 25.44 seconds**, including **55 new relational catalog cases**. No tests skipped in this run. Ruff check, Ruff format check, targeted services.py mypy and git diff --check passed.

The new tests use SQLite with foreign keys enabled and real SQLAlchemy statements, canonical CapabilityApplication grant/revoke commands, immutable grant history and audit-chain verification. A small awaitable session adapter exercises the actual asynchronous application methods and synchronous catalog persistence boundary without substituting authorization results. This is relational behavior evidence, not a PostgreSQL lock or networked API proof.

Coverage includes all five existing-resource operations; exact program allowance; other program/tenant/global denial; fresh revocation despite stale actor permission claims; read/publish/platform permissions not implying write; academy-wide creation; missing resource nondisclosure; supersession/prerequisite reference boundaries; canonical legacy owner/admin behavior; provenance/digest/ETag/technical-validation restrictions; published immutability; caller rollback; explicit transaction requirement; current account/verification/tenant/membership lifecycle checks despite retained stale identity-map objects; and selected-tenant enforcement. Denials preserve catalog/audit/pinning counts.

## Review and remaining proof

The author requested independent parent review of services.py and the new relational module. Review of the shared helper identified and coordinated immediate write-strength Program locking to avoid a SHARE-to-UPDATE upgrade cycle. The parent owns scope-filtering the helper's Program SELECT before row locking and the shared helper's separate tests.

No live course publication, HTTP idempotency claim, PostgreSQL concurrency pass, or customer-account access change is implied by this report. Those remain separate runtime acceptance evidence. Existing unrelated changes are preserved.
