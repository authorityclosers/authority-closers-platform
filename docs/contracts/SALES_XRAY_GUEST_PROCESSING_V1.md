# Sales Xray guest processing and ownership

The acquisition session owns the customer's source reservation. A separate
processing principal owns canonical worker rows. Neither a visitor cookie nor a
processing lease is a verified learner, browser login, provider approval, or
permission to access other uploads.

## Composition sequence

1. Provision the configured public learner tenant's processing principal using
   `python -m ac_platform.conversation_intelligence.processing_cli` inside the
   matching application release. Supply the explicit environment, tenant UUID,
   non-secret operator reference and reason; production also requires
   `--allow-production`. The command persists one audited principal per tenant
   and returns its actual identifiers. It creates no login credentials.
2. The HTTP adapter admits a guest or current Academy identity, obtains explicit
   source-upload consent, stores the original bytes privately, and measures
   duration server-side. Browser duration and device/IP hints are not authority.
3. Inside a caller-owned PostgreSQL transaction, call
   `AcquisitionSessions.reserve(MeasuredSource(...), token=..., actor=...)`.
   Admission records one source hash and measured seconds, against the shared
   6,000-second acquisition allowance. Existing acquired usage follows a later
   account claim without resetting that allowance.
4. Call `GuestOwnership(sessions).resolve_processing_actor(submission_id, ...)`
   for the same actual owner. This yields a `ProcessingActor` containing a
   bounded, immutable processing lease. It has no browser `session_id`.
5. Use the actor with canonical intake, exact quote acceptance, source storage,
   local execution and processing-plan commands. Registration automatically
   binds the canonical recording to the reserved source and lease. Intake must
   match both the source hash and reserved duration. Existing provider approval,
   retention, explicit consent, model and budget rules still apply.
6. Local C1 measures the source again. A duration disagreement fails processing.
   Its service-principal entitlement charge is zero because the acquisition
   ledger already charged the source; ordinary learner C1 accounting is unchanged.
   C1 completion alone does not settle the entire provider/report workflow.
7. The C5/report-publication transaction settles acquisition usage with its
   immutable C6 manifest digest, even when the browser has closed. A later
   authorized model/profile report preserves the first completed source charge.
   Uncertain or failed external calls retain their original reservation. A
   browser cannot assert that no work occurred or release charged minutes.

## Reads and claims

`GuestOwnership.require_submission_owner(submission_id, token=..., actor=...)`
returns `SubmissionScope` with the exact recording, processing identity, lease,
usage and source hash. The caller must use those identifiers to select retained
rows, validate canonical report evidence, and apply the guest/account projection.
Never list all recordings for the shared processing principal.

Read admission checks the current actual owner and source retention separately
from execution. An expired processing lease does not erase an owned report or
grant another execution. Revoked recording consent and deleted recordings remain
unavailable. After a genuine account claims a visitor, the old guest bearer alone
cannot reopen it. A current claiming account can reopen retained results without
the old cookie. Processing actors cannot claim accounts or visitors.

`GuestOwnership.request_deletion(submission_id, token=..., actor=..., key=...)`
authorizes the current actual owner and enqueues canonical erasure even when the
processing lease or recording permission has expired. It does not renew execution
authority. Deletion fences readers/workers immediately and keeps the attributable
owner request and canonical erasure audit.

## Integrity and concurrency

- Human quote acceptances, inference tasks and processing plans retain their
  real browser session foreign key. Guest rows instead have a processing-lease
  foreign key. The database requires exactly one binding.
- Processing roles are excluded from ordinary human tenant-context roles.
  Execution rejects any service identity with email verification or login
  credentials, and checks current principal, lease and actual-owner status.
- Canonical command keys include the lease identifier. Two guests using the
  same request key cannot replay each other's recording, quote or run.
- Ownership links are append-only. Principal and lease bounds cannot be edited;
  revocation is one-way. Existing audit history and usage are preserved.
- Acquisition mutations serialize on the tenant transaction lock. Guest workers
  serialize on the individual processing lease and share the service-person
  read lock; a provider call does not take the tenant acquisition lock. They do
  not acquire human person locks in the reverse order used by account requests.

This contract does not activate anonymous provider processing by itself. Runtime
composition still needs the approved source/provider policy, cost cap, abuse
admission, private storage and worker configuration. A cookie/IP address does not
prove that a human has only one account.
