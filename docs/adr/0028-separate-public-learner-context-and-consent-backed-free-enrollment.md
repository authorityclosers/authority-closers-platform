# ADR 0028: Separate public learner context and consent-backed free enrollment

- Status: accepted for v0.1 Alpha staging
- Date: 2026-09-01
- Scope: public learner tenancy and the exact Authority Closers free course

## Context

The first staging bootstrap reused one tenant for operations ownership and
self-directed learners. Membership role is intentionally singular inside a
tenant. Therefore `admin@authorityclosers.com` correctly remained an `owner`
and could not satisfy the free-enrollment requirement for an active `learner`
membership. Newly verified learners also had no canonical eligibility fact,
so a published course could be visible without being enrollable.

The reviewed learner registration consent explicitly includes an 18+
attestation, Terms, Privacy and required operational email. The enrollment
domain already requires a versioned server-owned eligibility fact and records
that fact in immutable enrollment provenance.

## Decision

1. `AC_OPERATIONS_TENANT_ID` and `AC_PUBLIC_LEARNER_TENANT_ID` must reference
   separate active tenants.
2. The public learner tenant is created by an idempotent application command,
   never by direct SQL. The bootstrap creates no person or membership.
3. Verified registration provisions only an active `learner` membership into
   that exact configured tenant after the exact current consent has been
   recorded. Authentication never creates membership or enrollment state; it
   selects an already-active public learner membership when one exists.
4. An explicit `Start free course` action may create a canonical eligibility
   fact under policy `AC-FREE-SELF-ATTESTATION-v1` only for the exact published
   global program slug `authority-closers-free-course`.
5. The fact evidence records the consent version and timestamp plus the
   explicit start action. It contains no email address, password, provider
   token or analytics-derived authority.
6. Existing positive canonical eligibility facts are reused and never
   overwritten. Negative, expired or conflicting facts fail closed.
7. Eligibility creation and enrollment run in the same caller-owned database
   transaction. Enrollment provenance and audit events retain the policy
   inputs used to grant access.

## Consequences

- One identity may remain an operations owner and also be a learner because
  the roles exist in different tenants.
- Any verified consenting learner can start the approved free course without
  an operator manually editing data.
- This does not authorize paid courses, tenant-owned catalogs, billing,
  scoring, provider-derived access, native apps or enterprise provisioning.
- Production remains blocked until the separate tenant references, fresh
  learner journey, isolation tests and deployment evidence pass independently.

## Alternatives considered

- Allow `owner` or `admin` to pass learner self-enrollment. Rejected because it
  collapses role semantics and weakens the server-side authorization boundary.
- Change the existing operations membership to `learner`. Rejected because it
  removes attributable operations authority and breaks recovery controls.
- Seed enrollment or eligibility with SQL. Rejected because runtime database
  state is not authoritative and direct SQL is not an operational recovery
  path.
- Treat acceptance analytics or Google identity state as eligibility. Rejected
  because neither is canonical consent or access authority.

## Reversal cost

Low to moderate. The environment reference can be changed to another reviewed
active public tenant. Existing memberships, eligibility facts and enrollment
history must be preserved or migrated with an explicit audited application
path; they must not be overwritten.

## Evidence

- `packages/python/ac_platform/tenancy/learner_provisioning.py`
- `packages/python/ac_platform/enrollment/self_attestation.py`
- `packages/python/ac_platform/http/course.py`
- `tests/integration/test_course_http_postgresql.py`
- `tests/integration/test_bootstrap_postgresql.py`
- Contextual staging-baseline captures showing the owner-role/no-enrollment
  collision in `docs/evidence/screenshots/v0.1-staging-live-audit-20260901/`.
  Their manifest explicitly records that they are not release-bound proof.

## Owner

Authority Closers product, tenancy and security owners.

## Supersedes

The single-tenant bootstrap assumption in the previous v0.1 runbook sequence.
It does not supersede ADR 0025 or the core G1 authorization model.

## Trigger to revisit

Revisit when AC introduces organization-managed cohorts, multi-role membership,
paid access, delegated tenant administration or a controlled age/eligibility
policy that supersedes self-attestation.
