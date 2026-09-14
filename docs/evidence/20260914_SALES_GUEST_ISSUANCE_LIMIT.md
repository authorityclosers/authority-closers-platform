# Sales Xray guest session issuance — 14 September 2026

The exact `POST /v1/conversation/acquisition/session` route now shares the
existing trusted-client-IP rate limiter. Its bucket allows five requests with
a 900-second refill window. Session reads are unaffected. Cloudflare client IP
is accepted only from the configured trusted proxy; forwarded or duplicate
headers cannot select a different bucket.

This is a bounded, single-process issuance shield. It does not establish that
two browsers belong to one person and does not replace the durable 100-minute
visitor/account ledger, upload challenge, or global provider spending caps.

The isolated leaf `7d74c4fa58f9a7f3ea3d06e05a3ff231326017a3` was reviewed and
integrated as `238001fbb760697f1b6dd4e4b17898711d789b68`. The release coordinator
reran all 13 rate-limit HTTP tests successfully, with `PYTHONPATH` explicitly
bound to this checkout. They exercise 429/Retry-After, separate client IPs,
untrusted headers, and unaffected GET requests. The initial invocation used
another checkout's editable package; its failures are not a candidate runtime
result. The corrected source path was printed before the passing run.

The external source-bound JUnit receipt has SHA-256
`262e39feefaaa24924ca30d1bd8aa7678c0ae8fb4415e08b06cbbc8b94ed1844`.
Ruff lint, formatting of all 611 Python package/test files, and mypy over 278
Python sources passed. No provider request or hosted deployment ran in this proof.
