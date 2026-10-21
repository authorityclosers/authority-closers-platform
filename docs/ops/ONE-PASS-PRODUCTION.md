# One pass in production: what it is, how the owner switches it, how to check it

Owner, 21 Oct 2026: "So at least get this on prod now!!!" (one pass on the standard
tier, about ₹0.50 a minute; the ₹100 real-call trial on dev keeps running as the safety
check). Design: `docs/architecture/ONE_PASS_ANALYSIS.md`.

## What production runs today, and where the saving is

Production runs C2 (ElevenLabs Scribe), C4 facts and C5 report on Gemini 3.8 Flash (C5
already with its strict schema, direct to the Gemini API) and the AI pointer review. It
runs no call data engine (`ac-call-data@` exists for development-live and staging only).

For a 14-minute call at list price (₹100 a dollar; cost research, 20 Oct 2026):

| stage | today | Google-only |
|---|---|---|
| C2 transcription | Scribe ₹5.08 | Gemini 3.1 Flash-Lite ≈ ₹3.2 |
| C4 facts | ₹1.15 | ₹1.15 |
| C5 report and coaching | ₹2.46 | ₹2.46 |
| pointer review | ₹2.13 | ₹2.13 |
| per call (per minute) | ₹10.8 (≈ ₹0.78) | ≈ ₹8.9 (≈ ₹0.64) |

Flash-Lite transcription measured ₹0.233 a minute on 16 real calls (standard tier; it
writes 500–1,330 output tokens a minute), against Scribe's ₹0.367.

So in production the one-pass saving is the transcription route. The one-read analysis
(`one_pass` mode: deep call data and pointer review in one request) replaces the call
data engine's deep read, which production does not run; it is offered on development
and staging only.

## Slice 1 (8fced2da, rides v0.71): no re-seal

- The C2 / C4 / C5 routes, their configuration digests and the hosted approval bundle
  are unchanged; **every classic route stays and nothing needs sealing**.
- New on every environment: `ac-one-pass@<env>` (host wrapper and unit, inside the
  worker on staging and production, like `ac-call-data@`). With the pipeline on
  `classic` (the default) it idles.
- Root step for staging (optional, where `one_pass` is offered): install
  `infra/application/scripts/ac-one-pass` to `/usr/local/sbin/ac-one-pass` (0755) and
  `infra/application/systemd/ac-one-pass@.service`, then
  `systemctl enable --now ac-one-pass@staging`.

## Slice 2: Gemini 3.1 Flash-Lite as the sealed C2 route

**Code.** C2 operation `transcribe_gemini_audio` (`conversation_intelligence/gemini_audio.py`):
the broker child turns the admitted source into mono 16 kHz 32 kbps MP3 (ffmpeg, as C1
already does in the worker) and sends it with the research's prompt and strict schema to
`gemini-3.1-flash-lite` on the standard tier. A call up to 15 minutes is one request; a
longer one goes as 10-minute parts heard 30 seconds into each other, all sent at once
(the broker allows 180 seconds for the whole provider call, and one request answers at
most 60,000 tokens, about 45 minutes of dense speech). The parts are joined on the
call's clock, each overlap cut at its middle, voices matched across parts from the turns
both heard. The result is today's C2 contract (timebase `gemini-audio-mmss-v1`, provider
speaker labels, unverified identity). Recipe `gemini-3.1-flash-lite-audio-v1`; pricing
snapshot `ref:pricing/gemini-31-flash-lite-audio-20261021` (USD 0.0030 a minute, evidence
`docs/ops/pricing-evidence/gemini-3.1-flash-lite-audio-20261021.md`, measured on real
calls); at most two hours of audio and ₹40 a request. C4, C5 and the pointer review are
unchanged.

**Seal with v0.72 or later**, not v0.71: v0.71's route sends one request whatever the
length (calls over about 45 minutes would fail) and seals a ₹24 ceiling and the older
pricing reference.

**What gets sealed.** One more finite route set per acquisition policy, beside the classic
one (`one_pass/c2_route.py`, the exact rule; `scripts/ops/one_pass_c2_seal.py`, the tool):

- profile `gemini-flash-lite-c2` for the configuration Admin prepares (today's active
  configuration with only the asr route on `gemini / gemini-3.1-flash-lite`);
- its C2 template: the classic C2 template with provider, model, recipe, the Flash-Lite
  pricing reference and evidence digest, Gemini's own credential, terms, privacy and
  permission references (as the C4/C5 Gemini stages), `paid_pricing_evidence`, 4,000
  paise, at most 7,200,000 ms, 0 completion tokens;
- its C4 and C5 templates: the classic ones with the new configuration digest;
- **every classic stage, profile, allowance and exact-source approval is kept
  byte-identical**; the tool refuses otherwise, and refuses any configuration other than
  the one it derives itself.

**Steps.**

1. *Admin (control account):* Admin → Sales Xray → One pass → Transcription (C2) →
   **Prepare Gemini 3.1 Flash-Lite transcription**. It saves the derived configuration as a
   provider revision and shows its digest (audited `analysis_pipeline.gemini_transcription_prepared`).
   Nothing changes for calls.
2. *Root (P0 card):* export, read-only, the active and the prepared configurations (the
   `configuration` column of `conversation_provider_configurations` for the two revisions
   the page shows) and run:

   ```
   python scripts/ops/one_pass_c2_seal.py --bundle <current hosted-approval.json> \
       --classic classic.json --configuration gemini.json --out /root/one-pass-c2-seal
   ```

   Check the summary (`classic_stages_unchanged: true`, one profile per policy), then
   install `hosted-approval.json` and its `hosted-approval.sha256` in the release metadata
   as for any re-seal, and restart the API and workers.
3. *Owner:* the page then offers **Switch transcription to Gemini 3.1 Flash-Lite**: type
   `one_pass`, give the reason in the owner's words, signed in within ten minutes. It is
   the provider activation (`POST /v1/admin/conversation/providers/activate`), audited as
   `conversation.providers.gemini_transcription_on`. New plans quote and run C2 on Gemini;
   plans already running keep their frozen route.
4. *Fallback, one click:* **Back to Scribe** activates the classic revision again.

## Slice 3 (v0.73): Gemini Flex as its own approved routes

The ₹0.28/min the owner saw is mostly Flex: the same models at half price, best effort.
A Flex route is a model id with the `:flex` suffix (`gemini-3.1-flash-lite:flex` for C2,
`gemini-3.8-flash:flex` for C4 and C5; `conversation_intelligence/gemini_tiers.py`): same
model, same prompt, same answer contract, the request only adds `service_tier: flex`.

- **Fallback.** A Flex request waits at most five minutes; a busy (429/5xx), lost or
  too-slow answer goes once more on standard, billed at standard. Receipts record
  `serviceTierFlex` and `flexFellBack`. The broker's limit for one provider call is now
  540 s (was 180 s; other routes still end at 180 s in the transport) and the worker's
  600 s.
- **Approval.** A second profile, `gemini-flash-lite-c2-flex`, for the Flex configuration
  (C2, C4 and C5 on Flex) beside `gemini-flash-lite-c2` and every classic route:
  `python scripts/ops/one_pass_c2_seal.py --flex ...` (same inputs, the Flex configuration
  from Admin → Prepare → Flex). Each Flex route keeps its standard per-request ceiling
  (a fallback is billed at standard). Pricing evidence
  `docs/ops/pricing-evidence/gemini-flex-20261021.md` (half of every rate).
- **Switch.** Admin → One pass → Transcription: "Gemini Flex" → Prepare → (Root seals) →
  Switch, the owner's typed confirm and reason (audited, `flex: true`). From Flex back to
  standard, or back to Scribe, is one click.
- **Pointer review.** The background review follows the same switch: when the active
  configuration runs on Flex, it asks for Flex (same five-minute window and fallback).
- **Cost** (14-minute call, list price, today's production stages): ≈ ₹0.64/min standard
  → ≈ ₹0.33/min on Flex. Measured on 16 real calls on development: no Flex request fell
  back; transcription 54 s median, analysis requests 33–131 s.

## A good first production analysis (after the C2 switch)

Read-only checks, on the first real call after the switch:

1. **Contracts pass.** The call's processing plan reaches `completed`; the C2 task's
   provider receipt says `gemini` / `gemini-3.1-flash-lite`; the C4 and C5 tasks complete
   and a report draft exists for the C5 run (no `held` plan, no C5 repair).
2. **The report renders.** The person's Report shows summary, coaching and the 27
   pointers (pointer review saved); the transcript view shows speakers and times.
3. **Cost per minute.** Admin → AI spend → by feature: `call_transcription` for that
   call ≈ ₹0.15–0.28 a minute (vs ≈ ₹0.37 on Scribe); all stages together ≤ ₹0.70 a
   minute for a call over 10 minutes.
4. **Time.** Transcription under 2 minutes, whatever the length (parts run at once).
5. **The canary.** Each release's canary now records `active_transcription_route` and
   `transcription_route` and fails with `c2_route_mismatch` when the call was not
   transcribed by the active route; after the switch both read
   `gemini/gemini-3.1-flash-lite`.

Fallback at any doubt: activate the previous (Scribe) revision in Admin → Providers.
