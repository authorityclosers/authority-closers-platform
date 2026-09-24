# PR1-A provider failure observation evidence

This change is based on integrated source commit `7ff3581fc39f616d189c525c2d6b3e23a51e472a` and adds an optional, versioned failure observation at the existing provider adapter and inference-broker boundary.

The `ac.sales_xray.provider_failure_observation/1` shape binds the provider HTTP status to the current reservation, attempt, quote, provider, model, operation, and input digest. It records whether the bounded error body was fully observed, how many bytes were observed (up to 16 KiB), and a body digest only when complete. Request IDs are represented only by a SHA-256 digest; missing, repeated, non-ASCII, or overlong request-ID headers are omitted. `Retry-After` and diagnostic categories are bounded and descriptive only.

An incomplete or unread body preserves the observed HTTP status but carries no body digest. A typed observation with an impossible HTTP 200 status, malformed fields, extra fields, duplicate frame keys, or mismatched attempt/input binding is rejected. Legacy error frames without observations remain compatible and carry no additional certainty. Success frames retain their existing shape.

This tranche does not retry requests, infer billing or no-charge outcomes, create settlement receipts, alter customer usage, or change worker/task/ledger semantics. HTTP status and `Retry-After` remain diagnostics; a separate lineage implementation must establish any retry and financial treatment.

Offline verification used synthetic `httpx.MockTransport` responses only; no provider calls or production state were involved. Focused contract, provider, and broker tests cover complete/truncated bodies, secret-shaped request IDs, duplicate keys, malformed/mismatched frames, legacy compatibility, and status/body bounds. The checked-in test command and final results are recorded in the task handoff.
