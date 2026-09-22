# Sales Xray browser gate readiness follow-up

The frozen candidate `819a3b1016b833908d25cf2a0c58a6e52d54fd74` passed the
explicit dispatch browser gate (`35754764681`, job `106837631056`) and the
local compiled journey. The pull-request validation run `35754743583` had one
browser-job failure (`106837542401`); all other validation components passed.

The failed JUnit receipt (`10707449161`) showed the test reaching the upload
screen, then failing because the `Analyse my call` button was absent after file
selection. The page heading is rendered before the upload policy request has
completed, so the old test could select a still-disabled file input. This was a
harness readiness race, with no product, parser, database, or provider failure.

The browser harness now waits up to 15 seconds for the exact file input to be
enabled before selecting the synthetic WAV. A missing policy or disabled input
still fails the required test; the wait does not mask the condition.

Verification after the bounded wait:

- `uv run --frozen ruff format --check tests/e2e/test_sales_xray_acquisition_browser.py`
- `uv run --frozen ruff check tests/e2e/test_sales_xray_acquisition_browser.py`
- Compiled browser journey: `1 passed in 47.30s` against disposable loopback
  PostgreSQL, Node `v24.19.0`, zero API interceptions, zero provider network
  calls, and no page errors. The sanitized receipt is outside Git at
  `D:\ac-xray-reliable-browser-evidence-20260922-readiness\browser-network.json`
  (SHA256 `fca6645a28a9042d9bcb88cc49a7b24b34b1d6f68cfa03c7ec1e0c9eb0d132f7`).

All evidence uses synthetic inputs and remains outside production data paths.

This follow-up changes only the test harness and evidence. The verified product
artifacts remain pinned to release `819a3b1016b833908d25cf2a0c58a6e52d54fd74`.
