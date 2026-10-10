# AUT-1694: invitation acceptance replay checks current membership

Base: `4d623dab8d6c78b0e261090d5df990eb904b5ee1` (merged PR #426).
Lane: `api`; branch: `task/api/1694-strike-organisations`.

## Result

An invitation recipient who retries an already accepted invitation gets their
current organisation role. If their membership has ended, the retry returns
HTTP 409 with the existing "This invitation has already been used" error. A
retry cannot restore membership or append another acceptance, audit or email.
This applies to replay of both the initial acceptance key and a later
acceptance-confirmation key.

The prior implementation returned the historical audit response immediately,
including an old admin role after demotion and success after removal. Four
fictional HTTP regressions reproduced those failures before the fix (4 failed,
11 deselected, 8.92 seconds).

`OrganisationService.accept_invite` now reuses `_lock_members` under its existing
organisation registry fence. This refreshes cached membership state, requires
an active, unended human membership and uses the established NOWAIT conflict
behavior. The existing accepted-invitation confirmation path uses the same
fence. Responses come from current membership; the original invitation role,
acceptance result and append-only audit chain retain their historical values.

No route, migration, sign-in, billing, dependency or worker changes are included.
The response shape and original UUID/intent idempotency checks are unchanged.

## Validation on the actual tree

- `uv run pytest tests/unit/http/test_organisation_invites.py
  tests/unit/http/test_organisation_creation.py
  tests/unit/organisations/test_service.py -q`: **37 passed in 25.00 seconds**.
- `uv run pytest tests/database/test_organisation_invites_postgresql.py -q`:
  **9 passed in 41.70 seconds** using the provided disposable PostgreSQL test
  environment. No skipped tests were counted as passing.
- Ruff check and format check pass for all three changed Python files.
- `uv run mypy packages/python/ac_platform/organisations/service.py` passes.
- `git diff --check` and the api task gate pass. A complete open-PR file scan
  and exact-path status scan across the other existing lane checkouts found
  no overlap with these three files before integration.

The HTTP regressions change roles and remove members through the app's existing
commands, then prove unchanged audit hashes/payloads, one queued mail event,
unchanged historical invitation role and no membership restoration. PostgreSQL
regressions preload a stale membership in the replay session, run a concurrent
owner role-change/removal, prove replay waits behind the registry fence, then
check the committed current state and unchanged audit chain. The same module
also proves the real default-worker send/replay/revoked/expired/wrong-tenant
journey, explicit acceptance and existing invite/seat races with fictional mail.

## Dev check after delivery

Use authorised fictional accounts and existing paid seat capacity or a sealed
fixture exemption. Invite a verified second person as admin; accept while their
selected workspace is Personal. Save the acceptance Idempotency-Key. As the
owner, change their role to member. Replay the acceptance from Personal with
that key: HTTP 200 must report `role: "member"`. Remove the member and replay
again: HTTP 409 must appear and membership must remain ended. A repeated
acceptance-confirmation key has the same behavior. The UI should display the
existing small error card for the 409 and must not invent successful joining.

## Limits

This is local/CI-fixture implementation evidence, not authenticated hosted dev
proof. AUT-1766's authorised actor/session/Access and runtime fixture handoff is
still required; its last durable receipt is blocked. A board-authenticated
session is unavailable in this direct continuation, so no current board status
is claimed. No host service, live approval, provider, staging/production data,
merge or deployment was changed. Call placement and default organisation
processing admission remain unfinished under their recorded ownership gates;
this replay repair does not enable either capability.
