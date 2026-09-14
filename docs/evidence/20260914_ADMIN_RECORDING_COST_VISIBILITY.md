# Admin recording cost visibility

This leaf adds read-only provider receipt visibility to the Admin Sales Xray
recording inventory.  Each current-scope C2/C4/C5 task may now expose its
provider, model, request identifier, bounded usage counters, receipt state,
and provider cost state under `latest_run.provider_stages`.

The cost payload keeps four separate facts:

- `estimate_paise` is the approved quote ceiling.
- `reservation_paise` is the amount currently represented by canonical budget
  reservations.
- `actual_paise` is populated only from canonical settlement receipts.
- `usage_estimate_paise` is populated only when an approved source-backed
  per-unit rate and matching usage units are available.

The release's immutable pricing evidence supplies two matching snapshots:

- ElevenLabs `scribe_v2`: `$0.22/hour`, applied to native measured duration.
- Gemini `gemini-3.8-flash`: `$0.75/1M` input and `$3.75/1M` output tokens,
applied to the provider receipt's input/output counters.

The source artifacts are `pricing-evidence-elevenlabs-v6.json`
(`294beecdac8d241c8fdee210eb8802e05f54a8369a748d90a0c823a10bae6448`) and
`pricing-evidence-gemini-v6.json`
(`d2be76be50be45b17b66aa528eeff86806705bf9e90dce36772c715e3c312fde`) under
`D:\AC-authority-closers-release-audit\activation-20260914\enabled-v4-params-final-c437c17`.

Both snapshots use the release's explicit planning conversion of INR100/USD,
source date `2026-09-14`, and preserve their pricing reference and evidence
hash in the API.  Paise are rounded upward to the next integer for a
conservative display estimate.  Each snapshot is marked
`is_billing_rate: false`; no provider invoice or settlement is inferred.  A
stage with missing units or an unknown model remains unavailable, and a
recording with only some stage estimates is labelled `partial`.

The snapshots carry `evidence_release_sha`
`0847db5d3ca1ed825b68c226713d0f52d11683b1`, the release that supplied the
immutable pricing evidence. This provenance field is not the serving release
and does not claim that the current deployment is that SHA; the API carries it
alongside each evidence hash so operators can audit the rate source.

The implementation reads existing `jobs.provider_receipt` rows through the
tenant-scoped inference task IDs.  It does not call providers, alter budgets,
settle charges, or expose receipt payloads beyond allowlisted provider/model,
request ID, and numeric usage counters.
