# ADR 0031: Explicit platform and scoped Studio capabilities

Date: 2026-09-07. Status: implementation in progress; no runtime activation.

## Authority and problem

The current user decision explicitly assigns whole-platform Cohorva LMS
administration to the named admin and Suyash company accounts, and Academy
content/coaching work to Dipak. This is not permission to invent an Instructor
role, bypass enrollment, or grant ERP/finance/infrastructure authority. Exact
identity provisioning remains a normal verified authentication workflow.

The controlled Admin source was fetched again by manifest ID
`12-VjN02jx8M7S8wJrZLcl4OwLcXIFGXKu74wxdJrWuY`; current revision
`ANLCKQmAYEDY2LvCZcR3jOoTQV8uscfzwd0MiFzsIyiMi6h2Tr3LjUa1FjJtS6dB-fTcxP7vFZyu983zVlNyM9DOs5aUvUOH8AiMuge7BrE`.
Its named-login temporary risk, attributable sensitive commands, separate ERP
authority and immutable corrections remain in force. This ADR supersedes only
ADR0029's owner/admin-only capability assignment implementation, once activated.

## Decision

Keep Person, session, tenant and Membership unchanged. Add immutable capability
grant and separate immutable revocation rows; neither email nor a client claim
is authority. A later regrant is a new command, not an edit of old history.

Platform scope accepts only `platform_access_manage`, `platform_tenants_read`,
`platform_catalog_read`, `platform_catalog_write`, `platform_catalog_publish`.
Tenant/program scope accepts the individually assigned existing Studio action
names `catalog_read`, `catalog_write`, `catalog_publish`, `learner_diagnose`,
`learning_review`. No assignment implies another action. In particular,
`platform_access_manage` is not catalog publication or learner access.
Program grants authorize that exact academy/program, not unfiltered tenant
readiness or people lists. Review still requires the existing assignment and
evidence gates; a permission is necessary, not sufficient.

All scopes require an active verified Person; Studio scopes additionally require
current active membership, active tenant and exact program ownership where
applicable. Platform scope does not depend on replacing a learner role or
fabricating tenant membership. Platform APIs will use explicit resource context;
the normal learner context selector remains membership-bound.

Management commands require a live named session and current persisted
`platform_access_manage`, explicit UUID intent, target, capability, scope and
reason. Exact replay returns original history; changed intent conflicts and
revoked grants never reactivate by replay. Audits and assignment rows share one
caller-owned transaction. Platform audit events use configured
`operations_tenant_id`; tenant/program changes use their real resource tenant.
The audit scope is not a fabricated selected-tenant ActorContext.

The operator-only initial bootstrap can assign only `platform_access_manage`
to an exact existing verified operations owner while capability history is
empty. It creates no person, session, membership or enrollment. It is never
called by login or a public endpoint. Revocation does not reopen bootstrap.
Any future last-manager protection/recovery policy must be explicitly designed;
there is no automatic owner fallback or resurrection mechanism.

## Transaction integration contract

PostgreSQL management uses a namespaced governance advisory fence followed by
shared governance-tenant validation and subject locks. Ordinary identity already
locks Person then Session then tenant. Therefore a future management HTTP
dependency must take the management fence **before** ordinary identity
resolution; reusing the existing dependency and adding a fence afterward can
deadlock two operators. Exact commands must hold authority/lifecycle locks
through their writes. The new concurrency tests exercise real blocked locks
and ordinary identity interaction when a disposable PostgreSQL URL is present.

## Activation gate

This persistence/service checkpoint is deliberately not mounted in HTTP. The
existing authorization remains authoritative until all enforcement points are
integrated and tested together: identity permission projection, admin route
checks, catalog command checks, both technical-fixture import checks, and admin
frontend entry/session validation. Platform permission strings must never be
silently projected into generic tenant catalog rights. Scoped collections need
server filtering and resource-specific checks. Linux/PostgreSQL migration,
concurrency, grant/revoke/audit tests and independent review must pass before
canonical operator commands or live grants are exposed. API/route/security
matrices and UI acceptance must then move with their adapters.

The backup/restore representative row-count contract currently contains 39
fixed tables shared by the foundation capture helper, off-site proof helper and
application restore controller. Extending only the application list was tested
and correctly failed their compatibility test; that partial change was removed.
Before activating populated capability state, add version-compatible explicit
grant/revocation restoration proof across the shared contract. Do not silently
weaken parity validation or claim the historical a5/0018 restore verifies new
0019 authorization rows.

### Recovery implementation checkpoint — September 7

The three recovery helpers now implement explicit compatible V1/39-table and
0019 V2/41-table contracts, with snapshot/release/restored-head checks and both
capability-history counts required. Parent review and 132 local tests pass;
Linux root execution and actual canonical live 0019 recovery remain gates.
See [compatibility evidence](../evidence/20260907_CAPABILITY_BACKUP_PARITY_COMPATIBILITY.md).
Roll out the backward-compatible foundation helpers before the reviewed 0019
application; do not claim the earlier live 0018 proof covers new permission data.
