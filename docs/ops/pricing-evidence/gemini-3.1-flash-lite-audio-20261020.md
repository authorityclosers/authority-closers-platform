# Pricing evidence: Gemini 3.1 Flash-Lite as C2 transcription (audio in, text out)

Superseded by `gemini-3.1-flash-lite-audio-20261021.md`: real calls write two to three
times the output estimated here.

- Source: https://ai.google.dev/gemini-api/docs/pricing, paid tier, read 20 Oct 2026 by
  the analysis-cost research (`docs/research/2026-10-20-analysis-cost/`).
- Model: `gemini-3.1-flash-lite`, standard tier.
- Audio input: USD 0.50 per million tokens. Gemini counts audio at 32 tokens a second,
  so 1,920 tokens a minute: USD 0.00096 a minute.
- Output (including thinking): USD 1.50 per million tokens. A transcript writes about
  450 tokens a minute of dense speech (27,000 for an hour, measured on the fictional
  set): about USD 0.00068 a minute.
- Planning rate for quotes and Admin estimates: **USD 0.0020 per audio minute**, the sum
  above rounded up with room for the prompt and the JSON envelope.
- Ceiling per request: the route answers at most 60,000 output tokens (USD 0.09) and
  takes at most two hours of audio (230,400 tokens, USD 0.1152), so one request costs at
  most USD 0.2052, ₹20.52 at the price sheet's ₹100 a dollar; the route's
  `max_cost_paise` is 2,400.
- Flex (half of every rate) is not used for production until a latency check.
