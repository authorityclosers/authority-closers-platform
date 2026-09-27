# OpenAI Responses C5 adapter checkpoint — 2026-09-24

This is an offline adapter implementation checkpoint. It does not change the
active provider configuration, call a model, or deploy anything. The source
control tree, task configuration, report validators, reservations, audit
receipts, and worker execution gates remain authoritative.

## Inventory and selection boundary

OpenAI publishes a broad catalog of general text/reasoning models, image-input
and image-generation models, audio transcription and speech models, real-time
audio models, embeddings, moderation, and specialized coding, search, and
research models. The account's read-only `GET /v1/models` receipt captured
132 model IDs with HTTP 200 and zero generation requests. It includes
`gpt-6-luna`, `gpt-6-sol`, and `gpt-6-astra`; that listing does not prove that a
generation request will be admitted by this account.

Only the three reviewed GPT-6 text models are entered in the Sales Xray C5
provider registry. Their official model pages describe text input/output,
image input, structured outputs, and the Responses endpoint; each says audio
and video are not supported by that model. The adapter uses text only. It does
not route audio/transcription, facts/C4, images, tools, search, or realtime
tasks through OpenAI. ElevenLabs remains the transcription source.

The catalog marks these C5 routes `request_only_account_access_unverified`.
That status is descriptive, not permission to run them. The provider-options
control reads model readiness from the shared registry. A saved catalog entry
or `/v1/models` entry alone is not an approved/active route. Root-owned API-key
settings, account usage checks, consent, retention, provenance, provider and
professional gates are still required before an external call.

## Request and response contract

The leaf adapter accepts only detailed C5 coaching prompts with supported
`coaching-v4` or `coaching-v5` schema revisions. It emits a stateless Responses
request with an explicit model, reasoning effort, output-token cap,
`background=false`, `stream=false`, `service_tier=default`, `store=false`,
disabled truncation, no tools, and strict JSON-schema output. Prompt caching
uses the documented implicit default; no extra cache-mode or TTL control is
sent. The max-output cap includes reasoning tokens as well as visible output.

Strict JSON-schema conversion marks all object fields required and all
objects closed, preserving nullable fields. The existing source-evidence and
coaching report validators remain the final authority. Refusals, incomplete
responses, tool calls, multiple messages, duplicate JSON keys, non-finite JSON,
and malformed JSON are rejected. Requests use the fixed Responses URL through
the existing bounded transport with no redirects or automatic retries.

Input admission is a 255,000-byte UTF-8 bound over instructions, source payload,
and generated schema, with a 17,000-byte margin to the documented 272,000 input
token pricing threshold. This is a byte limit, not a token count. No token
counting endpoint or live generation probe was used. The benchmark planning
ceiling therefore prices each request using a conservative 272,000-token
allowance and long-context rates; actual usage must come from the provider
receipt.

When response usage is absent or any usage counter is missing, malformed, or
incoherent, the adapter records usage as wholly unknown rather than filling in
zeroes or retaining a partial breakdown. The exact raw provider response is
still captured before report validation. A valid report may proceed with an
unknown usage breakdown; its receipt remains in cost reconciliation and the
reservation is not automatically settled or retried. The Responses usage
counter mapping keeps cached and cache-write input separate, keeps reasoning
inside output, and checks total/cache/reasoning bounds before estimating cost.

## Official evidence

- [OpenAI model catalog](https://developers.openai.com/api/docs/models)
- [GPT-6 Luna](https://developers.openai.com/api/docs/models/gpt-6-luna)
- [GPT-6 Sol](https://developers.openai.com/api/docs/models/gpt-6-sol)
- [GPT-6 Astra](https://developers.openai.com/api/docs/models/gpt-6-astra)
- [Responses create reference](https://developers.openai.com/api/reference/cli/resources/responses/methods/create)
- [Responses usage schema](https://developers.openai.com/api/reference/cli/__sdk_schema?declaration=%28resource%29+responses+%3E+%28model%29+response+%3E+%28schema%29+%3E+%28property%29+usage&selected=%28resource%29+responses+%3E+%28method%29+create)
- [OpenAI API pricing](https://developers.openai.com/api/docs/pricing)
- [Gemini Developer API pricing](https://ai.google.dev/gemini-api/docs/pricing)

## Verification

Focused offline tests cover the Responses request/response contract, strict
nullable schema shape, model-specific reasoning effort, request digest changes,
provider usage retention, cache/reasoning usage accounting, pricing tiers,
provider registry readiness, source validation, and worker receipt keys. No
paid OpenAI generation request, browser UI edit, deployment, or production
configuration change was made.
