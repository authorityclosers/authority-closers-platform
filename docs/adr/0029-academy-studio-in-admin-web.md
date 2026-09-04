# ADR 0029: Academy Studio lives inside `admin-web`

- Status: accepted for the v0.1 implementation candidate
- Date: 2026-09-04
- Scope: Academy Studio shell, catalog reads, content readiness and tenant-local publication

## Context

Authority Closers needs one operating workspace for course authorship and
coaching without creating a second identity system, backend or speculative
`Instructor` authorization role. The controlled IA already assigns product
administration to `admin.authorityclosers.com`; the catalog domain already
models tenant/global ownership and immutable versions; the authenticated actor
context already carries a server-selected tenant and named permissions.

The current `/catalog` screen is a static contract preview. It does not expose
canonical program/version state, an actionable draft backlog or a replay-safe
publication action. The Academy capacity exercise also does not authorize a
live workload forecast: arrival rate, service rate and planned human capacity
are not canonical product facts in this slice.

## Decision

1. **Academy Studio is a product/navigation label inside the existing
   `apps/admin-web` application.** It uses the existing admin host, product
   session, API, PostgreSQL catalog and audit chain. No Instructor host,
   account universe, backend or role is introduced.
2. The initial routes are `/studio` (Today/content readiness),
   `/studio/programs`, and `/studio/programs/{programId}`. `/catalog` redirects
   to `/studio/programs` so old links have one canonical destination.
3. The current role model gains the named `catalog_read` permission for active
   `owner` and `admin` memberships only. `catalog_write` and
   `catalog_publish` remain separate permissions. Support/learner membership,
   a hidden navigation item or a client-supplied role never grants a read.
4. Every Studio API read derives actor and selected tenant from the verified
   server session and rechecks the active person, tenant and membership.
5. Visibility is exact:
   - every working draft of a program owned by the selected tenant is
     readable; older immutable history may be bounded and is explicitly
     marked as truncated;
   - a global program is visible only when it has an immutable published or
     superseded version, and only bounded immutable versions are returned;
   - programs owned by another tenant and global draft versions are
     indistinguishable from missing resources;
   - global content is read-only in the tenant-local Studio. Global authoring
     and publication belong to a later approved Platform Console workflow.
6. Today shows the selected tenant's canonical draft backlog and derives the
   oldest-work age from the canonical draft creation timestamp and response
   time. Publish
   readiness is calculated by the same catalog structural, provenance, digest
   and supersession rules used by publication. The slice adds no new
   completeness rule. Arrival rate, service rate and planned capacity are
   explicitly `unavailable`, not zero and not estimated.
7. Tenant-local publication requires `catalog_publish`, a non-blank reason,
   `Idempotency-Key` and the current canonical `If-Match` version ETag. The
   command ledger reservation, locked version transition and append-only audit
   event complete in the caller-owned database transaction. An exact replay
   returns the stored semantic result; key reuse with different intent is a
   conflict; a stale precondition fails without mutation.
8. `AdminShell` navigation is permission-filtered. This improves discovery but
   is not an authorization control; every API route continues to enforce
   actor + tenant + resource + action server-side.

## Alternatives considered

- Create a separate Instructor application and identity boundary. Rejected
  because no controlled host or authorization role supports it and the shared
  LMS/Studio boundary is sufficient.
- Rebrand the whole admin application as Studio. Rejected because platform,
  finance, support and infrastructure operations have different least-
  privilege boundaries.
- Show global drafts to tenant operators or publish global content from a
  selected tenant. Rejected because it would mix tenant-local course operation
  with cross-tenant platform governance.
- Display simulated queue/capacity metrics. Rejected because the simulation is
  planning evidence, not current operational truth.

## Consequences

- Dipak can operate content from one coherent Studio entry point while the
  Platform Console remains a bounded subset of the same admin application.
- The Authority Closers Academy tenant can read its own working versions and
  the immutable global curriculum it consumes without seeing another tenant's
  data or platform-global drafts.
- The first Studio release is intentionally content-led. Review assignment,
  generic work queues, assessment authoring, real-call media, billing and
  tenant self-service remain gated.
- Existing sessions gain one permission value, so role/permission contract,
  navigation and negative tests must move together.

## Reversal cost

Low to moderate. Routes and components can later move to a separate deployment
behind the same API/session contracts. Extracting identity, tenant or catalog
authority would require a separate ADR and migration; this decision does not
pre-authorize that extraction.

## Evidence

- `packages/python/ac_platform/http/admin_learning.py`
- `packages/python/ac_platform/catalog/models.py`
- `packages/python/ac_platform/catalog/services.py`
- `apps/admin-web/app/studio/`
- `tests/unit/http/test_admin_learning_routes.py`
- `tests/integration/test_admin_learning_http_postgresql.py`
- `docs/evidence/ACADEMY_STUDIO_CONTENT_READINESS_IMPLEMENTATION.md`

## Owner

Authority Closers product, catalog, tenancy and security owners.

## Supersedes

The static `/catalog` preview as the canonical content workspace. It does not
supersede the separate admin/ERP trust boundary or authorize a new Instructor
role.

## Trigger to revisit

Revisit only when measured release cadence, staffing, security isolation or an
approved second-tenant contract justifies a separately deployed Studio, or
when a controlled role/permission decision replaces the current owner/admin
mapping.
