# Company-number calls: owner go-live checklist

Development uses the fake provider; no phone rings and its recording is generated silence.
No provider account, keys, number purchase, production setting or external AI activation
is part of this change.

Before real calls:

- The owner creates an Exotel account, completes KYC and buys an Indian virtual number.
- The owner puts provider keys in Infisical, separately for each environment. Never put keys
  or signed callback URLs in Git, tickets, screenshots or logs.
- Record AC-GOV-AUD-001 approval for Exotel as a processor of call audio, including access,
  authenticated recording retrieval, retention, deletion and the recording region.
- Counsel approves the lead recording notice and the evidence of consent. Call consenting
  leads only; the seller's standing analysis consent does not establish lead consent.
- Counsel confirms applicable TRAI 140/consent requirements and the approved calling flow.
- Record the expected ₹ per minute (including both legs, taxes and recording charges) in
  the internal operations cost record. Prices must never appear in seller-facing responses.
- Confirm the account's recording host and authentication mode. This adapter sends keys
  only to HTTPS Exotel domains and refuses redirects. Current Exotel documentation also
  shows S3 recording URLs; those require a separately verified signed-URL integration,
  never forwarding Exotel credentials to another host.
- Verify signed callback replay, late recording delivery, no-answer, seller-hangup,
  bounded authenticated fetch, seller/tenant isolation, and a real test-number call under
  the separate provider activation approval.
- Verify standing consent, changed terms and revoked consent: recordings are retained
  privately, but analysis waits for the seller's usual upload/Analyse tap without consent.
- Verify Android background push on the lead-alert Firebase app and its notification
  settings. The existing Android app uses `sx_open` launch extras for `/analysis/calls`.
  Foreground report updates use the in-app notification badge; the current native receiver
  handles lead/gold-review data messages only. Do not send report-ready as data-only push.

## Development behavior and limits

The server resumes call intake every 15 seconds and after an authenticated status webhook.
Status comes from the provider API, not callback-supplied facts or URLs. The append-only
company-call ledger keeps provenance and work progress, with a private per-call file lock.
Recording downloads allow three attempts, with bounded streaming and no redirects.
Late recordings are fetched even after terminal status was recorded. The original call
history receives a superseding recording attachment through the existing Lead Desk API.

The canonical upload and plan services enforce standing consent, current upload terms,
AI level, allowance, account profile, current session/membership and provider approval.
No login or consent is invented for a background job: an expired/revoked calling session
leaves the recording waiting for the seller's tap. Uploaded analysis then follows the
existing quick-facts, report and coaching pipeline.

Fake-provider audio never enters hosted external AI. Test composition can use the offline
provider workers; hosted development stops after privately storing the fictional WAV.
This restriction must stay visible in completion evidence: storing a fake recording alone
is not proof of a completed report or of Android delivery.

Pending provider recordings are swept for seven days. Recording files live under the
private recording storage root in `company-calls/<tenant>/<call>.media`; they require the
same storage backup/access controls. Canonical erasure/retention does not yet remove these
inbox copies: real recording intake must remain disabled until lifecycle integration is
verified. Real-call activation is still blocked by all checklist approvals above.

## Provider references

- [Exotel Call Details](https://developer.exotel.com/docs/voice-v1/api-reference/call-details)
- [Recording authentication and optional signed URLs](https://support.exotel.com/support/solutions/articles/3000129985-signed-url-approach-to-access-call-recordings)
- [DisconnectedBy field](https://support.exotel.com/support/solutions/articles/3000111713-call-reports-enhancement-7th-december-2021-)

Read 29 October 2026. Hangup values are retained as the provider supplies them;
missing values stay unknown.
