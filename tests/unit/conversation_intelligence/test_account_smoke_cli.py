"""QA operator receipts retain call IDs but discard accidental exception content."""

import importlib.util
import json
from pathlib import Path
from uuid import uuid4

import pytest

from ac_platform.conversation_intelligence.account_smoke import SmokeFailure

SPEC = importlib.util.spec_from_file_location(
    "account_smoke_cli",
    Path(__file__).resolve().parents[3] / "scripts/sales-xray-account-smoke.py",
)
assert SPEC and SPEC.loader
CLI = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(CLI)


@pytest.mark.parametrize("expected", [True, False])
def test_operator_failure_output_is_content_free(monkeypatch, capsys, expected):
    submission_id = uuid4()

    async def failed(args):
        if expected:
            raise SmokeFailure("qa_analysis_failed_or_held", submission_id=submission_id)
        raise ValueError("fictional-untrusted-exception-content")

    monkeypatch.setattr(CLI, "smoke", failed)
    assert CLI.main(["--environment", "staging"]) == 1
    output = capsys.readouterr()
    assert "untrusted" not in output.out + output.err
    if expected:
        receipt = json.loads(output.out)
        assert receipt["ok"] is False
        assert receipt["failure_code"] == "qa_analysis_failed_or_held"
        assert receipt["submission_id"] == str(submission_id)
    else:
        assert not output.out and "QA smoke failed" in output.err
