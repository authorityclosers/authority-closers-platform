# Gemini credential and generation verification

The owner supplied a replacement testing credential in this release thread.
It was stored in the existing Infisical project
`b421c44e-4599-4394-8df6-758ed8aedfed`, environment `dev`, folder
`/sales-xray-test`, key name `GEMINI_API_KEY`. Exact private readback matched.
The value was never printed, committed, or passed as a process argument. The
temporary transfer file had inheritance removed and was deleted after storage.

The first existing-model test returned 404 for Gemini 2.5 Flash. Gemini 3.8
returned HTTP 200 with the supplied key, but the former 16-token smoke limit
produced no final text. The fixed synthetic smoke uses a fixed 256-token total
cap and LOW thinking for 3.8. It records the finish reason and ignores thought
parts when checking the final reply. There are no automatic retries.

The corrected call returned HTTP 200, the exact expected `READY` final answer,
and finish reason `STOP`: 10 input tokens, 1 output token, 11 total tokens.
No customer recording was sent, no credit purchase was made, and no provider
invoice or funded tier was asserted. The existing reservation journal retains
the uncertain billing settlement until reconciliation.

Private receipts outside Git:

- `D:/AC-authority-closers-release-audit/gemini-key-update-20260914.json`
- `D:/AC-authority-closers-release-audit/gemini-supplied-key-smoke-20260914-2125/inference-smoke.jsonl`
- `D:/AC-authority-closers-release-audit/gemini-supplied-key-smoke-20260914-2128/inference-smoke.jsonl`
- `D:/AC-authority-closers-release-audit/gemini-smoke-unit-20260914.xml`

Three regression cases pass: final answer, HTTP success with truncated empty
output, and thought-only output. They also verify reservation-before-dispatch
ordering, source hash binding and the fixed request/output caps. Ruff passes.
The default Windows pytest temporary path was rejected by the private-storage
repository-boundary check; rerunning in the existing external audit directory
passed. This does not change production storage enforcement.

References checked on 2026-09-14:
[Gemini thinking](https://ai.google.dev/gemini-api/docs/thinking) and
[provider pricing](https://ai.google.dev/gemini-api/docs/pricing).

This proves the stored testing key and bounded Gemini generation work. It does
not prove hosted app activation, real-call processing, report quality, or the
staging/production guest journey. Those remain part of the release task.
