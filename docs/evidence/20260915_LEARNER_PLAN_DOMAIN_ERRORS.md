# Learner plan errors preserve the HTTP and transaction boundary

The learner-host submission dependency yielded its authenticated transaction
outside the `ConversationError` handler used by standalone accounts and guests.
When provider allowance validation denied an accepted plan, the learner route
returned HTTP 500 instead of the existing private HTTP 403 response.

The learner branch now translates the domain error only after the authenticated
transaction unwinds. Authentication, tenant ownership, origin checks, provider
limits and error statuses are unchanged. This does not authorize another call.

## Reproduction and checks

The regression uses real loopback PostgreSQL, migrations, an HTTP upload of a
synthetic one-second WAV, native audio inspection, canonical guest-to-account
claim, quote creation and plan acceptance. It injects the observed domain denial
at `ConversationAuthority.validate_quote`; no external provider runs.

The pre-fix receipt `peer-learner-plan-error-before2-20260915.xml` records one
failure and one pass: learner HTTP 500 versus standalone private HTTP 403.
The fixed regression asserts HTTP 403 with private/no-store and Cookie variance,
an unchanged quoted plan without an acceptance command, and no inference task
or stage authorization. The final suite also covers learner authentication,
host/origin boundaries and bounded upload request deadlines.

Receipts are retained outside Git at `D:/AC-authority-closers-release-audit/`.
Final receipt: `peer-learner-plan-error-final-20260915.xml`.
Final result: **7 passed in 46.32 seconds**. Ruff lint and formatting checks,
targeted mypy (`conversation_submissions.py`) and `git diff --check` passed.
Earlier local attempts were not successful receipts: the initial fresh worktree
lacked its native build; a later combined run used a temporary socket path over
the existing 107-byte limit. The verified native binary/build manifest was
reused, and the final run uses the shorter `D:/acxp15-a1` temporary root.

## Bounded continuation recommendation

For the separately owner-approved test, preserve the acquisition policy UUID
and supersede only the C5 lifetime `max_requests` from one to two in the pinned
approval. The old uncertain attempt remains counted by its stable approval ID.
Keep C2/C4 inputs and limits, the current exact provider/model/output bound,
price ceiling and cumulative budget unchanged. Quote and accept one new plan.
Each plan still admits only one C5 execution; completed C2/C4 checkpoints remain
reusable. Do not rotate the policy UUID, erase reservations/history, or retry an
uncertain task. This is a source-reviewed recommendation, not runtime activation
or proof of a successful generated report.
