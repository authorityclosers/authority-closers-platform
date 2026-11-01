"""A refused request never comes back in the answer (simulation lab, 1 Nov 2026: a call-log batch
of 201 calls answered 422 with every phone number in it). Every route says where and why only;
the message still gives the count and the limit. Made-up numbers only."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any
from uuid import uuid4

from fastapi import FastAPI
from fastapi.exceptions import RequestValidationError
from fastapi.testclient import TestClient

from ac_platform.http.platform_sensitive_segments import _validation_without_input
from ac_platform.lead_desk.contracts import PhoneLog


def batch(size: int) -> dict[str, Any]:
    return {
        "device_id": str(uuid4()),
        "calls": [
            {
                "log_id": f"log-{index}",
                "number": f"+91 98760 {index:05d}",
                "started_at": datetime(2026, 11, 1, 6, 0, tzinfo=UTC).isoformat(),
                "duration_seconds": 30,
                "direction": "outgoing",
            }
            for index in range(size)
        ],
    }


def test_a_refused_call_log_never_echoes_its_numbers() -> None:
    app = FastAPI()
    app.add_exception_handler(RequestValidationError, _validation_without_input)

    @app.post("/v1/lead-desk/phone-log")
    async def phone_log(command: PhoneLog) -> int:
        return len(command.calls)

    client = TestClient(app)
    answer = client.post("/v1/lead-desk/phone-log", json=batch(201))
    assert answer.status_code == 422
    assert "98760" not in answer.text and "log-" not in answer.text
    (error,) = answer.json()["detail"]
    assert set(error) == {"loc", "msg", "type"}
    assert error["loc"] == ["body", "calls"]
    assert "200" in error["msg"] and "201" in error["msg"]
    assert answer.headers["cache-control"] == "private, no-store"

    # One bad row: where it is, never what it said.
    wrong = batch(3)
    wrong["calls"][1]["direction"] = "sideways"
    refused = client.post("/v1/lead-desk/phone-log", json=wrong)
    assert refused.status_code == 422 and "98760" not in refused.text
    assert refused.json()["detail"][0]["loc"] == ["body", "calls", 1, "direction"]

    # The limit itself goes through.
    assert client.post("/v1/lead-desk/phone-log", json=batch(200)).json() == 200
