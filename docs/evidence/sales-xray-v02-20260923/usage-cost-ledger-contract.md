# Internal usage and cost ledger: requested contract

Date: 2026-09-23. Status: **design and gap analysis, not implemented or activated**.

The owner requested company cost accounting per user, call, audio second/minute, processing stage, analysis and provider request. This extends the separate report-quality benchmark packet. It does not change customer pricing, entitlements, credits or the existing paid-test ceiling. The local UI review remains the active delivery priority.

## Record usage before normalizing it

AC, LMS and Sales Xray share the canonical AC person/account identity. The owner explicitly confirmed this on 2026-09-23. Attribute signed-in usage to that stable person identifier and the existing workspace membership, with a product/surface dimension for reporting; do not create a separate Sales Xray user database. Usernames, email addresses and display names are mutable profile fields, not ledger keys. Authentication is shared; product entitlements and workspace authorization still follow their existing authorities.

Guest attempts retain their original visitor/session attribution. A verified claim links them to the canonical person through an append-only attribution event, without rewriting history or counting the same spend twice. Account merges and workspace transfers also require explicit canonical identity events; matching email strings is not proof. A person belongs to multiple workspaces only through authorized memberships, and company rollups must not disclose another workspace's calls. Per-person totals across products sum unique attempt identities and disclose unclaimed guest usage separately.

One append-only attempt record should identify workspace/user, recording/source hash, run, stage, task/chunk, attempt, provider request, exact provider/model, and immutable settings/prompt/price revisions. An intentional retry is another attempt; a redelivered receipt for the same attempt is not another charge. Existing provider reservations and receipts should be linked, not duplicated or replaced with a competing budget authority.

Counters retain their real units: source duration, provider-billed duration/channels, input tokens, cached input tokens, generated output tokens, reasoning tokens, worker CPU time, storage byte-hours and egress bytes. Only counters actually observed may be called measured. A missing counter remains unknown, not zero. Generation stages must retain separate counters before a run or user total is produced.

An internal normalized unit can be a display or allocation measure; it must not erase the underlying units or imply that one speech minute equals a fixed number of LLM tokens. Customer-facing credits require their own approved commercial policy.

## Money has an evidence class

Keep these values separate in the API, Admin and CLI:

| Value | Meaning |
| --- | --- |
| Reservation / maximum quote | Authorization exposure; not observed spend |
| Usage-derived estimate | Observed usage multiplied by a dated price snapshot; still not an invoice |
| Reconciled provider charge | Matched to a provider billing receipt or invoice allocation |
| Uncertain charge | A dispatched request without sufficient settlement evidence |
| Allocated shared cost | A documented allocation of common infrastructure or shared generation |

Corrections append an adjustment/superseding receipt. Preserve the original attempt, price source and reconciliation evidence. Sum adjustments without counting their superseded value twice. Budget reservation/release/settlement continues through the existing canonical operational service, never a direct SQL edit.

FX, tax treatment, account plan, discounts, billing granularity, cache charges and price effective dates belong to a versioned pricing contract. Account-specific paid statements are required before calling a value final company cost. Existing Admin estimates use a planning FX of INR 100/USD and explicitly declare `is_billing_rate: false`.

## Views and denominators

- Request and stage: show native counters, estimated/confirmed charge, latency, attempts and unresolved exposure.
- Analysis: sum every original/repair/fallback attempt, including charged failures, plus separately identified infrastructure allocation.
- User/workspace/company: aggregate the same attempt identities by date cohort; all rollups must reconcile to the same totals.
- Cost per admitted source minute: cohort cost / unique admitted source minutes. Reprocessing does not increase the unique-source denominator.
- Cost per delivered minute: all cohort cost, including failures / source minutes with an accepted delivered report. Label the cohort and delivery cutoff.
- Cost per accepted report: all cohort cost / accepted reports. With no accepted reports the result is undefined, not zero.
- Cost per second: a normalized rate calculated from the corresponding minute denominator. It is not a measurement of what each second of speech cost.
- Report microsection: exact only when independently generated and metered. A shared C5 request cannot yield measured prices for Overview/Prospect/Coaching individually. Any split must say **allocated**, disclose its rule and reconcile to the request total.

Margin analysis needs actual net revenue, fees, refunds/support and infrastructure assumptions. Show contribution and fully loaded cost separately. No profit or optimum is established by a token-price comparison alone.

## Public rate verification (not account invoices)

Official pages retrieved 2026-09-23:

- [ElevenLabs API pricing](https://elevenlabs.io/pricing/api): Scribe v2 base USD 0.22/hour, equivalent to approximately USD 0.003667/source minute before applicable extras/taxes. This is transcription alone, not a Sales Xray end-to-end cost.
- [Gemini pricing](https://ai.google.dev/gemini-api/docs/pricing): Gemini 3.8 Flash standard USD 0.75 per million input tokens and USD 3.75 per million output tokens including thinking through 2026-12-31; the page lists higher rates from 2027-01-01. Gemini 3.1 Pro Preview has prompt-length-dependent tiers. Price validity cannot be an undated constant.
- [Deepgram pricing](https://deepgram.com/pricing): prerecorded Nova-3 multilingual PAYG base USD 0.0052/minute. Applicable features, channel rules and account tier need separate verification.
- [Groq model catalog](https://console.groq.com/docs/models): lists model-specific token rates. Catalog presence is not qualification of this application's adapter, report fidelity or language quality.

These sources verify published base rates only. They do not establish current account discounts, final INR payments, actual tokens consumed by a call, or which provider has better sales-report quality.

## Minimum acceptance before operational use

1. Duplicate receipt delivery changes neither charge nor usage totals; an actual second attempt is counted.
2. Failed/uncertain paid attempts are visible; unknown totals cannot be shown as complete.
3. Per-user, per-stage, per-run and company totals reconcile, without cross-workspace disclosure.
4. Price/FX changes affect new calculations under a new revision; historical evidence remains inspectable.
5. Cached/reasoning tokens and channel duration are handled under the provider's actual billing contract, with no double counting.
6. Per-section allocations sum to their parent charge and are never labeled measured.
7. Cost views and exports cannot dispatch jobs or settle a budget account.
8. Benchmark rows retain corpus/configuration/usage lineage. A cheaper configuration is eligible only after quality and reliability gates pass.
9. One canonical person can be reported across AC/LMS/Sales Xray without duplicate accounts or charges. Renaming a profile does not change historical attribution; guest claiming, account linking and tenant boundaries have explicit regression cases.

The current hosted benchmark area and offline fixture runner are insufficient for these measurements. Implementation and live receipt reconciliation remain outstanding; no paid experiments or production changes were performed for this document.
