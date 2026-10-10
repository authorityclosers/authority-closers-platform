# AUT-1694: Personal-call move eligibility boundary

`organisations.call_move.personal_call_move_candidate` resolves a source-bound
candidate in the caller's transaction. It grants no artifact access and moves no
rows. The final assignment command must re-resolve it under its own per-call
transaction and append the reviewed mapping and audit before exposing movement.
No public move endpoint or complete move journey is claimed by this slice.

The actual current session must select Personal. Existing conversation admission
rechecks person verification/status, session/revocation/expiry and Personal
membership. Destination read fences require an active registered organisation
and current human owner/admin/member membership; operations and Personal are
excluded. The source query reuses the existing account library's canonical
usage/explicit-visitor-claim owner, guest-submission, recording/hash, consent,
retention and canary fences. It keeps the real caller throughout.

The candidate separates the actual owner from the non-login processing person.
It carries the exact submission/recording/usage IDs, original tenant/principal,
destination, source hash/revision/generation and permission ID. Recording scope,
source files, processing history, usage, charges and audit history remain intact.
Expired processing permission does not erase otherwise valid retained authority.

## Proof

- 16 relational unit tests pass in 11.43s. They verify actual owner versus
  processing principal, direct and explicitly claimed guest calls, no INSERT /
  UPDATE / DELETE, other-owner denial, deletion, revoked consent, expired
  retention, canaries, destination membership removal/ending/processing roles,
  inactive/unregistered/protected destinations and fresh session context checks.
- Two disposable PostgreSQL lock tests pass in 15.60s. Source permission
  revocation and destination membership removal wait behind the candidate's real
  read fences. After commit, a fresh resolution denies both; an old candidate
  is not an authorization grant.
- All four invitation PostgreSQL tests also pass together in 13.14s. The journey
  now selects its exact invite's job from the module's shared fixture queue,
  without assuming unrelated fixture jobs do not exist.
- Ruff check/format, targeted mypy and diff checks pass.

## Remaining integration

The append-only mapping migration cannot join this PR while other open PRs hold
the shared migration/AGENTS slot. Physical movement is rejected: migration 0037
protects immutable guest/lease lineage, and 12 composite plus three simple
recording references retain their original identity. Relaxing those protections
would still rewrite source, speaker and processing history.

Before a mapping mutation is enabled, source-aware library/activity and exact
retained read/mutation ports must honor its destination and current membership.
Those seams overlap Strike C/B ownership, and must be integrated with their
owners. Default organisation acquisition admission also requires reviewed
contract support and a Root seal; paid capacity remains independent. The precise
handoff and source-pin design remain in the strike NOTES/DESIGN records.
