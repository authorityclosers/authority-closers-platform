# Analyse my calls automatically (standing consent)

Owner approval, 26 Oct 2026, for v0.96: "approve standing consent for auto-analysis".
Code: `packages/python/ac_platform/call_ai/auto_consent.py`.

## What changes for a seller

Today every call starts from one tap, "Analyse this call". That tap carries the call's own
consent: "The customer knows this call is recorded, and I agree to these terms". A seller may
instead agree once per organisation. After that, each call they record there is analysed as
soon as its recording arrives, at the organisation's AI setting. Everyone else keeps the
tap, and so does anyone who turns it off.

## The words (English, v0.96)

Title: **Analyse my calls automatically**

> When I record a sales call with Sales X-Ray in {organisation}, the customer knows the call
> is recorded. Sales X-Ray may analyse each call I record here as soon as it arrives, at my
> organisation's AI setting. I can turn this off in Settings, Privacy, at any time.

Hindi and Marathi wait for the owner's (or the sales lead's) review of the translated words.
Until then the API refuses them.

The words are version-bound (`NOTICE_VERSION = auto-analysis-2026-10-26`), and a unit test
pins them. To change them, add a new version; never edit the words in place. People who
agreed are then asked again.

## The record

Every choice is an append-only audit event:
- `resource_type` is `sales_xray_auto_analysis` and `resource_id` is the person's id, in the
  organisation's chain;
- `action` is `conversation.auto_analysis_consent.v1`;
- the payload holds the decision (`granted` or `withdrawn`), the notice version, the words'
  hash, the language, and the hash of the upload terms the person had in front of them.

The newest event is the choice. Turning it off appends a new event, and nothing is
overwritten.

Reading the choice:
- **ask**: never chosen, or the words have changed since;
- **on**: granted, in the current words;
- **off**: withdrawn.

## When a call starts by itself

A call is analysed in two steps, as in the studio: its recording is uploaded, then its
processing plan is quoted and accepted. With the consent on, the app does both without
a tap:
1. It uploads the found recording with `X-Upload-Consent: standing` instead of `accepted`.
2. It accepts the plan (`POST …/submissions/{id}/plan`) with `X-Upload-Consent: standing`.

At each step the server checks that all three hold:
- the seller's own consent in this organisation is on;
- it was given for the same upload terms now in force, so a new AI provider or a new
  retention asks again;
- the seller's AI level is not Off.

The plan step also requires the call to be the seller's own: a consent never starts
someone else's call. Otherwise the server answers 409, and the call waits for its tap.
The upload is checked again after the bytes arrive, so turning it off mid-upload holds
that call too.

What gets recorded:
- **The upload's consent receipt** includes the consent event, and an audit event
  `conversation.auto_upload_accepted` names it.
- **The plan's own receipt** stays exactly as for a tap, because the workers re-verify it
  before every paid stage. A separate audit event, `conversation.auto_analysis_started`,
  names the consent event and the plan it accepted.

## API

- `GET /v1/sales-xray/call-ai/auto-analysis`: state, since, the agreed terms' hash, the AI
  level, `can_start`, and the notice (the words with the organisation's name, and their
  hash).
- `POST` on the same path with `{decision, policy_sha256, upload_policy_sha256, language}`.
  Turning on needs the words' hash as shown and the upload terms' hash in force. Turning off
  needs nothing.

Any member, for themselves only, inside an organisation.

## Tests

- `tests/unit/call_ai/test_auto_consent.py`: the words and their version.
- `tests/database/test_auto_analysis_consent_postgresql.py`:
  - on and off for oneself, newest wins;
  - an AI level of Off holds the call;
  - new words ask again;
  - an upload is taken only with a current consent for these terms, and names the consent;
  - a plan is accepted without a tap only on one's own call with a current consent, and its
    start names the consent;
  - turning off stops new automatic starts.
