# Sales Xray provider adapter evidence — 2026-09-13

This is the earlier adapter/synthetic test snapshot. Later authorized real-call
execution and its failed coaching-quality checks are recorded in
[the current status](SALES_XRAY_CURRENT_STATUS.md). Statements below about pending
report implementation and no real-call dispatch apply to this earlier snapshot.

This receipt covers the bounded conversation intelligence provider boundary. The
adapter tests use fake credentials and `httpx.MockTransport`; they do not send
customer recordings, read provider secrets, purchase credits or publish results.
Provider selection, authorization and settlement remain server-owned concerns.

## Implemented boundary

`conversation_intelligence/providers.py` provides fixed, single-shot transports
for the currently supported Gemini, Groq and ElevenLabs Scribe routes. Every
dispatch requires an in-flight reservation, an unexpired permission, an exact
provider/operation/model quote and a matching input SHA-256. The authorization
callback runs immediately before transport. Request bodies are rebuilt from the
canonical JSON bytes after hashing, so a caller mutation after admission cannot
change the sent payload. Audio is immutable `bytes` and is bounded at 32 MiB.

Transport behavior is bounded and fail-closed: redirects are disabled, proxy
environment discovery is disabled, response JSON is capped at 4 MiB, the HTTP
phase timeouts are finite, and the streamed response has a monotonic 180-second
whole-execution deadline. The adapter performs no retry. Provider error bodies
are classified into short diagnostic categories and never become exception text;
raw response JSON and request content are excluded from `repr` output.

Scribe normalization preserves the provider's literal native text and word order,
validates word timing and speaker-label shape, retains legitimate overlap without
shrinking an interval, and records `overlap_observed`. Provider speaker labels do
not become physical channel assignments: the normalized record marks speaker
identity and AudioAtlas alignment as unverified. The source SHA-256 carried by the
provider result must match the source supplied to normalization.

## Executed here

The final local contract run used Python 3.12 with no PostgreSQL dependency:

```powershell
$env:PYTHONPATH = 'D:/Projects/authority-closers-platform-sales-xray/packages/python'
$env:PYTHONUTF8 = '1'
& 'D:/Projects/authority-closers-platform/.venv/Scripts/python.exe' -m pytest `
  tests/unit/conversation_intelligence/test_providers.py -q `
  --junitxml='D:/Projects/authority-closers-release-transfer/2026-09-13-sales-xray/receipts/provider-contracts-final.xml'
& 'D:/Projects/authority-closers-platform/.venv/Scripts/python.exe' -m ruff check `
  tests/unit/conversation_intelligence/test_providers.py
```

The final run completed with **28 passed, zero failures or skips** (JUnit-reported
time: 0.349 seconds). The suite covers fixed Gemini and Groq endpoints, Scribe multipart request
fields, one-request behavior for redirects and provider failures, finite timeout
settings and the whole-stream deadline, prompt and response size limits,
canonical payload mutation, stale or revoked grants, source binding, immutable
audio, safe result/error representations, usage extraction, native text and word
timing, overlap retention, physical-channel distinction and malformed responses.
The external JUnit receipt records the exact test count and duration.

## Scoped provider smoke context

Earlier owner-authorized smoke receipts are synthetic-only and are reported here
for boundary context. They contain no customer recording bytes and set paid spend
and credit purchases to zero:

| Receipt | Observed result |
| --- | --- |
| `gemini-inference-smoke.json` | Gemini 2.5 Flash: one request, HTTP 404, no generation |
| `gemini38-diagnostic.json` | Gemini 3.8 Flash: one request, HTTP 403, diagnostic `permission_denied`, no generation |
| `groq-inference-smoke.json` | Groq `openai/gpt-oss-120b`: one synthetic request, HTTP 200, generation worked; 82 prompt, 16 completion and 98 total tokens |
| `scribe-inference-smoke.json` | ElevenLabs Scribe v2: one synthetic request, HTTP 200; no customer recording bytes |
| `provider-metadata.json` | Metadata-only account/model probe; credential values are not recorded |

These smoke receipts establish a bounded synthetic observation only. They do not
prove provider quality, language accuracy, production billing, retention terms,
customer-data eligibility, staging readiness or deployment safety. No real call
was sent. The report parser contract remains pending the coordinator's later
`reports.py` implementation and its own tests.

## Remaining gates

Before any real recording or customer-facing inference, the coordinator still
needs current provider terms, purpose-specific disclosure and permission,
retention/deletion propagation, professional and provider approval, verified
usage reconciliation, worker sandbox/network policy and integration tests for
authorization races. The provider adapter does not create access, minutes,
payment authority or official scoring. Staging and production activation were not
performed by this slice.
