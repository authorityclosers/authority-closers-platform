"""Admin → Sellers → What happened: one person's days, and the line naming the newest gap."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID, uuid4

from ac_platform.telemetry.admin_view import Row
from ac_platform.telemetry.seller_timeline import (
    Inputs,
    LeadRow,
    Member,
    Phone,
    Seller,
    SignIn,
    build,
    window_start,
)

# 17:30 in India on 24 Oct 2026; "23 Oct" below is the India day before.
NOW = datetime(2026, 10, 24, 12, 0, tzinfo=UTC)
DAY_23 = datetime(2026, 10, 23, 6, 0, tzinfo=UTC)
ORG = uuid4()
PERSON = uuid4()
OLD_PHONE = "aaaaaaaa-0000-4000-8000-000000000001"
NEW_PHONE = "bbbbbbbb-0000-4000-8000-000000000002"


def _inputs(**parts: Any) -> Inputs:
    return Inputs(
        seller=Seller(
            id=PERSON,
            name="Fictional Seller",
            email="seller@example.test",
            status="active",
            created_at=NOW - timedelta(days=40),
            terms_version="2026-10-01",
            terms_at=NOW - timedelta(days=40),
        ),
        members=[
            Member(
                tenant_id=ORG,
                name="Fictional Realty",
                kind="organisation",
                role="member",
                status="active",
                joined_at=NOW - timedelta(days=40),
                ended_at=None,
                analytics="on",
                analytics_changed_at=None,
            )
        ],
        **parts,
    )


def _call(at: datetime, **data: Any) -> LeadRow:
    return LeadRow(kind="call", at=at, tenant_id=ORG, data=data)


def _lead(kind: str, at: datetime) -> LeadRow:
    return LeadRow(kind=kind, at=at, tenant_id=ORG, data={})


def _row(event: str, at: datetime, workspace: UUID = ORG, **payload: Any) -> Row:
    return Row(
        event=event,
        at=at,
        release="v0.88",
        person=str(PERSON),
        workspace=str(workspace),
        session="s1",
        payload={"app": "android", "device": "phone", "app_version": "1.0.26", **payload},
    )


def test_calls_whose_results_stayed_on_the_phone_lead_the_summary() -> None:
    calls = [
        _call(DAY_23 + timedelta(minutes=index), via="phone", device_id=OLD_PHONE)
        for index in range(10)
    ] + [_call(DAY_23 + timedelta(hours=1, minutes=index)) for index in range(4)]
    saved = [
        _row(
            "sx.action_timing",
            DAY_23 + timedelta(hours=2, minutes=index),
            action="outcome_save",
            ms=300,
            result="settled",
        )
        for index in range(9)
    ]
    body = build(
        _inputs(
            sign_ins=[
                SignIn(
                    at=DAY_23 - timedelta(hours=2, minutes=30),
                    tenant_id=ORG,
                    last_seen_at=DAY_23 + timedelta(hours=3),
                    ended_at=None,
                )
            ],
            lead_events=calls,
            telemetry=[
                *saved,
                _row("sx.writes_waiting", DAY_23 + timedelta(hours=3), waiting=9, oldest_min=120),
                _row(
                    "sx.device_profile",
                    DAY_23,
                    store="play",
                    model_label="Fictional phone",
                    maker="fictional",
                    android=13,
                ),
            ],
            phones=[
                Phone(
                    tenant_id=ORG,
                    install="aaaaaaaa",
                    app_version="1.0.26",
                    family="xiaomi",
                    reported_at=DAY_23,
                    synced_at=DAY_23,
                )
            ],
        ),
        now=NOW,
        days=14,
    )

    assert body["schema"] == "ac.admin.seller-timeline/1"
    assert body["summary"] == {
        "tone": "bad",
        "words": "23 Oct: 14 calls, 0 results saved — "
        "the phone saved 9 results that never reached the server",
    }
    [day] = body["days"]
    assert day["day"] == "2026-10-23" and day["label"] == "23 Oct"
    assert day["server"]["calls_app"] == 4 and day["server"]["calls_logged"] == 10
    assert day["server"]["results"] == 0
    assert day["phone"]["results_saved"] == 9 and day["phone"]["waiting"] == 9
    assert [flag["words"] for flag in day["flags"]] == [
        "9 results saved on the phone, 0 reached the server",
        "The phone held 9 unsent changes (oldest 2 hours)",
    ]
    assert day["workspaces"] == ["Fictional Realty"]
    assert day["moments"][0] == {
        "at": (DAY_23 - timedelta(hours=2, minutes=30)).isoformat(),
        "time": "09:00",
        "words": "Signed in, opened Fictional Realty",
    }
    assert "Phone reported 9 changes waiting" in [item["words"] for item in day["moments"]]
    [device] = body["devices"]
    assert (device["app"], device["store"], device["model"], device["version"]) == (
        "android",
        "Play",
        "Fictional phone",
        "1.0.26",
    )
    assert body["phones"][0]["workspace"] == "Fictional Realty"
    assert body["workspaces"][0]["sign_ins"] == 1
    assert body["totals"]["days_with_gaps"] == 1


def test_a_clean_window_says_so_with_its_counts() -> None:
    day = DAY_23 - timedelta(days=1)
    body = build(
        _inputs(
            lead_events=[_call(day), _call(day), _lead("result", day), _lead("result", day)],
            telemetry=[
                _row("sx.action_timing", day, action="outcome_save", ms=200, result="settled"),
                _row("sx.action_timing", day, action="outcome_save", ms=200, result="settled"),
            ],
        ),
        now=NOW,
        days=14,
    )
    assert body["summary"] == {
        "tone": "good",
        "words": "No gaps in the last 14 days: 2 calls, 2 results and 0 stage moves "
        "reached the server",
    }
    assert body["days"][0]["flags"] == []


def test_installs_refusals_crashes_and_what_is_not_a_call() -> None:
    first = DAY_23 - timedelta(days=3)
    body = build(
        _inputs(
            lead_events=[
                _call(first, via="phone", device_id=OLD_PHONE),
                _call(DAY_23, via="phone", device_id=NEW_PHONE),
                _call(DAY_23, submission_id="s", recording=True),
                _call(DAY_23, simulated=True),
                _lead("result", DAY_23),
            ],
            telemetry=[
                _row("sx.writes_waiting", DAY_23, waiting=2, refused=2),
                _row("sx.app_exit", DAY_23 + timedelta(minutes=5), reason="crash"),
                _row("sx.error_shown", DAY_23, surface="leads", code="save_failed"),
            ],
        ),
        now=NOW,
        days=14,
    )
    newest, oldest = body["days"]
    assert newest["server"] == {
        "calls_app": 0,
        "calls_logged": 1,
        "connected": 0,
        "test_calls": 1,
        "results": 1,
        "notes": 0,
        "stage_moves": 0,
    }
    words = [flag["words"] for flag in newest["flags"]]
    assert "2 changes refused when the phone sent them again" in words
    assert "The app crashed or froze 1 time" in words
    assert "1 error shown (leads: save_failed)" in words
    assert "A new install or a new phone started logging calls" in words
    moments = [item["words"] for item in newest["moments"]]
    assert "New install bbbbbbbb logged its first call" in moments
    assert "App reported it last closed: crash" in moments
    assert oldest["flags"] == [] or all("install" not in flag["words"] for flag in oldest["flags"])
    assert [item["install"] for item in body["installs"]] == ["bbbbbbbb", "aaaaaaaa"]
    assert body["summary"]["tone"] == "bad"
    assert body["summary"]["words"].startswith("23 Oct: 1 call, 1 result saved — the phone held 2")


def test_nothing_in_the_window_and_nothing_before_it() -> None:
    before = window_start(NOW, 7) - timedelta(minutes=1)
    body = build(
        _inputs(lead_events=[_call(before)], telemetry=[_row("sx.js_error", before)]),
        now=NOW,
        days=7,
    )
    assert body["summary"] == {"tone": "neutral", "words": "No activity in the last 7 days"}
    assert body["days"] == [] and body["devices"] == []
    assert window_start(NOW, 7) == datetime(2026, 10, 17, 18, 30, tzinfo=UTC)


def test_calls_without_results_say_whether_the_phone_sent_anything() -> None:
    body = build(_inputs(lead_events=[_call(DAY_23)]), now=NOW, days=14)
    assert body["summary"]["words"] == (
        "23 Oct: 1 call, 0 results saved — the phone sent no usage data that day"
    )
    assert body["days"][0]["phone"] is None
