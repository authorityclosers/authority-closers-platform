# Deepgram Sales Xray integration evidence — 2026-09-15

Status: isolated staging candidate only. The provider key is stored in the
approved Infisical Development project path; no production files, secrets, or
provider calls were changed by this work.

## Implemented path

- The server provider catalog exposes `deepgram` / `nova-3` as an implemented
  ASR route at the fixed Deepgram `/v1/listen` endpoint. The admin provider
  editor consumes this catalog dynamically, so the provider can be selected
  without adding a secret field to the browser.
- The bounded worker adapter sends binary audio with multilingual transcription,
  punctuation, smart formatting, diarization, utterances, and paragraphs
  enabled. It injects `DEEPGRAM_API_KEY` only inside the isolated provider
  child, through the existing Infisical identity pattern.
- The normalized C2 output preserves raw-response provenance, native timing,
  provider speaker labels, and explicit `unverified` status for speaker
  identity and AudioAtlas alignment.
- The active append-only provider configuration selects the ASR binding for new
  plans. Existing quotes, checkpoints, runs, and reports retain their original
  route.
- This is an explicit alternative route, not automatic failover. If an
  ElevenLabs request fails, times out, or has an unknown external effect, the
  worker does not retry the same call through Deepgram. An admin-approved,
  source-owned configuration must select Deepgram before a new plan is created.
- Deepgram C2 reaches the existing common normalized transcript contract. The
  downstream C4 facts and C5 coaching/report tasks consume that same transcript
  shape; this leaf is therefore full C2-to-common-transcript pipeline support,
  not an admin-only catalog entry.
- Both hosted compose overlays and the operator template include the separate
  Deepgram identity mount. No key value is present in source, tests, this
  evidence file, or logs.

## Credential and data-handling packet

- Infisical: project `AC Infrastructure Secrets`, environment `dev`, path
  `/sales-xray-test/deepgram`, key name `DEEPGRAM_API_KEY`. The parent-folder
  duplicate was removed after the provider-scoped copy was verified masked.
- Request policy: every Deepgram pre-recorded request sets
  `mip_opt_out=true`; Deepgram documents that opted-out request data is
  retained only for the duration necessary to process the request.
- Provider terms gate: the real approved call remains blocked until AC records
  consent, provenance, retention, professional review, provider authorization,
  and an allowance/budget reference in a superseding staging approval.
- Pricing input reviewed 2026-09-15: Deepgram lists Nova-3 Multilingual
  pre-recorded at `$0.0052/min` Pay-As-You-Go. A 60-second probe therefore has
  an estimated provider charge of `$0.000087` before taxes or account-specific
  terms; exact billing must be confirmed from the provider usage record.
- The source-backed pricing snapshot is stored at
  `docs/evidence/pricing/deepgram-nova-3-multilingual-20260915.json` with
  SHA-256
  `e4ac299a8e030cd9b6e22d517293fb979bf9bd8797f4d67faee86a28e3ffd1a7`.
  The snapshot records `$0.0052/min` as a planning input and explicitly does
  not treat the planning USD-to-INR rate or account credit as billing or
  execution authorization.
- Account read-only check: the Deepgram console showed the Authority Closers
  project with `$200.00` credit, Nova 3, and Multilingual access. This is not a
  claim that the staging worker is activated.

Sources reviewed:

- https://deepgram.com/pricing
- https://developers.deepgram.com/docs/the-deepgram-model-improvement-partnership-program
- https://developers.deepgram.com/reference/speech-to-text/listen-pre-recorded
- https://deepgram.com/terms

## Bounded public connectivity test

On 2026-09-14, one non-customer request was sent through the Infisical
Development path above to Deepgram's official public `spacewalk.wav` sample.
The request used Nova-3, `language=multi`, `mip_opt_out=true`, smart format,
punctuation, diarization, utterances, paragraphs, and a non-customer test tag.
The raw response was handled outside Git and is not retained in this evidence
file.

Measured result:

```text
HTTP status: 200
Wall latency: 2355 ms
Provider/model: Deepgram Nova-3
Audio duration: 25.933313 s
Utterances: 8
Speakers detected: 1
Estimated charge at $0.0052/min: $0.002248
```

This proves credential injection, endpoint reachability, request authentication,
and response normalization at the provider boundary. It does not prove that
the frozen hosted staging release has been activated or that the real approved
customer recording is cleared for external processing.

## Runtime activation prerequisites

The following must all be present in a superseding staging approval before an
operator selects this route:

1. A release containing the isolated Deepgram leaf and hosted identity mount.
2. A source-owned provider configuration with `deepgram` / `nova-3`, the exact
   `transcribe_deepgram_nova3` operation, recipe/profile/prompt revisions, and
   an append-only activation record.
3. A matching Deepgram C2 stage approval binding consent, provenance,
   retention/privacy, professional review, provider terms, endpoint,
   credential reference, model, price/allowance, budget, and execution scope.
4. The mounted Infisical Development identity at
   `/sales-xray-test/deepgram` containing `DEEPGRAM_API_KEY`, plus runtime
   health/readback evidence without exposing the secret.
5. A permitted source recording and the existing reservation, receipt, and
   reconciliation gates. The `$200.00` account readback is an account fact,
   not permission to process a customer call.

The existing ElevenLabs/Gemini reports are not silently rewritten. A new
approved Deepgram plan would create its own source-bound transcript, receipts,
and downstream analysis records so results can be compared and superseded in
the normal audit trail.

## Verification

Synthetic tests passed:

```text
145 passed, 17 skipped
```

Latest focused provider/inference tests after the retention opt-out hardening:

```text
40 passed
Ruff: All checks passed
```

The tests cover the provider catalog, binary request shape, query parameters,
credential header isolation, source binding, Deepgram response normalization,
broker operation admission, route admission, and hosted compose input
validation. Ruff reports three pre-existing `UP038` findings in untouched
style areas; the new route-selection import error is fixed.

## Activation boundary

The current hosted approval artifact does not contain a Deepgram C2 stage or a
Deepgram credential reference. Therefore this candidate must not send the real
approved recording to Deepgram yet. A superseding staging approval must bind
the provider terms, privacy/retention, professional gate, pricing/allowance,
credential reference, model, and budget before the existing Admin activation
command can select it. The key should be rotated after testing because it was
exposed in chat.
