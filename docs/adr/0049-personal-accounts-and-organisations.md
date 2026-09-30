# ADR 0049: Personal accounts and organisations

- Status: accepted for the organisation foundation slice
- Date: 2026-09-30
- Scope: organisation membership, verified domains, and sign-in membership creation

## Context

Personal accounts need to work without a shared workspace. Some tenants are
registered organisations with an owner, admins, members, invitations, and
verified-domain settings. The AUT-443 owner order requires a reviewed command
path for organisation creation and domain settings; it forbids direct SQL
state changes. Existing tenancy roles and Admin permissions describe other
tenant types and must retain their current behaviour.

## Decision

1. An organisation is an explicit registry row attached to one tenant. A
   tenant outside that registry keeps the existing role-permission mapping.
2. Each organisation has exactly one active owner. Owners and admins receive
   only `organisation_manage` in an organisation tenant. Members receive no
   role permission there. Organisation roles never imply a platform
   capability.
3. Invitations are attributable commands for `admin` or `member`; direct adds
   require an active person with a verified email. Domain settings are
   append-only versions, and the newest version is authoritative.
4. Organisation creation, member adds, and domain settings use stable command
   IDs. Replaying the same intent returns its prior result; reusing an ID for a
   different intent is refused. Each command appends one audit event in that
   organisation's tenant.
5. Authentication may create an organisation membership only for an accepted
   invitation or a verified-domain auto-join into a registered organisation.
   This narrow rule amends ADR 0028's blanket prohibition for organisations.
   It does not create learner eligibility, enrollment, or membership in an
   unregistered tenant.
6. The operations and public learner tenants cannot be registered or managed
   as organisations. A freemail domain cannot be verified for auto-join, and
   one domain cannot be current for more than one organisation.

## Alternatives

- Give every tenant the organisation permission map: rejected because existing
  operations and learner tenant behaviour must remain stable.
- Let organisation owner or admin roles inherit Admin-console or platform
  capabilities: rejected because organisation management is a separate trust
  boundary.
- Replace domain settings in place: rejected because verification and
  auto-join changes need an attributable history.
- Create organisation memberships for any verified sign-in: rejected because
  membership requires an accepted invitation or an explicit verified-domain
  auto-join rule.

## Consequences

- Personal tenants remain independent; an organisation is an explicit tenant
  relationship.
- The A3a slice stores the organisation, invite, and domain-setting facts and
  supplies audited operator commands. Sign-in auto-join and HTTP routes remain
  later slices.
- Existing non-organisation tenant permissions remain unchanged.

## Reversal cost

Moderate to high. Membership, invite, audit, and domain-setting history is
security-relevant. Reversal requires an append-only, reviewed migration or
application command. The organisation registry cannot be removed by a
downgrade or by deleting audit history.

## Evidence

- [AUT-443 owner order](/AUT/issues/AUT-443)
- [AUT-438 A3a specification](/AUT/issues/AUT-438)
- `packages/python/ac_platform/tenancy/models.py`
- `packages/python/ac_platform/organisations/`
- `tests/unit/organisations/`

## Owner

Authority Closers product and platform security owners.

## Supersedes

ADR 0028 only where its blanket statement that authentication never creates a
membership conflicts with a registered organisation's accepted invitation
or verified-domain auto-join. All other ADR 0028 decisions remain in force.

## Trigger to revisit

Revisit before adding organisation membership routes, sign-in auto-join, role
transfer, customer-domain activation, or any change to the operations/public
tenant boundary.
