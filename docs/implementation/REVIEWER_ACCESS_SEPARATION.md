# Reviewer access separation

## Accepted requirement

The user's 2026-09-13 instruction supersedes the earlier implementation choice
in `SALES_XRAY_REVIEW_API_CONTRACT.md` that placed assigned reviewers inside the
Academy login and learner shell. Reviewers must use special access, learners
must not encounter reviewer UI, and Admin must manage invitations and inspect
review details. An email invitation must never create learner membership.

Existing learner accounts, enrollments and accepted feedback remain unchanged.
Removing an entry point does not delete or rewrite that history.

## Current repair boundary

- Normal learner login, registration, email verification and password recovery
  do not consume a review invitation or redirect to a reviewer screen. Normal
  course, activity and Sales Xray learning continuations remain supported.
- Legacy Academy reviewer pages must return 404. Learner navigation must not
  import the reviewer navigation guard or expose assigned-review links.
- Generic learner sessions must not authorize review read, playback, acceptance,
  history or submission. A matching assignment ID alone is insufficient.
- Admin detail reads use the existing operations tenant and admin permission
  checks. They do not impersonate the assigned reviewer or call reviewer APIs.
- Source permission, retention and exact report/checkpoint binding remain
  mandatory. Feedback and revocations remain append-only.

## Independent reviewer admission

2026-09-14 policy resolution: the user authorizes one global AC Person/email to
hold independent learner and reviewer access. Dipak, Suyash and Admin use their
existing identities for the separate workspaces. Reviewer authority must not
convert or revoke learner membership and must never grant learner enrollment.
The implementation lane starts from frozen `30cd7a8`; the release owner retains
deployment and provider operations. The historical same-email question below is
resolved by this instruction and is not a remaining approval gate.

A dedicated reviewer session must be authenticated and scoped by the server.
It requires independent reviewer authority, never learner membership inferred
from an invitation. Every assignment request must check that authority together
with the exact reviewer, tenant, assignment, expiry and revocation state.

An invitation token authorizes only its intended invitation claim; it does not
replace verified authentication. Tokens remain outside query strings, analytics,
browser storage and logs. New-account verification must not call learner
provisioning or claim the learner consent record covers a reviewer workflow.

Migration `20260914_0038` adds a session audience (`account` or `reviewer`),
requires reviewer sessions to have no selected tenant, adds encrypted mailbox
challenges, and changes the reviewer assignment foreign key to `persons.id`.
The recording owner's membership and all source permission checks are retained.
The migration preserves assignment and audit history and is forward-only.

The Admin application's `/reviewer` routes use their own shell, queue, login,
invitation, verification, report, transcript, source playback and feedback views.
The reviewer cookie is host-only, HttpOnly, Secure in deployed environments,
SameSite=Lax and distinct from the ordinary account cookie. Generic identity
resolution rejects reviewer sessions even when their cookie is renamed.
Reviewer resolution rejects account sessions. The API resolves current authority
from the canonical session, active Person and exact assignment on each request.

Invitations use `/reviewer/invite#token=...`. An unauthenticated invitee requests
a separate one-use, 15-minute sign-in link delivered by the transactional
outbox/worker. The sign-in challenge binds to a random HttpOnly browser nonce;
a copied link cannot substitute an account into another browser's session.
Only successful mailbox proof creates or verifies the global Person. It never
creates Membership, enrollment, or learner consent records. Existing identities
retain their consent, account credentials and memberships. Invitation acceptance
and reviewer session issuance commit together before a session cookie is sent.

Reviewer API routes are under `/v1/reviewer`; they accept only the configured
Admin host and mutations require that host's exact Origin. The production page
guard uses the internal API transport with a canonical Admin Host. Review source
access checks the exact report, source, checkpoint, recipient, tenant, assignment
expiry/revocation and retention permission. Legacy learner reviewer routes stay 404. Admin detail reads retain their own operations authority and never assume
the reviewer's identity.

Reviewer submissions use durable immutable feedback records and canonical audit
events, including for a Person with no tenant membership. Different allowed
lenses can submit independently; retrying a submission returns its existing
receipt. Saved feedback remains available to authorized Admin after revocation.
No feedback is promoted into official scores, progress, payment or access state.

## Release acceptance

Final reviewer acceptance requires an invited new reviewer to
verify their identity, enter the dedicated workspace without any learner
membership, read and play only an assigned source, submit and reload feedback,
and lose access after revocation or expiry. Learner sessions must fail those
same direct API and URL attempts. Admin must retrieve feedback by exact
assignment ID even when it is outside the latest queue page.

The implementation and local acceptance evidence are recorded in
`REVIEWER_ACCESS_VERIFICATION_20260914.md`. Hosted delivery, CI integration and
deployment belong to the release owner. Local tests use synthetic source and
the fake email adapter behind the real dispatcher; they do not claim an email
was delivered through the live provider or that the new artifact is deployed.
