"""Sanitized failure receipts for the synthetic Sales Xray browser gate."""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SPEC = importlib.util.spec_from_file_location(
    "sales_xray_acquisition_browser_gate",
    ROOT / "scripts/ci/verify_sales_xray_acquisition_browser.py",
)
assert SPEC and SPEC.loader
gate = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(gate)


def test_failure_summary_extracts_the_failed_step_and_redacts_message(tmp_path: Path) -> None:
    report = tmp_path / "pytest.junit.xml"
    report.write_text(
        """<testsuites><testsuite><testcase
          name="test_compiled_account_required_upload_profile_otp_report_relogin_and_deletion">
          <failure type="playwright.async_api.TimeoutError"
            message="TimeoutError: Timeout 30000ms exceeded for
              learner@example.test?token=fixture-query">
            Traceback (most recent call last):
              tests/e2e/test_sales_xray_acquisition_browser.py:985: in test_case
              File "/checkout/tests/e2e/test_sales_xray_acquisition_browser.py", line 603
            E TimeoutError: Timeout 30000ms exceeded for learner@example.test?token=fixture-query
          </failure></testcase></testsuite></testsuites>""",
        encoding="utf-8",
    )

    summary = gate._pytest_failure_summary(report)

    assert "node=" + gate.TEST_NODE in summary
    assert "location=tests/e2e/test_sales_xray_acquisition_browser.py:603" in summary
    assert "exception=TimeoutError" in summary
    assert "Timeout 30000ms exceeded" in summary
    assert "learner@example.test" not in summary
    assert "fixture-query" not in summary
    assert len(summary) <= 300


def test_redactor_removes_emails_codes_tokens_cookies_queries_and_database_urls() -> None:
    detail = (
        "learner@example.test OTP: 839201 Bearer fixture.bearer.token "
        "https://example.test/report?token=fixture-query "
        "postgresql://fixture-user:fixture-password@localhost/fixture-db "
        "Cookie: session=fixture-cookie; Path=/"
    )

    summary = gate._redact_failure_summary(detail)

    for secret in (
        "learner@example.test",
        "839201",
        "fixture.bearer.token",
        "fixture-cookie",
        "fixture-query",
        "fixture-user",
        "fixture-password",
        "fixture-db",
    ):
        assert secret not in summary
    assert "[redacted email]" in summary
    assert "[redacted code]" in summary
    assert "Bearer [redacted token]" in summary
    assert "[redacted cookie]" in summary
    assert "[redacted query]" in summary
    assert "[redacted database URL]" in summary
    assert len(gate._redact_failure_summary("x" * 400)) == 300


def test_redactor_removes_driver_qualified_database_urls() -> None:
    database_urls = (
        "postgresql+psycopg://fixture-user:fixture-password@db/fixture-db "
        "postgresql+asyncpg://fixture-async-user:fixture-async-password@"
        "127.0.0.1:55432/fixture-async-db"
    )

    summary = gate._redact_failure_summary(database_urls)

    for secret in (
        "fixture-user",
        "fixture-password",
        "fixture-db",
        "fixture-async-user",
        "fixture-async-password",
        "fixture-async-db",
    ):
        assert secret not in summary
    assert summary == "[redacted database URL] [redacted database URL]"


def test_failure_receipt_includes_a_redacted_failure_summary(tmp_path: Path) -> None:
    receipt = tmp_path / "failure.json"
    gate._write_failure_receipt(
        receipt,
        {
            "reason": "The required Sales Xray browser case failed",
            "failure_summary": "node=test email=learner@example.test OTP=928371",
        },
    )

    saved = json.loads(receipt.read_text(encoding="utf-8"))

    assert "learner@example.test" not in saved["failure_summary"]
    assert "928371" not in saved["failure_summary"]
    assert "[redacted email]" in saved["failure_summary"]
