import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from pydantic import ValidationError

from ac_platform.conversation_intelligence.contracts import RecordingIntent
from ac_platform.http.conversation import install_conversation_http


def test_caller_cannot_select_tenant_or_enable_providers():
    payload = dict(
        source_sha256="a" * 64,
        source_bytes=100,
        content_type="audio/mpeg",
        permission_reference="aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa",
        purpose="internal_analysis",
    )
    RecordingIntent.model_validate(payload)
    for key, value in [
        ("tenant_id", "forged"),
        ("provider_processing", True),
        ("source_bytes", True),
        ("source_bytes", 134217729),
        ("source_sha256", "../secret"),
    ]:
        with pytest.raises(ValidationError):
            RecordingIntent.model_validate({**payload, key: value})


def test_example_is_authored_and_no_intake_or_paid_route_is_exposed():
    app = FastAPI()
    install_conversation_http(app)
    with TestClient(app) as client:
        capability = client.get("/v1/conversation/capabilities")
        assert capability.json()["provider_processing"] == "disabled"
        assert capability.json()["numeric_publication"] == "withheld"
        assert capability.headers["cache-control"] == "no-store"
        sample = client.get("/v1/conversation/example").json()
        assert sample["state"] == "example"
        assert sample["profile"]["source_total"] == 95
        assert sample["profile"]["declared_total"] == 100
        assert sample["profile"]["numeric_score"] is None
        assert sample["measurements"]["state"] == "not_measured"
        assert "Authored" in sample["provenance"]
        assert client.post("/v1/conversation/recordings", content=b"media").status_code == 404
        assert client.post("/v1/conversation/runs", json={}).status_code == 404
