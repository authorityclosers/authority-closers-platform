# Native Gemini facts and coaching adapter

The existing durable C4 facts and C5 coaching stages now accept an approved
Gemini route as well as Groq. Gemini 3.8 Flash and 3.1 Pro Preview use native
`generateContent` JSON requests. Catalog implementation status describes code
availability, not provider quality, funding, consent or a deployed capability.
The older 2.5 task entries remain contract-only. There is no automatic fallback.

`StageRequest.provider` defaults to Groq and is omitted when serializing that
default, preserving existing Groq intent bytes. Gemini requests persist the
explicit provider. Both HTTP stage selection and the durable plan derive it
from the exact current server approval; learners cannot select or configure it.

## Request and result boundary

The native request keeps the existing versioned source/profile instructions,
using `systemInstruction` and one text-only `contents` item. A model/version
marker binds the selected model into the canonical request hash. Reconstruction
validates exact fields, source/revision/chunk/profile metadata, one candidate,
JSON mode, LOW thinking, and a finite 256–4,000 token output cap. It allows no
tools, cache reference, extra modality or safety override. The existing C4/C5
allocation and estimated input-plus-output limit remain in force.

The task uses JSON mode and AC's strict local schemas; it does not claim that
the provider enforces the entire detailed report JSON Schema. Only one candidate
ending in STOP with a model-role content object may be normalized. Blocked,
truncated, empty, thought-only, tool, multiple-candidate, duplicate-key and
non-finite JSON responses are rejected. Non-thought text parts form the final
object. No retry increases the allocation after truncation.

The same FactPacket and ReportDraft validators check literal quotes, native
timestamps, covered source segments, profile citations and the required
`dipak-14-point-v1` overview. Source hash/revision remain server-derived. Numeric
publication remains held. Structural validity does not establish the truth of
an interpretation or replace Dipak/Suyash adjudication.

Untouched provider JSON and its exact SHA-256 remain separate from normalized
data. Thinking and cached-input token counters are retained with the other
native usage counters. Thought text is not presented as analysis. A changed
judge/profile creates a new C5 request and reuses C2/C4; old reports stay readable.

## Authorization and cost

The fixed broker router now admits Gemini only for facts/coaching and checks its
native output cap before dispatch. It still binds source, provider, model,
recipe, exact credential reference, privacy/terms/retention/professional/pricing
references, expiry, current bundle and the permission's quote fingerprint.

The previous router-level zero-only check is reconciled with the already added
bounded-paid contract: price must exactly match the stage approval; any positive
price requires paid pricing evidence, the current paid approval reference and
an adequate bundle cap. Database reservations remain mandatory. This code is
not a new spending approval. No credentials or real call content are in this
packet, and no provider execution was performed for its tests.

The complete plan quotes one C2 maximum plus every permitted C4 request maximum
plus one C5 maximum. Its immutable manifest validates that sum exactly and
rejects a total above the current project cap or available budget when quoted.
The app displays the upper bound in rupees/paise and requires explicit consent;
a positive total paired with a zero-cost label is invalid. The plan quote does
not reserve all stages in advance: each effect still reserves against the shared
ledger before dispatch, and may be held if another plan has consumed the
available budget. Saved provider receipts keep actual cost unknown and the
reservation held until reconciliation; a successful report is not a ₹0 invoice.

## Provider reference

Google documents the native request fields, JSON response MIME type, candidate
finish reasons, and thinking-token usage in its [generateContent API reference](https://ai.google.dev/api/generate-content).
The [thinking guide](https://ai.google.dev/gemini-api/docs/thinking) describes
LOW reasoning and the combined thinking/output limit. Actual model quality and
full report completion within each authorized allowance require separate testing.
