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
| C2 transcription | Scribe ₹5.08 | Gemini 3.1 Flash-Lite ≈ ₹1.85 |
| C4 facts | ₹1.15 | ₹1.15 |
| C5 report and coaching | ₹2.46 | ₹2.46 |
| pointer review | ₹2.13 | ₹2.13 |
| per call (per minute) | ₹10.8 (≈ ₹0.78) | ≈ ₹7.6 (≈ ₹0.55) |

So in production the one-pass saving is the transcription route. The one-read analysis
(`one_pass` mode: deep call data and pointer review in one request) replaces the call
data engine's deep read, which production does not run; it is offered on development
and staging only.

## Slice 1 (this change, rides v0.71): no re-seal

- The C2 / C4 / C5 routes, their configuration digests and the hosted approval bundle
  are unchanged; **every classic route stays and nothing needs sealing**.
- New on every environment: `ac-one-pass@<env>` (host wrapper and unit, inside the
  worker on staging and production, like `ac-call-data@`). With the pipeline on
  `classic` (the default) it idles.
- Root step for staging (optional, where `one_pass` is offered): install
  `infra/application/scripts/ac-one-pass` to `/usr/local/sbin/ac-one-pass` (0755) and
  `infra/application/systemd/ac-one-pass@.service`, then
  `systemctl enable --now ac-one-pass@staging`.

## Slice 2 (next): Gemini 3.1 Flash-Lite as the sealed C2 route

The production switch is a provider configuration whose C2 route is
`gemini / gemini-3.1-flash-lite`, approved in the hosted approval bundle beside today's
Scribe configuration (one source/stage may have several approved routes; the
configuration digest picks one). The owner's action activates it in Admin (typed confirm,
reason, audit); activating the previous revision is the one-click fallback. Its exact
configuration document, digest and the bundle's stage approvals will be checked in here
with their sha256 when slice 2 lands.

## A good first production analysis (after the C2 switch)

Read-only checks, on the first real call after the switch:

1. **Contracts pass.** The call's processing plan reaches `completed`; the C2 task's
   provider receipt says `gemini` / `gemini-3.1-flash-lite`; the C4 and C5 tasks complete
   and a report draft exists for the C5 run (no `held` plan, no C5 repair).
2. **The report renders.** The person's Report shows summary, coaching and the 27
   pointers (pointer review saved); the transcript view shows speakers and times.
3. **Cost per minute.** Admin → AI spend → by feature: `call_transcription` for that
   call ≈ ₹0.13 a minute (vs ≈ ₹0.37 on Scribe); all stages together ≤ ₹0.60 a minute.
4. **Time.** Transcription under 2 minutes for a 15-minute call (standard tier).

Fallback at any doubt: activate the previous (Scribe) revision in Admin → Providers.
