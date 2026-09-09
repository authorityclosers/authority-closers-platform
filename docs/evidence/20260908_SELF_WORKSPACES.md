# Authenticated workspace choices

Date: 2026-09-08. Local source verification only.

`GET /v1/me/workspaces` returns exactly `person_id`, `session_id`,
`selected_tenant_id`, and `workspaces: [{tenant_id, name}]` for the canonical
authenticated person. A normal tenantless session is sufficient. The repository
joins only that person's active, non-ended memberships to active tenants, ordered
by name and ID. No other members, roles, slugs, capabilities or secrets are
projected. Query selectors are refused. Success is no-store/no-cache.

Coach's existing exact HTTP inventory includes this GET. Strict `/me` and
`/context` DTOs, canonical authorization, and `POST /context` remain unchanged.
Listing never selects a context or grants membership/role/access. The ordinary
authentication dependency still updates session last-seen/revision, as on existing
authenticated GETs; the query adds no other writes.

The new relational SQLite HTTP suite exercises real opaque-session token hashing,
identity/session lifecycle, repository queries and transactions (not PostgreSQL
lock proof). It covers all three hosts, tenantless/multiple/selected/empty choices,
foreign person exclusion, fresh membership and tenant deactivation, refused
selectors, absent/malformed/revoked/expired/unverified/suspended authentication,
and observed SQL restricted to the existing session activity update.

Actual checks: **15 new workspace cases**, within **182 passing** combined
workspace/Coach/auth/composition/identity-hardening cases in 14.67s. Complete
Python mypy (157 files), scoped Ruff lint/format and `git diff --check` pass.

No runtime or remote change, migration, account creation, or permission assignment
was performed. Frontend selection is a separate coordinated client change.
