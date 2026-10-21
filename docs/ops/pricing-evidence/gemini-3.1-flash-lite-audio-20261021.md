# Pricing evidence: Gemini 3.1 Flash-Lite as C2 transcription, measured on real calls

Supersedes `gemini-3.1-flash-lite-audio-20261020.md`, whose output estimate came from the
fictional set and was too low.

- Source of the rates: https://ai.google.dev/gemini-api/docs/pricing, paid tier, read
  20 Oct 2026. `gemini-3.1-flash-lite`: audio input USD 0.50, text input USD 0.25, output
  (thinking included) USD 1.50 per million tokens. Flex is half; production uses standard.
- Measured, 21 Oct 2026: 16 real calls on development (3.4 to 36.2 minutes, Hindi,
  Marathi and English), the route's own prompt and schema on mono 32 kbps MP3:
  - input: about 1,500–1,550 tokens per audio minute (audio at 32 tokens a second, plus
    the prompt);
  - output: 500–1,330 tokens per audio minute (Devanagari text and the JSON envelope);
  - standard list price: ₹0.15–0.28 a minute, ₹0.233 a minute over all 280 minutes (the
    analysis-cost research measured ₹0.24 on dense calls).
- Planning rate for quotes and Admin estimates: **USD 0.0030 per audio minute** (₹0.30):
  the densest call measured (1,550 in, 1,331 out a minute, USD 0.00277) rounded up.
- Ceiling per request: two hours of audio at the planning rate is USD 0.36; with each
  10-minute part heard 30 seconds into the next, about USD 0.38. The route's
  `max_cost_paise` is 4,000 (₹40).
- A request answers at most 60,000 output tokens, which at the densest rate measured is
  about 45 minutes of speech: so calls longer than 15 minutes go as 10-minute parts.
