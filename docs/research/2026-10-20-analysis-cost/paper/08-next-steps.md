# 8. From fictional evidence to a production switch (proposals for the owner)

Fictional calls rank options; they cannot prove quality on real Indian phone calls. Each step below is gated and
small, and none changes a production pipeline until the owner has read the paper (phase 6).

1. **Real-call check inside existing providers (owner approval needed).** Re-transcribe ~20 already-uploaded
   *staging* staff calls (AC's own team; no customer) with Gemini audio-in, and compare with the stored Scribe
   transcripts and C4/C5 outputs: critical-fact retention, speaker attribution, report agreement. Google is already
   our provider, but it has only ever received transcripts, never audio, so sending audio is a new data flow under
   AC-GOV-AUD-001 → needs "approve data change: staging staff audio to Gemini (paid tier, no training), research".
   Cost ≈ ₹2–5 on the paid key, read-only on the database, audio fetched from staging storage, results deleted
   after the study.
2. **Flex tier (no model change).** One request field (`serviceTier: "flex"` in `generateContent`), plus a
   503/429 retry that falls back to standard after N minutes. Halves every Gemini stage. Ship behind Admin's
   provider switch, measure latency p50/p95 for a week.
3. **Prompt order for caching.** Put the transcript first (shared prefix), stage instructions after it, so Gemini's
   implicit cache can hit across stages on calls whose transcript exceeds the 4,096-token minimum (≈ 10+ min).
4. **Deep pipeline segment labels: drop them.** Distilling them into an embedding + linear head was tried (6.5) and
   reached only 33–61% agreement, near the majority-class baseline; the report does not use them. Stopping the
   per-segment LLM labels removes 27% of today's bill with nothing for users to lose.
5. **Provider gates for the ₹0.10 path.** Groq (Whisper), DeepSeek/GLM/Qwen hosts, AssemblyAI, Sarvam each need the
   AGENTS.md / AC-GOV-AUD-001 review (retention, region, training use, DPA) before any real call; India-hosted
   options (Sarvam's hosted DeepSeek/GLM, AWS Mumbai) ease residency.
6. **HF token on GitHub (owner's call).** With `HF_TOKEN` as a GitHub Actions secret on the public repo (forks and
   pull requests cannot read it), round 2 can use Indic Parler-TTS native Marathi voices and the gated AI4Bharat
   real-speech sets (IndicVoices, Kathbath-noisy, Svarah) for a real-human WER cross-check.
