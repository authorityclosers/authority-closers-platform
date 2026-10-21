# Pricing evidence: Gemini Flex routes

- Source: https://ai.google.dev/gemini-api/docs/flex and
  https://ai.google.dev/gemini-api/docs/pricing, read 20–21 Oct 2026 by the
  analysis-cost research: Flex is half of every standard rate for the same model, best
  effort, and may queue for minutes. A request asks for it with `service_tier: flex`.
- `gemini-3.1-flash-lite:flex` (C2 transcription): half of the measured standard
  planning rate (`gemini-3.1-flash-lite-audio-20261021.md`), **USD 0.0015 per audio
  minute**.
- `gemini-3.8-flash:flex` (C4 facts, C5 report): **USD 0.375 input, USD 1.875 output**
  per million tokens (thinking included).
- Measured on development, 21 Oct 2026, 16 real calls on Flex: no request fell back;
  transcription 54 s median (92 s longest), the two analysis requests 33–131 s.
- A Flex route waits at most five minutes, then sends the same request once on standard,
  billed at standard. So a Flex route's approval keeps the standard per-request ceiling,
  and receipts record `serviceTierFlex` and `flexFellBack`.
