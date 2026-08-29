# G1 API conventions

Controlled references: API/MCP specification, Security/IAM specification, AC-G1-003/010/012/015, AUTHZ-01–14.

## Boundary

- Public product operations live under `/v1`.
- Provider callbacks live under `/internal/v1/providers/{provider}/webhooks` and are never administrative endpoints.
- Commands and queries use explicit resources; no endpoint accepts an arbitrary `tenant_id` as proof of context.
- The authenticated session resolves `ActorContext`. Active membership resolves tenant context. Resource ownership is then rechecked server-side.

## Mutation contract

- Idempotent commands require `Idempotency-Key`, scoped to actor, tenant, operation, and canonical request digest.
- Optimistically concurrent resources return an opaque revision and require `If-Match` for updates. A stale revision returns `409 resource_conflict` without overwriting current work.
- Successful creation returns `201`; idempotent replay returns the canonical existing result without repeating outbox/provider effects.
- Business state and outbox intent commit in one database transaction.

## Error contract

Errors use `application/problem+json` with `type`, `title`, `status`, bounded `detail`, `instance`, stable `code`, and `request_id`. Responses never expose SQL, stack traces, provider tokens, policy internals, or another tenant's resource existence.

## Collection contract

Collections use opaque cursor pagination. Sort order is deterministic and includes a stable ID tie-breaker. Filters are allowlisted. Cross-tenant search, cache, export, and retrieval boundaries are negative-tested.

## Recovery contract

Restored outbox/jobs start held. Reconciliation is a named, permissioned command with audit provenance; neither process startup nor readiness releases external side effects.
