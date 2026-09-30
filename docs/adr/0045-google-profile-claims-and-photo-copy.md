# ADR 0045: Keep Google profile claims and a first-party photo copy

Date: 2026-09-30. Status: proposed for CTO review under AUT-397.

## Context

The existing Google `openid email profile` token already includes optional
profile claims. Sales Xray needs those values after sign-in. A Google picture
URL is provider-controlled and must not become a permanent browser dependency.

## Decision

Refresh the verified `given_name`, `family_name`, `locale`, and `hd` claims on
each Google register, sign-in, or link. Store only normalized values in the
person's `person_google_profiles` row. Missing or invalid claims become NULL.
Expose the four values through the Sales Xray contact-profile response.

Keep an optional photo copy in Postgres for the follow-on implementation.
Store the image and its SHA-256, plus only the source URL's SHA-256. Never store,
hot-link, or log the Google picture URL. Photo fetch and delivery remain outside
this change.

Do not add scopes or change consent text, authorization URLs, or identity
checks. These profile values are display-only and never identity keys.

## Alternatives

- Keep the Google URL and hot-link it: rejected because the provider controls
  availability and the URL is not our image copy.
- Add OAuth scopes: rejected because the existing token already has the claims.
- Put the image in object storage: rejected; the approved design uses Postgres.

## Consequences

The profile uses current Google claims, with a missing claim clearing its old
value. Account deletion removes the row. Postgres backup and restore parity
must include the table before the migration head is supported.

## Reversal cost

Stop reading the claims and photo copy, then remove them through a reviewed
forward-only migration. Preserve account deletion behavior and prior backups.

## Evidence

- CTO spec card for AUT-397 and the existing Google OIDC adapter.
- Migration `20260930_0053` and the personal-data inventory in this repository.

## Owner

Platform pod; CTO reviews and approves the decision.

## Supersedes

None.

## Trigger to revisit

Revisit if Google changes the signed claims, retention decision, or permitted
photo-copy source, or if the owner removes the profile display requirement.
