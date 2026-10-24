"""Admin's product telemetry: speed and slow-device share, vitals, screens, funnels, errors."""

from __future__ import annotations

from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import uuid4

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from ac_platform.audit.models import AuditEvent
from ac_platform.db.models import model_metadata
from ac_platform.learning.planning_models import AnalyticsEvent
from ac_platform.telemetry.admin_view import (
    Filters,
    Read,
    Row,
    overview,
    read_consent,
    read_rows,
)
from ac_platform.telemetry.sales_xray import NOTICE_VERSION, RETENTION_POLICY_ID
from ac_platform.telemetry.sales_xray_consent import PERSON_ACTION, RESOURCE_TYPE

NOW = datetime(2026, 10, 24, 6, 0, tzinfo=UTC)


def _row(
    event: str,
    person: str = "p1",
    *,
    minutes_ago: float = 10,
    release: str = "v0.86",
    session: str | None = "s1",
    **payload: Any,
) -> Row:
    return Row(
        event=event,
        at=NOW - timedelta(minutes=minutes_ago),
        release=release,
        person=person,
        workspace="w1",
        session=session,
        payload=payload,
    )


def _view(rows: list[Row], **filters: Any) -> dict[str, Any]:
    return overview(
        Read(rows=rows),
        now=NOW,
        window="7d",
        filters=Filters(**filters),
        consent={"people_off": 1, "workspaces_off": 0},
        environment="development",
    )


def test_speed_says_which_share_of_taps_and_devices_are_slow_by_tier() -> None:
    rows = [
        # A low-end phone: every lead opens slowly.
        *(
            _row(
                "sx.action_timing",
                "slow",
                action="lead_open",
                ms=value,
                result="settled",
                device="phone",
                tier="low",
                paint_ms=180,
            )
            for value in (1_800, 2_100, 1_500)
        ),
        # Two quick devices.
        *(
            _row(
                "sx.action_timing",
                person,
                action="lead_open",
                ms=value,
                result="settled",
                device=device,
                tier="high",
                paint_ms=40,
            )
            for person, device, value in (("a", "desktop", 300), ("b", "phone", 450))
        ),
        _row("sx.action_timing", "a", action="tab_switch", ms=120, result="no_change"),
    ]
    view = _view(rows)
    lead = next(item for item in view["speed"] if item["action"] == "lead_open")
    assert lead["taps"] == 5
    assert lead["slow_ms"] == 1_000
    assert lead["slow_share"] == 0.6
    assert lead["devices"] == 3
    assert lead["slow_device_share"] == round(1 / 3, 4)
    assert lead["p75"] == 1_800
    assert lead["paint_p75"] == 180
    tiers = {item["tier"]: item for item in lead["by_tier"]}
    assert tiers["low"]["slow_share"] == 1.0
    assert tiers["high"]["slow_share"] == 0.0
    assert {item["device"] for item in lead["by_device"]} == {"phone", "desktop"}
    tab = next(item for item in view["speed"] if item["action"] == "tab_switch")
    assert tab["results"] == {"settled": 0, "timeout": 0, "no_change": 1}
    # A filter narrows every part.
    phones = _view(rows, device="phone")
    assert next(item for item in phones["speed"] if item["action"] == "lead_open")["taps"] == 4


def test_vitals_screens_flows_and_exits() -> None:
    rows = [
        _row(
            "sx.web_vital", metric="lcp", value=value, rating=rating, screen="leads", device="phone"
        )
        for value, rating in (
            (1_900, "good"),
            (2_400, "good"),
            (4_600, "poor"),
            (3_000, "needs_improvement"),
        )
    ] + [
        _row("sx.screen_viewed", screen="leads", nav="first", minutes_ago=30),
        _row(
            "sx.screen_viewed",
            screen="lead",
            nav="push",
            **{"from": "leads"},
            stay_ms=4_000,
            minutes_ago=29,
        ),
        _row(
            "sx.screen_viewed",
            screen="report",
            nav="push",
            **{"from": "lead"},
            stay_ms=9_000,
            minutes_ago=28,
        ),
        _row("sx.screen_viewed", "p2", screen="leads", nav="first", session="s2"),
    ]
    view = _view(rows)
    [lcp] = view["vitals"]
    assert lcp["p75"] == 3_000
    assert lcp["rating"] == "needs_improvement"
    assert lcp["shares"]["poor"] == 0.25
    screens = {item["screen"]: item for item in view["screens"]["rows"]}
    assert screens["leads"]["views"] == 2
    assert screens["leads"]["people"] == 2
    assert screens["leads"]["stay_p50"] == 4_000
    # Session s1 ended on the report; s2 on Leads.
    assert screens["report"]["exit_share"] == 1.0
    assert screens["leads"]["exit_share"] == 0.5
    assert sum(screens["leads"]["heat"]) == 2
    assert len(view["screens"]["buckets"]) == 8  # 7 days and today
    assert {"from": "leads", "to": "lead", "count": 1} in view["screens"]["flows"]


def test_funnels_features_errors_releases_and_mix() -> None:
    rows = [
        _row("sx.report_opened", "a", view="report"),
        _row("sx.report_opened", "b", view="report"),
        _row("sx.section_read", "a", section="analysis", read_band="30_120s", look="brain4"),
        _row("sx.section_read", "b", section="analysis", read_band="under_5s"),
        _row("sx.full_report_requested", "a", surface="report"),
        _row("sx.outcome_set", "a", outcome="won"),
        _row("sx.feature_used", "b", feature="bulk_import"),
        _row(
            "sx.js_error",
            "a",
            kind="error",
            error="typeerror",
            where="e1a2b3c4",
            screen="report",
            source="app",
        ),
        _row(
            "sx.js_error",
            "b",
            kind="error",
            error="typeerror",
            where="e1a2b3c4",
            screen="report",
            source="app",
            release="v0.85",
        ),
        _row("sx.api_slow", "a", endpoint="v1_leads_id", status="5xx", ms=4_000),
        _row("sx.tap_issue", "a", kind="rage", target="button", screen="leads"),
        _row("sx.error_shown", "a", surface="connection_card", code="read_failed"),
    ]
    view = _view(rows)
    report = next(item for item in view["funnels"] if item["key"] == "report")["steps"]
    assert [step["people"] for step in report] == [2, 1, 1, 1]
    assert report[1]["share"] == 0.5
    features = {item["feature"]: item for item in view["features"]["rows"]}
    assert features["report"]["people"] == 2
    assert features["coaching_score"]["people"] == 2
    assert features["bulk_import"]["share"] == 0.5
    [script] = view["errors"]["scripts"]
    assert script["count"] == 2
    assert script["people"] == 2
    assert set(script["releases"]) == {"v0.86", "v0.85"}
    assert view["errors"]["apis"][0]["failed"] == 1
    assert view["errors"]["taps"][0]["kind"] == "rage"
    assert view["errors"]["shown"][0]["code"] == "read_failed"
    assert view["filters"]["releases"] == ["v0.85", "v0.86"]
    assert view["totals"]["people"] == 2
    assert view["consent"] == {"people_off": 1, "workspaces_off": 0}
    only = _view(rows, release="v0.85")
    assert only["totals"]["events"] == 1


def test_the_phone_app_panel_counts_launches_frames_exits_tiers_and_permissions() -> None:
    rows = [
        _row("sx.app_launch", "a", start="cold", ms=2_400, pages="app"),
        _row("sx.app_launch", "b", start="cold", ms=4_000, pages="app"),
        _row("sx.app_frames", "a", frames=1_000, slow=50, frozen=2, p90_ms=20),
        _row("sx.app_frames", "b", frames=1_000, slow=150, frozen=8, p90_ms=40),
        _row("sx.app_exit", "a", reason="low_memory", foreground="no"),
        _row("sx.app_exit", "b", reason="low_memory", foreground="yes"),
        # An older profile is superseded by the newer one for the same person.
        _row("sx.device_profile", "a", minutes_ago=60, android=13, ram_tier="4", maker="xiaomi"),
        _row("sx.device_profile", "a", minutes_ago=5, android=14, ram_tier="4", maker="xiaomi"),
        _row("sx.device_profile", "b", android=14, ram_tier="2", maker="samsung"),
        _row("sx.permission_snapshot", "a", calls="granted", mic="denied", rec_files="granted"),
        _row("sx.permission_snapshot", "b", calls="granted", mic="not_in_build"),
        _row("sx.network_state", "a", transport="cellular", down_tier="1to5"),
    ]
    phone = _view(rows)["phone"]
    assert phone["phones"] == 2
    [launch] = phone["launches"]
    assert (launch["samples"], launch["p50"], launch["p75"]) == (2, 2_400, 4_000)
    assert phone["frames"] == {
        "sessions": 2,
        "slow_share": 0.1,
        "frozen_share": 0.005,
        "p90_ms": 20,
    }
    assert phone["exits"] == [{"reason": "low_memory", "count": 2, "foreground": 1, "people": 2}]
    breakdowns = {item["key"]: item["rows"] for item in phone["breakdowns"]}
    assert breakdowns["android"] == [{"value": "14", "people": 2}]
    assert {"value": "2", "people": 1} in breakdowns["ram_tier"]
    assert breakdowns["transport"] == [{"value": "cellular", "people": 1}]
    permissions = {item["permission"]: item for item in phone["permissions"]}
    assert permissions["calls"]["share"] == 1.0
    assert permissions["mic"]["share"] == 0.0
    assert "folder" not in permissions


@pytest.fixture
def session() -> Iterator[Session]:
    engine = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    model_metadata().create_all(engine)
    made = Session(engine)
    try:
        yield made
    finally:
        made.close()
        engine.dispose()


def _stored(session: Session, *, at: datetime, expires: datetime, policy: str) -> None:
    session.add(
        AnalyticsEvent(
            event_id=str(uuid4()),
            tenant_id=uuid4(),
            actor_person_id=uuid4(),
            subject_person_id=uuid4(),
            event_name="sx.screen_viewed",
            event_version="1.0",
            occurred_at=at,
            trace_id="t",
            release_id="v0.86",
            session_id="s",
            route="/leads",
            payload={"screen": "leads", "nav": "first"},
            consent_status="granted",
            consent_purpose="product_analytics",
            consent_policy_version=NOTICE_VERSION,
            consent_captured_at=at,
            retention_policy_id=policy,
            retention_expires_at=expires,
            created_at=at - timedelta(seconds=1),
        )
    )


def test_reads_only_live_sales_xray_rows_and_counts_who_turned_it_off(session: Session) -> None:
    _stored(
        session,
        at=NOW - timedelta(hours=1),
        expires=NOW + timedelta(days=170),
        policy=RETENTION_POLICY_ID,
    )
    # Expired, another surface's, and outside the window: none of these are read.
    _stored(
        session,
        at=NOW - timedelta(hours=2),
        expires=NOW - timedelta(minutes=1),
        policy=RETENTION_POLICY_ID,
    )
    _stored(
        session,
        at=NOW - timedelta(hours=1),
        expires=NOW + timedelta(days=10),
        policy="learner-telemetry-v1",
    )
    _stored(
        session,
        at=NOW - timedelta(days=9),
        expires=NOW + timedelta(days=100),
        policy=RETENTION_POLICY_ID,
    )
    session.flush()
    read = read_rows(session, since=NOW - timedelta(days=7), until=NOW, now=NOW, limit=5)
    assert len(read.rows) == 1
    assert read.truncated is False
    assert read.rows[0].at == NOW - timedelta(hours=1)

    tenant, person = uuid4(), uuid4()
    for sequence, (resource, enabled) in enumerate(
        [(str(person), False), ("workspace", False), ("workspace", True)], start=1
    ):
        session.add(
            AuditEvent(
                id=uuid4(),
                tenant_id=tenant,
                sequence_no=sequence,
                actor_person_id=None,
                actor_type="system",
                action=PERSON_ACTION,
                resource_type=RESOURCE_TYPE,
                resource_id=resource,
                payload={"enabled": enabled},
                occurred_at=NOW - timedelta(minutes=10 - sequence),
                recorded_at=NOW,
                previous_hash="0" * 64,
                event_hash=f"{sequence:064x}",
            )
        )
    session.flush()
    assert read_consent(session) == {"people_off": 1, "workspaces_off": 0}
