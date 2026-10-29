import json
from dataclasses import replace

import pytest

from ac_platform.learning.planning_repository import PlanningRepository
from ac_platform.telemetry import durable
from ac_platform.telemetry.sales_xray import SALES_XRAY_SURFACE
from tests.unit.http.test_sales_xray_telemetry_routes import _ORIGIN, _Harness


@pytest.fixture
def harness():
    value = _Harness()
    yield value
    value.session.close()
    value.engine.dispose()


def test_person_cap_acknowledges_spool(harness, tmp_path):
    client = harness.client(replace(SALES_XRAY_SURFACE, person_daily_cap=0))
    event = harness.event()
    response = client.post("/v1/telemetry/events", json={"events": [event]}, headers=_ORIGIN)
    assert response.status_code == 202
    assert response.json()["hot_store_full"] is True
    assert response.json()["spool_receipt"]
    files = list((tmp_path / "telemetry" / "test").glob("*.open"))
    assert json.loads(files[0].read_text())["events"][0]["event_id"] == event["event_id"]


def test_postgres_failure_preserves_batch_and_outer_transaction(harness, tmp_path, monkeypatch):
    def failed(_self, database, _events):
        from sqlalchemy import text

        database.execute(text("SELECT * FROM telemetry_test_unavailable_table"))

    monkeypatch.setattr(PlanningRepository, "add_analytics_events", failed)
    client = harness.client()
    event = harness.event()
    response = client.post("/v1/telemetry/events", json={"events": [event]}, headers=_ORIGIN)
    assert response.status_code == 202
    assert response.json()["reason"] == "hot_store_unavailable"
    assert (
        durable.day_inventory(tmp_path / "telemetry" / "test", event["occurred_at"][:10])["events"]
        == 1
    )
    assert harness.session.is_active


def test_spool_outage_returns_real_503(harness, monkeypatch):
    def failed(*_):
        raise durable.SpoolUnavailable("full")

    monkeypatch.setattr(durable, "append", failed)
    response = harness.client().post(
        "/v1/telemetry/events", json={"events": [harness.event()]}, headers=_ORIGIN
    )
    assert response.status_code == 503


def test_spooled_batch_backfills_idempotently_with_current_privacy(harness, tmp_path):
    from datetime import UTC, datetime

    from ac_platform.telemetry.raw_cli import backfill
    from ac_platform.telemetry.sales_xray_consent import PERSON_ACTION

    response = harness.client(replace(SALES_XRAY_SURFACE, person_daily_cap=0)).post(
        "/v1/telemetry/events",
        json={"events": [harness.event()]},
        headers=_ORIGIN,
    )
    assert response.status_code == 202
    path = next((tmp_path / "telemetry" / "test").glob("*.open"))
    now = datetime.now(UTC)
    assert backfill(harness.session, path, now=now)["stored"] == 1
    assert backfill(harness.session, path, now=now)["duplicate"] == 1
    harness.choice(str(harness.person_id), False, action=PERSON_ACTION)
    assert backfill(harness.session, path, now=now)["skipped"] == 1


def test_backfill_preserves_server_call_refs_and_skips_conflicts(harness, tmp_path):
    from datetime import UTC, datetime

    from ac_platform.telemetry.raw_cli import backfill

    submission, _ = harness.call()
    harness.key()
    client = harness.client()
    event = harness.event(call_id=str(submission))
    assert (
        client.post("/v1/telemetry/events", json={"events": [event]}, headers=_ORIGIN).status_code
        == 202
    )
    path = next((tmp_path / "telemetry" / "test").glob("*.open"))
    assert backfill(harness.session, path, now=datetime.now(UTC))["duplicate"] == 1
    conflict = {**event, "payload": {"section": "analysis", "read_band": "30_120s"}}
    result = client.post("/v1/telemetry/events", json={"events": [conflict]}, headers=_ORIGIN)
    assert result.status_code == 409
    # A following legitimate, raw-only batch must still recover.
    capped = harness.client(replace(SALES_XRAY_SURFACE, person_daily_cap=0))
    assert (
        capped.post(
            "/v1/telemetry/events", json={"events": [harness.event()]}, headers=_ORIGIN
        ).status_code
        == 202
    )
    result = backfill(harness.session, path, now=datetime.now(UTC))
    assert result["conflicts"] == 1 and result["stored"] == 1
