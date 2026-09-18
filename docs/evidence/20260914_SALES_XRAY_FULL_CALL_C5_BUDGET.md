# Complete-call C5 input budget

The production call finished C2 and all four C4 chunks, then report preparation raised `report_prompt_budget_exceeded`. The selected provider was correctly passed as Gemini. The failure came from the Gemini 3.8 Flash coaching adapter's conservative 32,000-unit ceiling, not a missing transcript or provider fallback.

## Bounded change

Only the Gemini 3.8 Flash C5 ceiling changes to **48,000 units**, calculated as UTF-8 input bytes + approved maximum output tokens + 128 units of overhead. This retains the existing conservative one-input-byte-per-token basis. Groq, C4 and the other Gemini model retain their limits. Preparation, reconstructed requests and broker validation enforce the same ceiling; one extra byte is rejected.

The request contents, exact frozen profile, every C4 observation/quote, all covered segment IDs, response schema, output cap and source/attribution validators are unchanged. No compact evidence schema or clipping is introduced. C2/C4 checkpoints remain reusable.

## Actual retained-call reproduction

Read-only private source: `D:/AC-authority-closers-release-audit/dipak-fa5f956c-c5-input-evidence-20260914.json`, SHA-256 `6476866c8ddcaf2fc8dc7027b531ae6900a750c144fc7cdff3988ab00870d488`.

- All five checkpoint payload/manifest bindings passed the runtime verifier.
- The current C2 has **152 segments**, and all four C4 packets preserve **38 observations**. This is the current production C2, not an earlier 147-segment transcription of the same source.
- Exact new-source system input: **14,056 bytes**; user input: **30,215 bytes**. With the accepted **3,200 output tokens** and overhead, the request uses **47,599 units**.
- The old 32,000 limit rejects this actual input; the new limit prepares and reconstructs it successfully. Canonical provider payload: **46,419 bytes**, SHA-256 `287599a859d50031f11b93540fe571475bdfb03d66f11d808bfb00c94fb04d99`.
- Frozen profile SHA-256 stays `4c16b69e97b5c4e259e2b577cc41fb6fde28c35fb934b3a9dd6595cf04f314f7`.
- Only 2,642 input bytes repeat exact evidence. Deduplication alone cannot fit the prior ceiling; deleting observations or shortening quotes would discard context.

## Existing approval and cost basis

The actual accepted C5 stage already allows **500 paise**, **3,200 output tokens** and **134,217,728 input bytes**, using `ref:pricing/gemini-38-intro-20260914`. No approval is expanded by this patch.

Using that frozen planning basis (USD0.75 per million input tokens, USD3.75 per million output tokens, INR100/USD), the entire 48,000-unit ceiling costs at most **456 paise** with 3,200 output tokens. Even the largest legal 4,000-token output configuration stays within **480 paise**. These are conservative planning calculations, not a statement of settled provider cost or invoice charges.

## Executed checks and receipts

- **92 focused tests passed** in 2.28 seconds: complete mixed-script input, Gemini envelope, report structure and broker suites.
- New tests cover a synthetic 152-segment/38-observation call exceeding the old limit, unchanged full coverage/profile/quotes at 1,800/3,200/4,000 output caps, exact 48,000-unit acceptance and one-byte-over rejection, broker reconstruction and rejection, and every legal output cap's cost on the frozen pricing basis.
- Ruff lint/format and diff whitespace pass.
- Actual private reproduction passed with zero provider calls, no database writes, unchanged private artifact hash and unchanged in-memory source/fact/profile objects.

External receipts: `peer-c5-full-budget-focused-final-20260914.log` and matching JUnit XML; `peer-c5-full-budget-measure-20260914.json`; `peer-c5-full-budget-proof-20260914.json`, all under `D:/AC-authority-closers-release-audit/`.

This proves preparation and validation. Report generation, actual output quality, live settlement, combined CI, staging and production checks remain with the release coordinator. The separate scheduler recovery fix handles preparation failures without restarting the worker.
