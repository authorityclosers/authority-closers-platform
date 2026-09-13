# Reviewer invitation integration and recovery evidence

Canonical backend commits7ffd092 and14781f6 were integrated as9630221 andbf221c4.
Invitation UI1b9696b was selectively adapted onto the primary fa1dcbc reviewer UI,
retaining the strict assignment/report adapters and durable saved-review history.

Admin can queue email invitations for an exact saved run and revoke a known ID,
including after reload. Only confirmed server receipts render success. Create
receipts must match the requested run, email under the canonical case-insensitive
comparison, lens set and expiry; revoke receipts must match the ID and revoked
state. Queueing does not claim inbox delivery. There is no invented invitation
list endpoint. Server-accepted invite receipts are retained only for this visit.

Unchanged failed intents reuse their request key. Editing the run, email, lenses
or expiry produces a fresh key. Synchronous validation errors are caught, duplicate
clicks are guarded before rendering, and known-ID revocation has visible success.

Academy removes the invitation fragment while preserving Next history state and
keeps the token in memory through effect replay. A temporary failure can retry
with that token. Normal password login, registration, recovery requests and
verification-help links carry the fragment locally and exclude it from auth/API
provider requests. Registration still requires consent. Google sign-in is offered
from the invitation in a token-free separate tab, followed by explicit acceptance
retry. Nothing is written to localStorage/sessionStorage for this handoff.

## Validation on the integrated source

- Admin review/invitation:28 tests passed across4 files.
- Learner review, invitation, auth continuity/hydration and shell:56 tests passed
  across13 files. The three new auth-chain tests passed after correcting a test
  selector/assumption to verify actual consent enforcement at submit.
- Backend HTTP/contracts/security:23 tests passed. Actual PostgreSQL assigned
  review, invitation, ACL/revocation/expiry, metadata-only UX and erasure:6 passed
  in30.81s, receipt integrated-review-invites-02.xml.
- Both complete app ESLint checks and Next production builds passed, including
  TypeScript and the new /sales-xray/review/invite route.
- Source formatting, browser-script Ruff and git diff checks passed.

The first combined PostgreSQL attempt stopped in C1 fixture setup because this
isolated checkout lacked the reviewed native cache. No application state was
changed to bypass it. The existing ignored binary and build manifest were copied
only after their source and binary hashes matched. The replay above passed.
Provenance is in external integrated-invite-native-cache.json.

## Actual browser, HTTP and PostgreSQL

The extended scripts/prove-review-assignment-browser.py runs both journeys with
REVIEW_UI_INVITATIONS=true. Backend code is frombf221c4; front-end source hashes
are recorded in committed review-invitations-browser-20260913 JSON receipts.

Learner receipt integrated-invitation-browser-learner-01:1 passed in47.55s.
A locally generated invitation was accepted through the real HTTP route(201),
opened the exact assignment, and left no token in browser storage. The accepted
review saved technical feedback plus a transcript correction(201), replayed to
the same ID, reloaded with one durable feedback row, and read private audio(206).
Dirty sidebar/G H navigation cancellation,390/320px widths and dark rendering
also passed with no page errors.

Admin receipt integrated-invitation-browser-admin-01:1 passed in32.80s.
Actual HTTP create-assignment201 and revoke200 survived reload. Invitation
create201 was rendered as queued; after reload the known invitation ID revoked
with200 and visible confirmation.390/320px screenshots have no horizontal
overflow. The configured Academy link and existing assignment screens passed.

Only synthetic identities and one-second WAV input are used. Session resolution
and shell profile reads are fixtures; the mounted HTTP router, services, private
storage and disposable PostgreSQL are real. Learner uses its production Next
build; Admin uses explicit local development preview and browser forwarding to
the real API. This does not prove production authentication, edge routing, inbox
delivery, Linux standalone startup or external provider execution. No real email
or paid provider request was sent by these checks.

Backend migration0035 populated-history proof remains documented in
20260913_REVIEW_INVITATION_INTEGRATION.md. Final runtime deployment remains owned
by the active consolidation controller. The old3309ac0 workflow is superseded
for full invitation acceptance, although its complete PR validation passed.

## Password-reset and verified-email completion

The password reset form now retains the invitation on both its fresh-reset link
and its post-reset sign-in link. The generic reset or verification token is
removed independently; the invitation remains in the local fragment. A completed
email-verification page also points back to the invitation when that local
handoff is present.

Five invitation/auth tests cover password sign-in, registration consent,
verification help, recovery requests, successful reset, and successful email
verification. Reset receives only its own token and the new password; verification
receives only its own token. Neither request contains the review invitation.

The follow-up run passed 29 tests across four invitation/auth, password reset,
email-continuity and Sales-continuity files. This adds two tests to the earlier
56-test learner selection. Scoped ESLint passed; the updated production learner
build passed again. These auth-link changes do not alter the already verified
review assignment or invitation browser screens.

## Full-suite CI regression correction

The bd51eec application run 34767467799 passed formatting, lint and type checking,
then found one learner regression: normal login had lost the existing guidance
that first-time Google users should register. The invitation adaptation now keeps
"First time here—including with Google?" for normal sign-in while preserving
invitation-specific text in the invitation flow. The existing assertion remains.

After that correction, the complete learner suite passed: 109 files and 1,775
tests in 45.56 seconds. The failed CI log is retained outside Git as
reviewer-bd51eec-ci-failed.log. No check was removed or relaxed.

The complete Admin suite also passed: 37 files and 751 tests in 41.05 seconds.
The normal-login correction passed scoped ESLint, Prettier and diff checks.
