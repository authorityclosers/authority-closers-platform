# Provider usage receipt on strict validation failure

Date: 2026-09-15  
Source baseline: `b4ebfcf558951d33f68e2aa39f1f7ae10e5ba4c4`

The inference worker now records a bounded provider-returned receipt in its own
transaction after private raw-response storage and before strict response
validation. This preserves provider/model, allowlisted usage counters, request
and response digests, and the raw-response binding when a provider response
cannot produce a canonical checkpoint, including Gemini `MAX_TOKENS`.

The receipt is explicitly marked `validation_state=provider_returned`, keeps
`cost_state=reconciliation_required`, and leaves `actual_cost_paise` unset.
The worker still rejects the response, publishes no checkpoint or report, marks
the dispatch and reservation uncertain, and dead-letters the job with its
content-free failure code. A validated response upgrades the provisional
receipt to the existing final receipt under the same idempotency key. A replay
of either state cannot dispatch the provider a second time or create another
ledger transition.

The existing admin projection exposes the saved provider/model/usage as a
recorded receipt while retaining the task uncertainty, usage estimate, and
unsettled-cost semantics. It does not turn provider usage into an invoice or
an automatic refund.

Validation evidence:

- `ruff check` passed for all changed Python files.
- `mypy` passed for the changed source modules.
- Unit receipt/admin and outbox suites: 56 passed.
- Disposable PostgreSQL inference suite: 11 passed.
- Disposable PostgreSQL Gemini plan success path: 2 passed.
- Disposable PostgreSQL Gemini `MAX_TOKENS` regression: 1 passed. It verifies
  the saved provider/model/usage receipt, no C5 checkpoint, uncertain
  reservation, `conversation_gemini_response_incomplete`, and zero additional
  broker calls on replay.

Tests use only synthetic local brokers and the disposable loopback database;
they make no provider requests and contain no response body, transcript, or
credential material.
