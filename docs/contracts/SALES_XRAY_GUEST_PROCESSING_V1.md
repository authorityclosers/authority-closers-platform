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
silently grant a new execution. A processing plan that was explicitly accepted
before that lease expired may finish its exact source-bound stages until the
plan's own bounded expiry; this continuation keeps the original lease and
acceptance as immutable evidence and still checks revocation, deletion,
retention, owner, provider and budget gates. If a held plan needs a fresh
quote, the current owner may use the existing quote action to append one
bounded continuation grant. That grant binds the original tenant,
submission, recording, source hash/revision/generation, usage and lease plus
the authenticated account or visitor owner. It does not edit the lease,
reopen acquisition minutes, reset request limits or dispatch a provider;
the normal exact plan quote and acceptance remain required. Revoked recording
consent and deleted recordings remain unavailable. After a genuine account
claims a visitor, the old guest bearer alone cannot reopen it. A current
claiming account can reopen retained results without the old cookie. Processing
actors cannot claim accounts or visitors.

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
- Ownership links and continuation grants are append-only. Principal and lease
  bounds cannot be edited; revocation is one-way. Existing audit history and
  usage are preserved.
- Acquisition mutations serialize on the tenant transaction lock. Guest workers
  serialize on the individual processing lease and share the service-person
  read lock; a provider call does not take the tenant acquisition lock. They do
  not acquire human person locks in the reverse order used by account requests.

This contract does not activate anonymous provider processing by itself. Runtime
composition still needs the approved source/provider policy, cost cap, abuse
admission, private storage and worker configuration. A cookie/IP address does not
prove that a human has only one account.

## Release-approved public provider policy

Hosted approval bundle schema `ac.sales-xray.hosted-approval/1` may include the
optional `acquisition_policy` object. Its exact JSON shape is:

```json
{
  "schema": "ac.sales-xray.acquisition-provider-policy/1",
  "id": "<release-policy-uuid>",
  "tenant_id": "<configured-public-tenant-uuid>",
  "processing_person_id": "<provisioned-processing-principal-person-uuid>",
  "authorization_ref": "ref:acquisition/approval",
  "expires_at_epoch": 0,
  "max_recordings": 1,
  "max_source_bytes": 1,
  "max_stored_source_bytes": 1,
  "stages": [
    {
      "stage": "C2|C4|C5",
      "configuration_sha256": "<sha256>",
      "provider_id": "<approved-provider>",
      "model_id": "<approved-model>",
      "recipe_revision": "<approved-recipe>",
      "permission_ref": "ref:...",
      "retention_ref": "ref:...",
      "professional_gate_ref": "ref:...",
      "pricing_ref": "ref:...",
      "provider_terms_ref": "ref:...",
      "privacy_ref": "ref:...",
      "credential_ref": "ref:...",
      "free_allowance_ref": "ref:...",
      "no_paid_overage_ref": "ref:...",
      "privacy_revision": "<revision>",
      "privacy_notice": "<notice>",
      "expires_at_epoch": 0,
      "max_requests": 1,
      "entitlement_seconds": 0,
      "zero_cost_basis": "verified_free_allowance|paid_pricing_evidence",
      "price_evidence_sha256": "<sha256>",
      "max_cost_paise": 0,
      "max_source_duration_ms": 1,
      "max_input_bytes": 1,
      "max_completion_tokens": 0,
      "profile_sha256": null
    }
  ]
}
```

The three stages are ordered `C2`, `C4`, `C5`; each retains the same bounds as
an exact `StageApproval`. At runtime the server derives an exact stage approval
ID with UUID5 over the policy ID, configured tenant, provisioned processing
person, source SHA-256 and stage. The source hash comes from the measured
server receipt and the person/tenant/lease come from `ProcessingActor`; an
ordinary `ActorContext` cannot select this policy. Canonical intake permission
and later processing-plan acceptance remain required, and provider stages keep
zero user entitlement. The router recomputes this exact stage from the source
binding and its approval reference, rather than trusting a caller-selected
provider or stage.

When `acquisition_policy` is absent, it is omitted from canonical JSON so
existing `/1` bundle bytes and digests remain unchanged. Reporting composition
binds the policy's credential references at startup even when no public source
has been measured yet. The policy adds no browser credential, no wildcard
source grant and no second acquisition-minute grant.
