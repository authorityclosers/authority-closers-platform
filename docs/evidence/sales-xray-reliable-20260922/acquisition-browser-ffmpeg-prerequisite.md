# Acquisition browser FFmpeg prerequisite repair

Date: 2026-09-22

Workflow job: `validate-sales-xray-acquisition-browser`

Failed run: `66240141`

The required compiled browser job built AudioAtlas successfully, then failed
at the first source upload: the browser expected HTTP 202 and received HTTP 422. The bounded JUnit artifact was:

```text
D:\AuthorityClosers-Private\sales-xray-reliable-20260922\ci-browser-35746012526\acquisition-browser.junit.xml
```

The test replaces `SocketNativeRuntime.validate_source` with the real local
`signals.validate_media` implementation. That implementation requires both
`ffprobe` and `ffmpeg` for media validation. The dedicated browser workflow
installed Playwright dependencies and built the native AudioAtlas binary, but
did not install or verify those two codec tools. The source PUT therefore
failed before the browser journey could reach the report path.

The repair adds an explicit `Install FFmpeg prerequisites for acquisition
browser` step before Playwright/native execution. It installs the runner
package `ffmpeg`, then fails closed on missing `ffmpeg` or `ffprobe`
using `command -v` and records their versions. The workflow contract test
asserts the exact step, command order, and placement before the browser and
native steps.

The source PUT assertion now reports only bounded, sanitized response fields:
HTTP status, problem code, title, and whitespace-normalized detail truncated
to 240 characters. It does not include the submission URL, request body,
credentials, or raw response payload.

## Verification

```text
python -m pytest -q tests/infra/test_recovery_ci_gates.py
8 passed in 0.85s

ruff check tests/infra/test_recovery_ci_gates.py tests/e2e/test_sales_xray_acquisition_browser.py
All checks passed!

ruff format --check tests/infra/test_recovery_ci_gates.py tests/e2e/test_sales_xray_acquisition_browser.py
2 files already formatted

git diff --check -- .github/workflows/application.yml tests/infra/test_recovery_ci_gates.py tests/e2e/test_sales_xray_acquisition_browser.py
passed
```

No provider, production database, deployment, or customer data was used. No
commit was made by this repair task.
