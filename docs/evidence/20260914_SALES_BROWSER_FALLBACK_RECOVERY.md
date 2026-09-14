# Sales Xray disabled acquisition fallback evidence

Date: 2026-09-14. Source commit: `d293604476a436be6cec596be9b315d9d625b523`.

The fallback backends compose `install_acquisition_runtime(..., runtime=None)` with `sales_xray_app_url` bound to the loopback browser origin. `/v1/conversation/acquisition/entry` therefore returns `enabled: false`; guest upload/provider/native handlers are not mounted. The enabled guest flow remains separately covered by `tests/e2e/test_sales_xray_acquisition_browser.py`.

Three original browser journeys passed against the static build and disposable loopback PostgreSQL (`127.0.0.1:55432`), with no API response interception or provider calls:

- `test_real_browser_saved_report_playback_and_local_upload`: `1 passed`; receipt `D:\AC-authority-closers-release-audit\activation-20260914\sales-ci-browser-report-tmp\test_real_browser_saved_report0\authenticated-browser.json`; SHA-256 `8de62128af0f7d9fdd177a273abf9a95d32be0bfb14568c6abe398bc34ffdc58`.
- `test_real_browser_durable_worker_report_playback`: `1 passed`; receipt `D:\AC-authority-closers-release-audit\activation-20260914\sales-ci-browser-report-tmp\test_real_browser_durable_work0\durable-authenticated-browser.json`; SHA-256 `84059fd00d500cdd19c9753931c740c143b59a77ddab2a0a375668b7b19c3c9b`.
- `test_standalone_sales_xray_password_workspace_and_logout_browser_proof`: `1 passed`; receipt `D:\AC-authority-closers-release-audit\activation-20260914\sales-ci-browser-standalone-tmp\test_standalone_sales_xray_pas0\standalone-auth-browser.json`; SHA-256 `15c0f22832245d01640e79c2f9bb1621a1aa1dcc1158ce35e3e1b4eb135aee7c`.

Receipts cover source-bound report/audio access, private range playback, durable C5/C6 rendering, workspace membership isolation, and post-logout `401` source/measurement access. The standalone receipt records the exact cancelled `HEAD /login/: net::ERR_ABORTED` probe; the test accepts it only with the existing navigation cancellation and independently verified successful login/logout responses. No other request failures remained. Receipts stay external and are referenced by path and hash only.
