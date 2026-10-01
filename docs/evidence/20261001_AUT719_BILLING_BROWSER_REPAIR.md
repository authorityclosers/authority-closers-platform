# AUT-719 — billing browser CI repair

Base: `3cba094e14ba7c45e3c67c0e506cf6ae92caff05`, existing
`task/billing/560-billing-backend`, [PR #179](https://github.com/authorityclosers/authority-closers-platform/pull/179).

The failed browser gate in [run 36926915669](https://github.com/authorityclosers/authority-closers-platform/actions/runs/36926915669)
stopped after profile completion because the session read returned HTTP 500.
The retained artifact contained proof/receipt JSON and JUnit, but no screenshot.
The synthetic provider authority used the public learner tenant as its operations
tenant. The billing ledger correctly refuses a Personal account in that tenant.
This was a fixture boundary error; the new-account trial projection returns
3,600 seconds when composed with distinct tenants.

The shared test setup now offers `separate_operations=True`. In this mode it
seeds a separate operations owner, writes the synthetic provider configuration
there, and pins both the validated approval bundle and authority to that tenant.
The browser opts into this mode and uses the same tenant for identity audits.
Other fixture callers retain their previous default. Production code, admission
rules, billing settings, prices and credentials are unchanged.

The browser asserts the authenticated session immediately after profile
completion, before checking the existing Analyse button and upload flow:

```json
{
  "state": "account",
  "allowance": {
    "allowance_seconds": 3600,
    "committed_seconds": 0,
    "available_seconds": 3600
  }
}
```

A PostgreSQL regression composes the real acquisition runtime factory with the
synthetic provider authority, default trial v1, no switch timestamp and billing
disabled. Session, plan and usage return the same allowance. The owner's
billing account and ledger entries remain absent before and after these reads.
These checks are scoped to the new fixture owner because the module also tests
other accounts on its shared disposable schema.

## Server validation

All database tests used the existing isolated loopback billing lane database.
No deployed application or real provider was contacted.

- `pnpm install --frozen-lockfile` — exit 0.
- `AC_CONVERSATION_API_ORIGIN=http://127.0.0.1:18116 NEXT_TELEMETRY_DISABLED=1 pnpm --filter @ac/sales-xray-web build` — exit 0; Node 24.19.0.
- `uv run --frozen python -c 'from ac_platform.conversation_intelligence.signals import build_native, _native_executable; built = build_native(); assert _native_executable(None) == built.resolve(); print("Verified AudioAtlas build is ready")'` — exit 0, CI's native prerequisite verified.
- `uv run ruff format --check packages/python tests` — exit 0, 839 files formatted.
- `uv run ruff check packages/python tests` — exit 0.
- `uv run mypy packages/python` — exit 0, 359 source files.
- `uv run pytest tests/unit/billing/test_ledger.py -q` — exit 0, **40 passed**, including the operations-tenant refusal.
- `uv run pytest tests/integration/test_me_plan_usage_postgresql.py -q` — exit 0, **3 passed**.
- `uv run pytest tests/database/test_conversation_submission_http_postgresql.py::test_shared_upload_is_silent_and_erasure_releases_only_its_owner tests/database/test_conversation_submission_http_postgresql.py::test_reupload_earlier_report_hint_is_scoped_to_the_current_owner -q` — exit 0, **3 passed**.
- `uv run --frozen python scripts/ci/verify_sales_xray_acquisition_browser.py --evidence-dir "$PAPERCLIP_RUN_SCRATCH_DIR/browser-native-verified"` — exit 0, **all 24 assertions passed**, zero provider network calls, zero API interceptions and no page errors. A temporary scratch pytest plugin wrapped the local worker only to report and rethrow exceptions; it did not change results or intercept API responses. The sanitized proof JSON is attached to AUT-719.
- `git diff --check` — exit 0.

The first combined database run had 17 passes and four failures: the new test
incorrectly asserted that the entire shared schema had no billing accounts, and
three existing media cases ran before the verified native build prerequisite.
The owner-scoped assertion was corrected, the full three-test usage suite was
rerun, and all three media cases were rerun successfully after that prerequisite.
Every case in the original 21-case combined selection is therefore covered by
passing evidence. An intermediate browser run also failed in its local worker
before that prerequisite; the final complete browser proof passed.

## Review and dev check

Reproduce the PostgreSQL regression and the compiled browser command above on
the isolated dev test database, with CI's Node/native/browser prerequisites.
The ordinary deployed billing routes remain absent while `AC_BILLING_ENABLED`
is off. This repair does not perform a dev deployment or real Razorpay TEST
payment. CI must pass on the pushed head before CTO review, CEO approval and
watchdog merge.
