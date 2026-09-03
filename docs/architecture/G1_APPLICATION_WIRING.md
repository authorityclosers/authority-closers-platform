# G1 application wiring

This document fixes the integration boundary for the Free Course walking
skeleton. Domain helpers may remain pure and testable, but production commands
are constructed only through the durable application composition root.

## Request trust boundary

1. The browser presents an opaque session cookie; the raw value is never
   persisted or logged.
2. The API hashes the cookie and resolves one active, unexpired session.
3. The API reloads the canonical person, selected membership, and tenant on
   every authenticated request. Suspended/deleted people, inactive membership,
   or suspended/deleted tenants fail closed.
4. The resulting `ActorContext` is server-owned. Request bodies cannot assert
   `person_id`, `tenant_id`, role, permission, enrollment, entitlement, catalog
   visibility, reviewer assignment, or completion.
5. Resource ownership and current version are rechecked in the command
   transaction. Identifier knowledge never grants access.

## Transaction boundary

Each mutation owns one SQLAlchemy `AsyncSession` transaction. Canonical domain
rows, immutable evidence, audit evidence, idempotency result, and outbox intent
either commit together or roll back together. Provider calls never occur in an
HTTP transaction.

```text
HTTP command
  -> resolve trusted ActorContext
  -> begin SQL transaction
  -> lock/reload policy inputs and canonical resources
  -> execute domain invariant
  -> append audit + outbox intent
  -> commit
  -> return canonical result
```

Idempotent commands persist `(actor, tenant, operation, key, request_digest,
result)` and reject same-key/different-request reuse. Optimistic resources use
an opaque revision and conditional update; an affected-row count of zero is a
conflict, not a retryable overwrite.

## Worker boundary

Workers materialize and lease durable jobs using `FOR UPDATE SKIP LOCKED`.
Lease completion, renewal, and failure are fenced by job ID, lease token,
status, and database expiry. Production construction is held by default.
After restore, both unpublished outbox intents and nonterminal jobs remain held
until a named operations actor reconciles an explicit set in the same
transaction as audit evidence.

The G1 provider allowlist contains only versioned email communications. Local
and test construction use the no-network fake adapter. An unimplemented or
unapproved provider configuration is a startup error.

## Route-to-command projection

| Route family     | Durable command/query                                                     |
| ---------------- | ------------------------------------------------------------------------- |
| identity/context | session resolution, self query, selected-membership change                |
| public catalog   | published visibility query with locked payload policy                     |
| free enrollment  | self-only enrollment + entitlement + provenance + welcome intent          |
| learning         | entitlement-bound draft/evidence/progress command with pinned version     |
| certificate      | authoritative completion evaluation and immutable issuance                |
| admin            | named permission, purpose/reason, append-only correction, mandatory audit |
| provider webhook | signature/time verification, inbox lease/dedupe, no direct access grant   |

HTTP schemas adapt to these commands; they do not duplicate business policy.
Controlled identifiers that remain unresolved stay replaceable and are not
allowed to weaken this boundary.
