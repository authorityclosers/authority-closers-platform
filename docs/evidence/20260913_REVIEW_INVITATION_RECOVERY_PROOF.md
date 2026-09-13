# Reviewer invitation integration proof

The independent review of `7ffd092` found that a non-ASCII invitation token could
raise an encoding error and return HTTP 500. Acceptance now maps malformed token
hashing to the same unavailable-invitation result as an unknown token. Admission
still runs first, and the invalid token never reaches a database lookup.

The PostgreSQL reviewer fixture now supplies synthetic email addresses for its
already-verified synthetic persons. This repairs test setup without changing
production identity or verification state.

The populated migration rehearsal now inserts assignment, revocation and feedback
history at revision `20260913_0034`, upgrades to `20260913_0035`, and compares all
pre-existing rows. The three new invitation tables start empty.

Validation on 13 September 2026:

- Four focused service and HTTP tests passed, including a 40-character non-ASCII
  token, generic HTTP 404, and no database lookup for malformed bearer material.
- Six actual PostgreSQL reviewer/invitation tests passed after the fixture repair.
  Follow-up receipts separately verify the invitation flow (one test) and the
  existing assigned-review flows (five tests).
- One populated PostgreSQL migration rehearsal passed in 43.44 seconds, including
  the existing revision-34 review history. The disposable database was removed.
- Ruff formatting and lint checks passed for all changed Python files.

Receipts are outside Git in `D:/AC-authority-closers-release-audit/`:
`v02-invite-malformed-01.xml`, `v02-invites-postgresql-02.xml`,
`v02-invites-postgresql-03.xml`, `v02-invites-postgresql-06.xml`, and
`v02-invites-migration-01.xml`. These establish local implementation evidence;
they do not claim deployed email delivery or a production reviewer journey.

No provider calls, real invitation emails, production database edits, or identity
overrides were performed by these checks.
