# OpenAI GPT-6 Luna on the Flex tier: list price evidence (21 Oct 2026)

- **Route:** `openai / gpt-6-luna:flex`, the same model and Responses request as
  `gpt-6-luna`, sent with `service_tier: "flex"`. The transport waits at most 600 s,
  then sends once more on the default tier, billed at the default rate.
- **Rates (USD per million tokens), half of each `gpt-6-luna` rate**
  (`ref:pricing/openai-gpt-6-luna-20260924`):

  | | Up to 272k input tokens | Above 272k |
  |---|---|---|
  | Input | 0.05 | 0.10 |
  | Cached input | 0.005 | 0.01 |
  | Cache write | 0.0625 | 0.125 |
  | Output (reasoning included) | 0.25 | 0.375 |

- **Source:** OpenAI's API pricing page (https://developers.openai.com/api/docs/pricing),
  where the Flex tier is half price, best effort, and may queue. The cost research
  measured it on the 16 fictional benchmark calls (21 Oct 2026, luna-route-spec):
  32 Flex requests, every response echoing `"service_tier": "flex"`, none falling back.
  Per-call latency was 261 s median and 352 s max, with both requests in parallel.
- **Use:** planning estimates and approval ceilings only, never a charge. A fallback is
  priced at the default rate.
