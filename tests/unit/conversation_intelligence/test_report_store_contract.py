"""Regression: malformed internal draft content produces validation errors."""

from typing import Any

import pytest
from pydantic import ValidationError

from ac_platform.conversation_intelligence.report_store import PrivateDraftIntent


@pytest.mark.parametrize("invalid", [b"not-json", {1, 2}, float("nan"), "\ud800"])
def test_non_json_report_content_is_a_validation_error(invalid: Any) -> None:
    with pytest.raises(ValidationError, match="valid JSON"):
        PrivateDraftIntent.model_validate(
            {
                "raw_transcription_json": "{}",
                "report": {"summary": invalid},
                "receipt": {
                    "schema_id": "ac.sales-xray.private-proof-reference/1",
                    "approval_receipt_sha256": "a" * 64,
                    "transcription_response_sha256": "b" * 64,
                    "generation_receipt_sha256": "c" * 64,
                    "source_review_receipt_sha256": "d" * 64,
                    "new_provider_calls": 0,
                },
            }
        )
