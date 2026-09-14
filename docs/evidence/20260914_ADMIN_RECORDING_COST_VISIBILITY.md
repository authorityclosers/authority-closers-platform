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
  per-unit rate is available.

The current canonical receipt stores token or provider usage counters and a
`pricing_ref`, but no persisted unit-rate snapshot.  The accepted pricing
evidence is an approval reference and quote ceiling, not a token price table.
Therefore this leaf returns `usage_estimate_paise: null` with
`usage_estimate_state: "rate_unavailable"` when usage is recorded.  The UI
labels that state as “Unavailable · no approved rate” and keeps the pending
provider reconciliation state separate from both the quote and settlement.

The implementation reads existing `jobs.provider_receipt` rows through the
tenant-scoped inference task IDs.  It does not call providers, alter budgets,
settle charges, or expose receipt payloads beyond allowlisted provider/model,
request ID, and numeric usage counters.
