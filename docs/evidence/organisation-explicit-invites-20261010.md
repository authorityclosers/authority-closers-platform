# AUT-1694: explicit organisation invitations

Review routing: **CTO/CEO required**, because the organisation sign-in hook now
leaves new self-serve invitations pending until the person explicitly accepts.
Identity core, billing, migrations and provider approval files are unchanged.

## Implemented API

An owner/admin's existing `POST /v1/organisation/members` accepts `{email, role}`
and returns an invited member row with `invite_id`, including when that person
already exists. Admins can invite members; owners can invite admins. Active
members cannot be reinvited to bypass role-management commands. The canonical
UUIDv4 Idempotency-Key and safe Origin are required. Existing audited platform
operator provisioning retains its previous semantics.

`GET /v1/organisation/invites` works without a selected organisation and returns
`{invites:[{invite_id,tenant_id,organisation_name,role,invited_at,expires_at}]}`.
It shows only pending, unexpired invitations matching the person's verified
email and an active registered organisation. It performs no writes and uses
private/no-store caching.

`POST /v1/organisation/invites/{invite_id}/accept` requires a safe Origin and
UUIDv4 Idempotency-Key. It checks the current verified identity, exact email,
organisation, pending/expiry state and current paid capacity or sealed seat
exemption. Acceptance replaces the pending seat in one transaction, reactivates
an inactive membership, preserves the sole owner, and appends a person-attributed
`organisation.member_joined` audit with `reason=invite_accepted`. Its response is
`{invite_id,tenant_id,person_id,role,status:"accepted"}`. Identical command replay
returns its original result. A new command confirming an already accepted,
still-active membership appends confirmation evidence without adding a member.
Neither path switches the session's selected workspace; use `POST /v1/context`.

The existing `DELETE /v1/organisation/invites/{id}` revokes with append-only
audit evidence. It now requires a safe Origin as well.

## Expiry and mail

The creation audit seals `ac.organisation.invitation-policy/1`, explicit
acceptance and the exact seven-day UTC expiry. Existing audit mutation guards
protect that fact; changing a future default cannot extend a stored invitation.
Unmarked operator invitations retain their prior behavior. Expired invitations
cannot accept or send and do not reserve seats or appear pending. Reissue closes
the old lifecycle row as revoked, appends `organisation.invite_expired`, and
creates a new ID. No audit history is updated or deleted.

Invitation creation atomically enqueues `organisation.invitation.requested.v1`
with exactly `{invite_id}`. The dedicated resolver rechecks state, tenant and
expiry, and renders the escaped version-1 organisation invitation through the
existing approved security communication class and mail adapter. Its link is
`/organisation/invites?invite_id=<UUID>` on the configured Sales Xray host.
That ID is not an access credential: sign-in, verification and acceptance are
required. No email address, token, customer content or secret enters the outbox.

**Delivery integration is still blocked:** Strike C owns the worker allowlist.
It must register this event/route, job/handler, prepare allowlist and resolver.
Strike A must wire the join screen/link and explicit acceptance flow. This
evidence does not claim default-worker or live-dev delivery. Review must retain
that limitation until the integration is checked.

## Proof

- 72 focused HTTP invitation/write/seat-exemption tests pass (36.24s).
- 53 service/sign-in/platform compatibility tests pass (21.67s).
- Three disposable PostgreSQL concurrency tests pass (13.04s): accept/revoke
  in both orders, and competing invitations for the last paid seat.
- The disposable PostgreSQL HTTP create → invite nonexistent person → exact
  outbox route → fake mail send/replay → verified person → pending list → accept
  → workspace selection journey passes (13.36s). It uses the explicit route
  allowlist, not a claim that the default worker is registered.
- Two existing organisation PostgreSQL integration tests pass after updating
  invite acceptance: concurrent daily budget and paid two-seat purchase,
  invitation, usage pool and renewal. Payment/ledger assertions remain intact.
- The safe-origin/revoke/replay checks pass after the route guard change; the
  already-accepted confirmation check passes after its final audit addition.
- Ruff check/format, targeted mypy (13 source files), diff and task gates pass.

Negative proof includes wrong email, unverified identity, inactive organisation,
revocation, expiry, unpaid capacity, audit failure rollback, case variants,
HTML escaping, wrong-tenant mail jobs and no implicit join through domain policy.
All data and mail are fictional; no live data/provider request was used.

The full requested upload/read/move journey still waits for approved default
processing admission and the append-only call assignment/read integration.
