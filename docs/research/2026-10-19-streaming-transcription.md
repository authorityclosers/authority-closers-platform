# Streaming transcription for Hindi, English and Marathi calls

Research for the call data engine's fast pipeline, 19 Oct 2026. Provider pages
were read on 19 Oct 2026. Prices are list prices converted at ₹95/USD. Nothing
was signed up for or tested, so verify the claims before any real call goes
through a new provider.

## Recommendation

**Primary for streaming: Sarvam Realtime API** (`saaras:v3-realtime`; then try
`saaras:v4`).
- It has the best published phone-call accuracy for both Hindi and Marathi.
- It accepts 8 kHz mulaw audio natively and has a code-mix output mode.
- The price is ₹29.40 per audio hour (pay-as-you-go) or ₹24.60 (Growth plan),
  the same as batch.
- ADR 0056 §14 already names Sarvam behind a Cloudflare Worker for the live
  relay.
- Gaps:
  - **Streaming has no speaker labels.** So stream each side of the call when we
    have both legs, or let the extraction step tell the salesperson from the
    prospect.
  - **Sarvam keeps data indefinitely by default.** Set zero retention on the
    workspace before any real call.

**Fallback: AWS Transcribe streaming in Mumbai.**
- Its published phone accuracy is second or third best (Hindi 4.9 / Marathi 7.8).
- It includes speaker labels at no extra charge and can detect several
  languages in one stream.
- It costs $0.60/h (₹57) flat, billed per second.
- It needs an AWS AI-services opt-out policy first; without it, AWS may keep
  content outside India.

**Batch stays on ElevenLabs Scribe v2** ($0.22/h). It is already integrated, it is
cheap, and it has speaker labels. Before switching, run a 30–50 call comparison
on our own consented calls (Hindi, Marathi, Hinglish, Marathi-English). Measure
word error rate and how well CRM fields come through (names, numbers, amounts,
places) for:
- Scribe v2;
- Sarvam batch with speaker labels (₹35.40/h);
- AWS batch ($0.36/h).

**Bake-off candidate: Soniox.**
- It is the cheapest at $0.12/h, includes speaker labels, detects language per
  word, and offers an India region.
- It has no published Indian-language accuracy results, so it needs our own
  test first.

**Not recommended:**
- **Deepgram:** Marathi error 42.6–43.7, and its mixed-language mode leaves out
  Marathi.
- **Azure:** weak Marathi (28–30), over $1/h with add-ons, and it does not switch
  language within a sentence.
- **Google Chirp 3:** no India region, Marathi only in Preview, no speaker labels
  when streaming.
- **Gladia:** trains on self-serve data unless you opt out.
- **AssemblyAI:** its older model scored 87.6 on Marathi; the new one is untested.

## Comparison

| Provider | Hi / En / Mr / mixing (streaming) | Speakers when streaming | Latency (published) | Streaming ₹/hour | Data |
|---|---|---|---|---|---|
| Sarvam realtime | Yes / Yes / Yes; code-mix on final text | No | <150 ms first token (v4), <250 ms median | 29.40 (24.60 Growth) | Zero retention needs setting; India-only and no-training claims not confirmed on a primary page |
| AWS Transcribe (Mumbai) | Yes / Yes / Yes; multi-language stream | Yes, included | Not published | 57.00 | Mumbai; AI opt-out policy required |
| ElevenLabs Scribe v2 Realtime | Hindi listed; Marathi realtime not confirmed | No | ~150 ms | 37.05 | India residency endpoint; zero retention enterprise only |
| Deepgram Nova-3 | Hi and Mr single-language only; mixing En+Hi only | Add-on $0.12/h | <300 ms | 27–44 (promotional) | No India region |
| Soniox `stt-rt-v5` | Hi, Mr; language per word | Yes, included | Not published | 11.40 | India region; realtime audio not stored; no training |
| AssemblyAI Universal-3.6 Pro | Hi, Mr; mid-sentence switching | Add-on $0.12/h | Not published | 54.15 | Billed on connection time; not checked |
| Google Chirp 3 | Hi GA; Mr Preview | No | Not published | 91.20 | US and EU only |
| Azure real-time | Hi, Mr; no within-sentence switching | Yes | Not published | ~95 + add-ons | India region |
| Gladia Solaria | Hi, Mr listed; live not confirmed | No | <120 ms (press) | €0.68/h | Trains by default on self-serve |

**Indian options checked in brief:**
- **Gnani Vachana:** 8/16 kHz streaming, 10 languages plus Hinglish. No public
  price.
- **AI4Bharat IndicConformer:** MIT licence, offline 16 kHz, no streaming model
  found. Self-hosting means our own GPU and decoder work.

## Published accuracy on Indian phone calls

The source is the Voice of India benchmark (Josh Talks with AI4Bharat): 536
hours of narrowband phone speech. Lower is better. The pages do not say
whether streaming or batch was tested, and two versions disagree.

| System | Aug 2026 report: Hi / Mr | Apr 2026 blog: Hi / Mr |
|---|---|---|
| Sarvam Saaras v3 | 3.8 / 6.5 | — |
| Gemini 3 Pro (not streaming) | 4.7 / 8.8 | 6.0 / 10.7 |
| Amazon Transcribe | 4.9 / 7.8 | 6.8 / 11.3 |
| ElevenLabs Scribe v2 | 5.9 / 10.3 | 7.7 / 12.9 |
| IndicConformer | 6.5 / 11.6 | 8.2 / 13.1 |
| Microsoft (realtime) | 8.0 / 28.4 | — |
| Deepgram Nova-3 | 9.5 / 42.6 | 13.0 / 43.7 |

The August report is a draft hosted on an ElevenLabs-branded subdomain.
Spot-check these figures before quoting them outside the company.

## Cost per 10-minute call

Streaming plus the Scribe v2 batch pass (₹3.48):

| Streaming option | Streaming | Total |
|---|---|---|
| Soniox | ₹1.90 | ₹5.38 |
| Sarvam pay-as-you-go | ₹4.90 | ₹8.38 |
| ElevenLabs Realtime | ₹6.18 | ₹9.66 |
| AWS Mumbai | ₹9.50 | ₹12.98 |

Streaming each leg separately (to get speakers) doubles the streaming cost.

## How it plugs in (v0.64)

- **Live draft text.** A streaming provider produces draft text only, off-box
  (ADR 0056 §14). The VPS receives draft text and never audio from the relay.
  The fast pipeline may read the draft, and its objects record the draft
  transcript revision. The deep pipeline always waits for the canonical batch
  transcript and supersedes.
- **Admin-swappable.** The provider is chosen in Admin like every other
  provider. Keys stay in Infisical.
- **Gate.** No new provider processes real calls until AC-GOV-AUD-001's
  consent, retention and provider gates are cleared for it.

## Sources (read 19 Oct 2026)

- ElevenLabs:
  - https://elevenlabs.io/pricing/api
  - https://elevenlabs.io/docs/capabilities/speech-to-text
  - https://elevenlabs.io/realtime-speech-to-text
- Deepgram:
  - https://deepgram.com/pricing
  - https://developers.deepgram.com/docs/models-languages-overview
  - https://developers.deepgram.com/docs/multilingual-code-switching
- Sarvam:
  - https://www.sarvam.ai/api-pricing
  - https://docs.sarvam.ai/api/api-guides-tutorials/speech-to-text/realtime-streaming.md
  - https://www.sarvam.ai/blogs/introducing-saaras-v4
  - https://docs.sarvam.ai/api/platform/data-retention
- Google:
  - https://cloud.google.com/speech-to-text/pricing
  - https://docs.cloud.google.com/speech-to-text/docs/models/chirp-3
- Azure:
  - https://prices.azure.com/api/retail/prices
  - https://learn.microsoft.com/en-us/azure/ai-services/speech-service/language-support
- AWS:
  - https://aws.amazon.com/transcribe/pricing/
  - https://docs.aws.amazon.com/transcribe/latest/dg/supported-languages.html
  - https://docs.aws.amazon.com/organizations/latest/userguide/orgs_manage_policies_ai-opt-out.html
- Gladia:
  - https://www.gladia.io/pricing
  - https://docs.gladia.io/chapters/language/supported-languages
- Soniox:
  - https://soniox.com/pricing
  - https://soniox.com/docs/stt/concepts/supported-languages
  - https://soniox.com/docs/data-residency
- AssemblyAI:
  - https://www.assemblyai.com/pricing
  - https://www.assemblyai.com/docs/streaming/multilingual-transcription
- Benchmarks:
  - https://voiceofindiablogs.ai.joshtalks.com/
  - https://elevenlabsreport.ai.joshtalks.com/
  - https://arxiv.org/abs/2604.19151
- Others:
  - https://huggingface.co/gnani-ai/vachana
  - https://github.com/AI4Bharat/IndicConformerASR
