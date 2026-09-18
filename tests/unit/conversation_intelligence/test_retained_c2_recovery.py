"""Contracts for the no-provider-call retained C2 recovery boundary."""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any, cast
from uuid import uuid4

from ac_platform.conversation_intelligence.reporting_pipeline import _raw_response_binding
from ac_platform.conversation_intelligence.retained_c2_recovery import retained_c2_receipt


def test_retained_receipt_names_source_and_zero_provider_calls() -> None:
    source_run_id = uuid4()
    source_recording_id = uuid4()
    source = cast(
        Any,
        SimpleNamespace(
            receipt={
                "provider": "deepgram",
                "model": "nova-3",
                "response_sha256": "a" * 64,
                "provider_request_id": "request-1",
                "usage": {"total_tokens": 12},
            },
            task=SimpleNamespace(run_id=source_run_id),
            recording=SimpleNamespace(id=source_recording_id),
        ),
    )
    job = cast(Any, SimpleNamespace(dedupe_key=f"conversation:provider:{uuid4()}"))
    checkpoint = cast(Any, SimpleNamespace(id=uuid4(), manifest_sha256="b" * 64))

    receipt = retained_c2_receipt(
        job=job,
        source=source,
        checkpoint=checkpoint,
        input_sha256="c" * 64,
    )

    assert "provider_calls" not in receipt
    assert receipt["raw_blob_id"] == str(source_run_id)
    assert receipt["retained_reuse"] == {
        "schema": "ac.sales-xray.retained-c2-reuse/1",
        "provider_calls": 0,
        "source_recording_id": str(source_recording_id),
        "source_run_id": str(source_run_id),
        "source_response_sha256": "a" * 64,
    }


def test_reporting_accepts_only_explicit_source_blob_marker() -> None:
    task = cast(Any, SimpleNamespace(run_id=uuid4()))
    target_recording = cast(Any, SimpleNamespace(id=uuid4()))
    source_recording_id = str(uuid4())
    source_run_id = str(uuid4())
    response_sha256 = "a" * 64
    receipt: dict[str, Any] = {
        "raw_blob_id": source_run_id,
        "response_sha256": response_sha256,
        "retained_reuse": {
            "schema": "ac.sales-xray.retained-c2-reuse/1",
            "provider_calls": 0,
            "source_recording_id": source_recording_id,
            "source_run_id": source_run_id,
            "source_response_sha256": response_sha256,
        },
    }

    assert _raw_response_binding(receipt, task, target_recording)
    assert not _raw_response_binding(
        receipt,
        task,
        cast(Any, SimpleNamespace(id=source_recording_id)),
    )
    receipt["retained_reuse"]["provider_calls"] = 1
    assert not _raw_response_binding(receipt, task, target_recording)


def test_normal_receipt_remains_task_local() -> None:
    task = cast(Any, SimpleNamespace(run_id=uuid4()))
    recording = cast(Any, SimpleNamespace(id=uuid4()))
    receipt = {"raw_blob_id": str(task.run_id)}

    assert _raw_response_binding(receipt, task, recording)
    receipt["raw_blob_id"] = str(uuid4())
    assert not _raw_response_binding(receipt, task, recording)
