"""Failure details remain useful without retaining response or credential text."""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock

import pytest

from ac_platform.conversation_intelligence.inference_tasks import InferenceTaskError
from ac_platform.conversation_intelligence.inference_worker import (
    ConversationInferenceWorker,
    provider_failure_code,
)
from ac_platform.conversation_intelligence.storage import StorageError


@pytest.mark.parametrize(
    ("error", "expected"),
    [
        (
            InferenceTaskError("report_findings_invalid"),
            "conversation_report_findings_invalid",
        ),
        (
            InferenceTaskError("report_findings_invalid: private response"),
            "conversation_provider_result_validation_failed",
        ),
        (
            InferenceTaskError("report_evidence_quote_mismatch"),
            "conversation_report_evidence_quote_mismatch",
        ),
        (
            InferenceTaskError("fact_evidence_outside_chunk"),
            "conversation_fact_evidence_outside_chunk",
        ),
        (
            InferenceTaskError("report_evidence_quote_mismatch: private words"),
            "conversation_provider_result_validation_failed",
        ),
        (
            InferenceTaskError("report_evidence_quote_mismatch", "private words"),
            "conversation_provider_result_validation_failed",
        ),
        (
            ValueError("report_evidence_quote_mismatch"),
            "conversation_provider_execution_unresolved",
        ),
        (
            RuntimeError("https://provider.invalid/?key=private-value"),
            "conversation_provider_execution_unresolved",
        ),
        (TimeoutError("private response"), "conversation_provider_execution_timeout"),
        (StorageError("private path"), "conversation_provider_storage_failed"),
    ],
)
def test_only_explicitly_allowlisted_validation_codes_are_retained(
    error: BaseException, expected: str
) -> None:
    assert provider_failure_code(error) == expected


@pytest.mark.asyncio
async def test_validation_failure_is_reported_once_without_another_dispatch() -> None:
    worker = ConversationInferenceWorker.__new__(ConversationInferenceWorker)
    work = object()
    worker.claim = AsyncMock(return_value=work)  # type: ignore[method-assign]
    worker._dispatch = AsyncMock(  # type: ignore[method-assign]
        side_effect=InferenceTaskError("report_evidence_quote_mismatch")
    )
    worker._fail = AsyncMock()  # type: ignore[method-assign]

    assert await worker.run_once() is True

    worker._dispatch.assert_awaited_once_with(work)
    worker._fail.assert_awaited_once_with(
        work, failure_code="conversation_report_evidence_quote_mismatch"
    )


@pytest.mark.asyncio
async def test_cancellation_still_drains_failure_acknowledgement_and_propagates() -> None:
    worker = ConversationInferenceWorker.__new__(ConversationInferenceWorker)
    work = object()
    worker.claim = AsyncMock(return_value=work)  # type: ignore[method-assign]
    worker._dispatch = AsyncMock(side_effect=asyncio.CancelledError())  # type: ignore[method-assign]
    worker._fail = AsyncMock()  # type: ignore[method-assign]

    with pytest.raises(asyncio.CancelledError):
        await worker.run_once()

    worker._dispatch.assert_awaited_once_with(work)
    worker._fail.assert_awaited_once_with(
        work, failure_code="conversation_provider_execution_unresolved"
    )
