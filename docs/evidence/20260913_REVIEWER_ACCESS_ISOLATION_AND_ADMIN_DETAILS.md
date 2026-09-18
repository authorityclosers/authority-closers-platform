# Reviewer access isolation and Admin feedback details

Date: 2026-09-13. This supersedes the shared Academy reviewer admission described
in the earlier review UI and invitation browser evidence. It is an interim
capability hold, not acceptance of a dedicated reviewer login or deployment.

## Implemented boundary

Learner login, registration, verification and recovery no longer consume review
invitation fragments, add reviewer copy, or redirect into a review workspace.
Normal learning and account recovery continuations remain. The two legacy
Academy review pages return 404, and learner navigation has no reviewer guard or
entry. Old review components remain as migration material but are not mounted.

The generic learner review HTTP router is not installed. Direct assignment,
source, history, feedback and invitation acceptance requests return 404 without
calling the review service or private storage. New Admin assignment/invitation
commands retain the canonical Admin, host and origin gates, then return 503
without creating records or an email outbox event. The production Admin UI
disables those commands. Existing list and revoke operations remain available.
Existing identities and memberships are not converted or revoked by this change.

Admin can read saved feedback through the separate exact-ID endpoint
`GET /v1/admin/conversation/review-assignments/{assignment_id}`. It uses canonical
operations-tenant Admin authority, validates assignment/source/report/checkpoint
bindings, and reuses the canonical C1-C6 evidence checks before exposing content.
It returns bounded feedback and lifecycle metadata without report, transcript,
audio bytes or source URLs. Reviewer expiry/revocation preserves readable history;
source erasure, permission loss or retention expiry removes substantive feedback
from the response while preserving audit envelopes. No history is overwritten.

The Admin detail screen loads an assignment outside the latest queue page,
validates response bindings, discards stale requests, clears feedback on access
failure, and renders corrections, availability and lifecycle states. New invite
and direct-assignment controls remain unavailable while dedicated admission is
unfinished.

## Validation

- Learner: all 1,778 tests passed across 110 files; production build, TypeScript
  and full ESLint passed.
- Admin: all 767 tests passed across 42 files; full ESLint, production build and
  TypeScript passed. This includes stale-response, access-loss, exact-ID loading,
  response-binding and paused-command regressions.
- Python: eight focused HTTP/projection unit tests passed. Changed source passes
  strict mypy, Ruff lint and formatting checks.
- Broader Python HTTP/conversation suite: 1,386 passed, one skipped, and 29 failed
  because the default Windows temporary directory has a Git ancestor and the
  private-storage guard correctly rejected it. All 29 failed cases then passed
  unchanged in 5.93 seconds with a fresh temporary directory outside repositories.
  Both reports remain in the external release audit packet; no guard was relaxed.
- Disposable PostgreSQL: `review-admin-details-pg-02` passed in 20.78 seconds.
  Canonical Admin reads, learner/foreign denial, unknown IDs, revoked history and
  retention redaction were exercised. The first run found invalid checkpoint
  attribute assumptions; the final implementation uses the actual model and
  canonical evidence resolver. The initial failed receipt remains outside Git.
- Built learner browser: both legacy URLs returned 404; login/register/recovery/
  verification with a synthetic invitation fragment showed no reviewer links and
  made zero reviewer API requests.
- Admin browser against the actual HTTP router and disposable PostgreSQL:
  `admin-review-details-browser-02` passed in 20.07 seconds. Saved revoked feedback
  survived reload, exact-ID reads returned 200, both new-write buttons were
  disabled, no learner review API was called, no page errors occurred, and
  1440/390/320px layouts had no horizontal overflow. The first proof attempt
  counted only visible controls and missed the collapsed advanced form; the
  assertion was corrected to inspect both controls without changing application
  behavior. Its failure remains outside Git.

Receipts and inspected screenshots are in `reviewer-access-isolation-20260913/`.
Admin source hashes normalize UTF-8 line endings to LF; learner hashes describe
the exact local source bytes used by the build. Browser authentication uses
synthetic canonical actor fixtures, so this is not session-resolver, real email,
provider, production data or hosted deployment acceptance.

## Remaining reviewer acceptance

Dedicated reviewer admission, its session boundary, new reviewer verification,
invitation delivery and the hosted reviewer journey are not implemented or
accepted by this packet. The user has been asked whether an existing learner
email must use a different reviewer address or may hold independent dual access;
no answer or account-policy change is inferred. See
`../implementation/REVIEWER_ACCESS_SEPARATION.md` for the required journey.

Only the reviewer capability is held. The root release coordinator may integrate
this isolation correction with independently accepted capabilities and owns the
single final image/installer/deployment. This packet does not dispatch one.
