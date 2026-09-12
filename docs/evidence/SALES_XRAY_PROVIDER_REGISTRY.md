# Sales Xray provider registry evidence

Date: 2026-09-13. This is a pure contract and catalog slice. It does not read
secrets or settings, call a provider, open a network connection, change a database,
add an HTTP route, authorize an actor, or make a frontend promise.

## Boundary implemented

`packages/python/ac_platform/conversation_intelligence/provider_registry.py` supplies:

- immutable, versioned `ProviderCatalog` and safe `catalog_public_view()` metadata;
- explicit deployment classification (`hosted`, `gateway`, `local`, or
  `deterministic_tool`) without inferring licensing, quotas, or model ownership;
- task-neutral provider/model/protocol records and task contracts for `asr`, `facts`,
  `embeddings`, `retrieval`, `rerank`, `coaching`, and `presentation`;
- strict `parse_registry_config()` JSON ingress, immutable `RegistryConfig`, and a
  canonical `.digest` for append-only admin persistence;
- `(provider_id, model_id)` keyed routes, explicit profile/prompt/recipe revisions,
  and required checkpoint reuse stages;
- pure `validate_registry_config()` and `resolve_dispatch()` checks; a
  `DispatchPlan` is only a validated plan and does not imply HTTP transport exists;
- `ProviderTransport` and `TaskAdapter` protocols with typed, digest-bound byte
  request/response envelopes. No concrete network adapter is claimed here.

The configuration boundary accepts opaque `ref:` identifiers only. Credential values,
URLs in reference fields, query strings, URL credentials, common API-key formats,
JWT/basic/bearer values, oversized collections, and mutable payloads are rejected.
External endpoints must match the catalog byte-for-byte and by SHA-256, with an
operator approval reference. Local HTTP endpoints are limited to loopback and require
a separate local-endpoint approval reference. A zero-paid policy is the default;
missing terms, privacy, pricing, free-allowance, permission, endpoint approval, or
credential evidence blocks dispatch. Automatic purchase is forbidden and paid fallback
is never inferred.

## Catalog status

The catalog distinguishes transport availability from task-adapter readiness:

| Entry | Deployment | Catalog status | Claimed task status |
| --- | --- | --- | --- |
| Local AC AudioAtlas / `audioatlas` | `deterministic_tool` | `implemented` transport, outside this external task catalog | C1 measurement remains owned by the local AudioAtlas path |
| Gemini / `gemini-2.5-flash`, `gemini-2.5-pro`, `gemini-3.8-flash`, `gemini-3.1-pro-preview` | `hosted` | `implemented` bounded transport | `facts` and `coaching` are `contract_only`; no task adapter is claimed |
| Groq / `openai/gpt-oss-120b`, `llama-3.3-70b-versatile` | `hosted` | `implemented` bounded transport | `facts` and `coaching` are `contract_only`; no task adapter is claimed |
| ElevenLabs / `scribe_v2` | `hosted` | `implemented` bounded transport | `asr` is `implemented`; native speaker labels remain unverified |
| OpenAI, DeepSeek, Anthropic, OpenAI-compatible gateway, Ollama, vLLM, llama.cpp, Sarvam | `hosted`, `gateway`, or `local` by provider | `planned_no_transport` | No model IDs, quotas, prices, privacy terms, or task adapters are asserted |

Planned provider configurations may be retained as dormant admin metadata so a future
approved model option does not look implemented. `resolve_dispatch()` rejects planned
providers before model lookup. Unknown models cannot dispatch. Learner-facing provider
selection is not part of this module; the future application control plane must keep
registry creation and revision changes admin-only.

## Verification

The focused synthetic suite completed with **25 passed**. It covers catalog status and
readiness, all task contracts, C2 reuse, strict round trips and digests, multi-model
routes, dormant planned registrations, zero-cost exact permission/endpoint checks,
missing evidence, paid-policy and auto-purchase rejection, endpoint and credential
hardening, secret formats inside reference prefixes, collection bounds, and typed
immutable request/response envelopes.

No provider, browser, database, VPS, or secret operation was performed. Receipts for
the final checks are stored outside Git under
`D:/Projects/authority-closers-release-transfer/2026-09-13-sales-xray/receipts/`.
