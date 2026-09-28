# ADR 0033: Tenant-scoped shared source audio

## Context
AUT-4 D4/D5 and AUT-8 require one stored audio file per tenant/hash without exposing another owner's copy. T3a adds unused schema; T3b centralises reads; T3c switches uploads and deletion together.

## Decision
- Store bytes at `<tenant>/sources/<sha256>/source`, outside every recording folder. Existing strict recording inventory/erasure must continue rejecting unknown files.
- `conversation_source_objects` has one live row per `(tenant_id, source_sha256)`; `deleted_at` is a permanent tombstone. Re-upload after deletion creates a new object ID. Hashes never cross tenants.
- `conversation_source_references` has one permanent row per recording, bound to its tenant and owner. Release sets `released_at` and `release_reason` together once; neither table's history may be deleted or rewritten. Database guards enforce these transitions.
- T3c acquires the storage-root `_FencedExecutor` fence before locking the live object row for reference addition/release. First creation uses the unique index to serialize competitors, retries after conflicts, and rechecks live state under lock. Use the same lock order everywhere.
- Receive the full body, spool, hash and verify on both upload paths before atomic publication or spool discard. Body, status and headers must be identical; no early hit response, foreign identifiers, result reuse or owner-visible hit-dependent timing. T3c must test first upload versus someone else first; equal work alone is not proof of timing equivalence.
- Release only the requesting recording's reference. Under the same row lock and root fence, delete bytes only after the last live reference is released, then tombstone the object. A failed unlink leaves deletion retryable; crash recovery must reconcile filesystem/transaction boundaries before reuse. Do not acknowledge completed erasure before this finishes.
- Consent, retention, access and analysis charges remain per recording/owner. No existing files are migrated: recordings without a reference retain their per-recording key for reads and erasure. A released reference never falls back to a legacy key.

## Alternatives
Global hash dedupe breaks tenant isolation. Placing shared files inside a recording folder breaks strict inventory and independent erasure. A mutable refcount alone loses reference history.
## Consequences
T3a changes no runtime behaviour. T3c must deliver fenced upload/deletion recovery and D5 evidence together before using these tables.
## Reversal cost
Empty schema can downgrade to 0050. Once populated, downgrade refuses to destroy history; rollback needs a separately reviewed forward migration.
## Evidence
AUT-4 plan revision `0c5f3782-31c2-4d6e-af8f-6a424605af14`, CTO T3a scope comment `202440db-dab1-458d-9858-75460aa66dc6`, base `a5064f46`; PostgreSQL and parity results are recorded in the T3a evidence file.
## Owner
Lead Engineer; CTO owns scope; repository owner approves by merging.
## Supersedes
None.
## Trigger to revisit
Before T3c activation, a different storage adapter, tenant-boundary changes, or evidence of a duplicate timing leak.
