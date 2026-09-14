# Deepgram Sales Xray integration evidence — 2026-09-14

Status: isolated staging candidate only. No production files, secrets, or
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
- Both hosted compose overlays and the operator template include the separate
  Deepgram identity mount. No key value is present in source, tests, this
  evidence file, or logs.

## Verification

Synthetic tests passed:

```text
145 passed, 17 skipped
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
command can select it. The user-supplied key was not persisted; it should be
rotated because it was exposed in chat.
