# Sales routing CI correction

Combined candidate `a1a9936cea2ab32241b3803cc0ca3f480ca9c7e6` failed
GitHub run `34773977688` on two Ruff findings in the routing test file.
This correction documents the fixed public loopback marker as a false positive
for S105 and shortens one test name. No routing implementation or assertion changed.

The marker must stay identical to the source script's mock-only gate. An initial
attempt to generate it randomly failed three tests because the gate correctly
rejected the changed value (13 passed, 3 failed). That failed receipt remains at
`D:/AC-authority-closers-release-audit/sales-xray-routing-ci-lint-20260913.xml`.
The final source restores the exact public marker with one documented lint
exception; it is not a provider credential.

Final validation on the pinned project environment:

- `uv run --frozen --offline ruff check packages/python tests`: passed.
- `uv run --frozen --offline ruff format --check tests/unit/infra/test_sales_xray_routing.py`: passed.
- Focused routing pytest: **16 passed in 15.83 seconds**, no skips.
- Actual JUnit: [routing-ci.junit.xml](sales-routing-ci-20260914/routing-ci.junit.xml).

The tests use local fixture transports; no Cloudflare DNS or tunnel configuration
was changed. This receipt does not mark combined CI, staging or production passed.
