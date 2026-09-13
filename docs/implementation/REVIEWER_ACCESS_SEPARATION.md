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

## Reviewer admission still to implement

A dedicated reviewer session must be authenticated and scoped by the server.
It requires independent reviewer authority, never learner membership inferred
from an invitation. Every assignment request must check that authority together
with the exact reviewer, tenant, assignment, expiry and revocation state.

An invitation token authorizes only its intended invitation claim; it does not
replace verified authentication. Tokens remain outside query strings, analytics,
browser storage and logs. New-account verification must not call learner
provisioning or claim the learner consent record covers a reviewer workflow.

The same-email rule is awaiting the user's answer: reject an invitation to an
existing learner email and require another address, or allow one person to hold
independent learner and reviewer access. The current global email-unique Person
and single-role tenant membership cannot silently decide this policy. No existing
membership will be converted or revoked to make an invitation work.

## Release acceptance

The removal and denial tests are an interim correction, not proof of a working
reviewer login. Final reviewer acceptance requires an invited new reviewer to
verify their identity, enter the dedicated workspace without any learner
membership, read and play only an assigned source, submit and reload feedback,
and lose access after revocation or expiry. Learner sessions must fail those
same direct API and URL attempts. Admin must retrieve feedback by exact
assignment ID even when it is outside the latest queue page.

Hosted invitation delivery and the final deployed artifact require separate
evidence. The reviewer capability remains held until those requirements pass;
unrelated capabilities may continue under their own release gates.
