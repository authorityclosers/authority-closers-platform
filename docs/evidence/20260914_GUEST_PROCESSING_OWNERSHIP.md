# Guest processing ownership evidence

The candidate adds migration0037 and the non-login processing/ownership contract
in `docs/contracts/SALES_XRAY_GUEST_PROCESSING_V1.md`, on parent `d2f0fea`.
No runtime tenant, identity, provider, database or deployment was changed.

## Verified behavior

- One canonical principal per tenant creates an empty processing ledger, with no
  email verification, password, provider login, browser session, budget or grant.
  Replay requires the ledger to exist; incomplete restored history is not reset.
- Guest source reservation and processing lease remain distinct from human
  identity. Canonical intake and actual local C1 execution bind the measured
  source without charging acquisition minutes twice.
- Another guest/account cannot read or replay the recording. A genuine account
  claim retains the original source usage and private owner scope.
- Expired/revoked leases stop execution. Retained owned results can still be
  resolved and deleted. Deletion enqueues one canonical erasure job and records
  the actual owner's request.
- Processing admission does not hold the tenant acquisition lock. A retained
  source read fences only that visitor's claim/revoke; another visitor can still
  create a session and reserve audio.
- Processing identities do not appear as real users or staff in the admin CRM.

## Checks and receipts

Luna's final real-Alembic, disposable loopback PostgreSQL run passed **24 tests**
in **27.98 seconds**, across the new guest suite and existing acquisition suite.
The raw redacted log and JUnit are in `guest-processing-20260914/`; their SHA-256
and byte counts are recorded in `receipt-index.json`.

Root also passed the existing canonical conversation/acquisition PostgreSQL
suites: **25 tests**. These overlap the 24-test run and are not additive counts.
Conversation unit tests passed **607**, with one explicit POSIX-ownership skip;
the native synthetic audio tests ran. Admin directory tests passed **14**.
Mypy and Ruff passed for the changed application source.

Independent Luna review found no remaining double-charge or lock-order issue.
The empty-ledger setup issue was corrected. Existing-principal ledger absence
explicitly fails rather than inventing restored history.

## Remaining release verification

The guest HTTP/source/report consumer is a separate active implementation owned
by the Sales Xray task. It must consume `SubmissionScope` and the guest/account
projection for retained reads; ordinary human-owned canonical recording routes
cannot read the shared processing principal's recordings. No production guest
read success is claimed by this packet.

The C5 report transaction now settles acquisition against the first C6 manifest,
including when the browser closes. A complete guest C2–C6/provider report test
remains required with the incoming HTTP/Gemini integration. Provider expenses
remain reserved pending real cost reconciliation; no fake zero invoice is emitted.
Real provider calls, hosted activation, public abuse admission and staging/
production browser journeys remain release dependencies.
