# Sales Xray v0.2 integration record

Date: 2026-09-24. Branch: `codex/sales-xray-v02-integration-20260924`.

## Exact inputs integrated

- Base: `4bbc2b790431949314d5464fe1973b62d02f87e7`
- v0.2 intake: `2217d41d5c21aeae64b886d4f17eeb3ee6329b32` → merge `aa54f379`
- Google auth recovery: `0e0eca6e0cdde19383324fb333d6c965c01d46c0` → merge `041e72b9`
- Avatar transport: `b6f1cf7062d59a52593070972c06ed2d2816baff` → merge `7ff3581f`

## Conflict resolutions

- v0.2 intake: kept its report-reader/navigation, excerpt playback, multi-file intake, and paused-processing work while retaining stack regressions around bookmarked report tabs, stale dialogs, auth preview gating, and profile display name. Report moments use explicit empty `rewatch` as intentional zero; finding evidence remains available in report details and legacy reports retain fallback behavior.
- Google recovery: preserved the incoming completion/consent behavior and persistence assertions. Kept stricter existing account profile phone-field assertions and the pre-existing account integration test where the conflict was formatting-only. Login without renewed consent returns no prior consent receipt in the response while retaining the historical DB/audit record.
- Avatar transport: retained hosted upload implementation and test coverage for cross-origin URLs, malformed object keys/tokens, signed length/checksum, and same-origin transport. Combined the existing raw-host authority note with the incoming proxy-header-disabled safeguard.

## Root triage evidence

`CODEX-TRIAGE.md` is a byte-for-byte copy of the current root-authored triage file. SHA-256: `FA50C402B0F1A1ED99E84D85E8335A47DB2BB97C31AF1BE5AD2638F92B7464BE`.

## Validation

Integration code/test baseline: `b958ace741c07f50bdaaedeb740053a30688c6ce`.

- The standalone production build completed successfully with Node `v24.19.0`.
- Sales Xray app typecheck, lint and Prettier check over the complete `apps/sales-xray-web/app` directory passed.
- The serial Sales Xray Vitest suite passed **457 tests across 52 files** after the UI behavior fixes and before the formatting-only pass. The focused UI suite passed 24 tests. Formatting did not alter test behavior.
- Appendix B Python tests passed **246 tests** using a temporary directory under `C:\Temp`.
- Avatar transport checks passed: media upload telemetry **21**, avatar contract **1**, local avatar runtime **47**.
- Authentication/profile PostgreSQL checks passed **24 tests**. Separately, the release owner ran the inference and processing-plan PostgreSQL baseline at exact merge `7ff3581f`: **37 passed**. That baseline used synthetic providers and made no provider calls.
- The required compiled-browser gate passed **1 test / 24 assertions** on the rebuilt standalone app. Its separate receipt records build ID `1MegdQMG4LII8UWQrj_dz`, 97 local HTTP responses, zero API interceptions, zero provider network calls, zero page errors, and synthetic-only challenge/native adapters. Pytest: `1 passed in 236.82s`.
- The first browser-gate attempt is preserved separately and **failed** at the obsolete `summary[aria-label="More report actions"]` selector. The test now targets the current accessible `Sales call report` → `Report actions` group → `Request deletion` button and retains the deletion confirmation assertions. Both attempts' bounded proof and receipt JSON files are committed alongside this record; full screenshots/logs remain in `C:\Temp\salesxray-acquisition-browser-c53bb0cb419442e58075e21af10c2087` and `C:\Temp\salesxray-acquisition-browser-rerun-20260924-7ff3581f-ea48d13b`.

## Release boundary and open work

This is a tested local integration baseline, not a release receipt. Nothing was deployed, no production database was changed, and no external analysis provider was called. Root triage continues to hold PR1-A and PR3 out of this merge, and the named-tester concurrency change remains held pending its lock-order correction and deterministic concurrency/report-completion evidence. Broader handoff work, exact-candidate canonical CI, staging acceptance and production verification remain outstanding. The browser proof is synthetic functional evidence; it is not design approval or evidence of provider quality.

