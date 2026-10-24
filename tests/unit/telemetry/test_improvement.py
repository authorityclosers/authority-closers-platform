"""The improvement loop: devices, release comparison, the release gate and what to fix next."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

from ac_platform.telemetry.admin_view import Filters, Read, Row
from ac_platform.telemetry.improvement import compare, devices, fix_next, gate

NOW = datetime(2026, 10, 24, 6, 0, tzinfo=UTC)


def _row(
    event: str,
    person: str = "p1",
    *,
    minutes_ago: float = 10,
    release: str = "v2",
    session: str | None = None,
    **payload: Any,
) -> Row:
    return Row(
        event=event,
        at=NOW - timedelta(minutes=minutes_ago),
        release=release,
        person=person,
        workspace="w1",
        session=session or f"s-{person}",
        payload=payload,
    )


def _tap(person: str, ms: int, action: str = "lead_open", **payload: Any) -> Row:
    fields: dict[str, Any] = {"app": "android", "device": "phone", "tier": "mid", "screen": "leads"}
    fields.update(payload)
    return _row("sx.action_timing", person, action=action, ms=ms, result="settled", **fields)


def test_devices_are_phone_models_or_classes_with_speed_issues_and_the_slowest_tenth() -> None:
    rows = [
        _row(
            "sx.device_profile",
            "a",
            android=13,
            maker="xiaomi",
            model_label="m1906g7g",
            webview="130",
            ram_tier="4",
            app="android",
            app_version="1.0.26",
        ),
        _row(
            "sx.device_profile",
            "b",
            android=14,
            maker="samsung",
            model_label="sm-a515f",
            ram_tier="6",
            app="android",
        ),
        *[_tap("a", 2_000, app_version="1.0.26", net="4g") for _ in range(5)],
        *[_tap("b", 400) for _ in range(5)],
        *[_tap("c", 300, app="web", device="desktop", tier="high") for _ in range(5)],
        # An older app build sends no profile: its device is a class.
        *[_tap("d", 700) for _ in range(2)],
        _row("sx.js_error", "a", app="android", error="typeerror", where="0a1b2c3d"),
        _row("sx.app_exit", "a", app="android", reason="crash", foreground="yes"),
        _row("sx.tap_issue", "b", app="android", kind="rage", target="row", screen="leads"),
    ]
    view = devices(Read(rows=rows), now=NOW, window="7d", filters=Filters())
    groups = {item["key"]: item for item in view["groups"]}
    assert set(groups) == {
        "model:xiaomi:m1906g7g",
        "model:samsung:sm-a515f",
        "class:web:desktop:high",
        "class:android:phone:mid",
    }
    xiaomi = groups["model:xiaomi:m1906g7g"]
    assert (xiaomi["maker"], xiaomi["model"], xiaomi["people"]) == ("xiaomi", "m1906g7g", 1)
    assert xiaomi["android"] == [{"value": "13", "people": 1}]
    assert xiaomi["ram"] == [{"value": "4", "people": 1}]
    assert xiaomi["app_versions"] == [{"value": "1.0.26", "people": 1}]
    assert xiaomi["networks"] == [{"value": "4g", "people": 1}]
    assert xiaomi["actions"]["lead_open"]["p75"] == 2_000
    assert xiaomi["actions"]["lead_open"]["slow_share"] == 1.0
    assert (xiaomi["script_errors"], xiaomi["crashes"], xiaomi["rage_taps"]) == (1, 1, 0)
    assert xiaomi["speed_index"] == 2.0
    # The slowest tenth of the 17 lead_open taps is two taps, both the Xiaomi's.
    assert (xiaomi["slow_tail_taps"], xiaomi["slow_tail_share"]) == (2, 0.4)
    assert groups["model:samsung:sm-a515f"]["rage_taps"] == 1
    # The device with two taps is too few to rank.
    assert groups["class:android:phone:mid"]["speed_index"] is None
    assert view["totals"] == {
        "devices": 4,
        "ranked": 3,
        "models": 2,
        "classes": 2,
        "slow_devices": 1,
        "slow_share": 0.3333,
    }
    [slowest] = view["slowest"]["devices"]
    assert (slowest["key"], slowest["speed_index"], slowest["android"], slowest["ram"]) == (
        "model:xiaomi:m1906g7g",
        2.0,
        13,
        "4",
    )
    assert slowest["app_version"] == "1.0.26"
    assert "person" not in str(slowest)
    # A filter keeps the app's rows only.
    android = devices(Read(rows=rows), now=NOW, window="7d", filters=Filters(app="web"))
    assert [item["key"] for item in android["groups"]] == ["class:web:desktop:high"]


def _release(name: str, ms: int, minutes_ago: float, people: int = 20) -> list[Row]:
    return [
        _tap(f"{name}-{index}", ms, release=name, minutes_ago=minutes_ago)
        for index in range(people)
    ]


def test_a_release_is_compared_with_the_one_before_and_the_gate_blocks_a_slower_key_action() -> (
    None
):
    rows = [*_release("v1", 800, minutes_ago=600), *_release("v2", 1_200, minutes_ago=60)]
    result = compare(Read(rows=rows), now=NOW)
    assert (result["head"], result["base"]) == ("v2", "v1")
    speed = {item["key"]: item for item in result["metrics"]}
    lead = speed["speed:lead_open"]
    assert (lead["base"], lead["head"], lead["change"]) == (800, 1_200, 0.5)
    assert (lead["verdict"], lead["regression"]) == ("worse", True)
    assert speed["speed:tab_switch"]["verdict"] == "too_few"
    assert [item["key"] for item in result["regressions"]] == ["speed:lead_open"]

    verdict = gate(Read(rows=rows), now=NOW, environment="production", release="v2")
    assert (verdict["verdict"], verdict["baseline"], verdict["blocks_promotion"]) == (
        "block",
        "v1",
        True,
    )
    assert verdict["reasons"] == ["Open a lead: 75th percentile 800 ms → 1200 ms (20 → 20 taps)"]
    # The first release has nothing before it, and an unknown one has no data: never a block.
    assert gate(Read(rows=rows), now=NOW, environment="production", release="v1")["verdict"] == (
        "not_enough_data"
    )
    assert gate(Read(rows=rows), now=NOW, environment="production", release="v9")["verdict"] == (
        "not_enough_data"
    )
    # 900 ms is slower, but under the threshold: it passes.
    steady = [*_release("v1", 800, minutes_ago=600), *_release("v2", 900, minutes_ago=60)]
    passed = gate(Read(rows=steady), now=NOW, environment="production", release="v2")
    assert (passed["verdict"], passed["reasons"]) == ("pass", [])
    # Too few taps never block.
    thin = [*_release("v1", 800, 600, people=5), *_release("v2", 3_000, 60, people=5)]
    assert gate(Read(rows=thin), now=NOW, environment="production", release="v2")["verdict"] == (
        "not_enough_data"
    )


def test_what_to_fix_next_ranks_by_people_times_severity_with_evidence_and_owner() -> None:
    current = [
        # Opening a lead is slow for three people (serious: a key action).
        *[_tap(person, 2_400) for person in ("a", "b", "c") for _ in range(2)],
        *[_tap("d", 300) for _ in range(4)],
        # A script error from our code for two people.
        *[
            _row(
                "sx.js_error",
                person,
                error="typeerror",
                where="0a1b2c3d",
                source="app",
                screen="report",
            )
            for person in ("a", "b")
        ],
        # A browser extension's error is not ours.
        _row("sx.js_error", "c", error="error", where="ffff0000", source="extension"),
        # The Android app crashed once (critical).
        _row("sx.app_exit", "a", reason="crash", foreground="yes"),
        # Three rage taps by one person.
        *[
            _row("sx.tap_issue", "b", kind="rage", screen="chats", target="button")
            for _ in range(3)
        ],
    ]
    before = [
        *[_tap(person, 2_000, minutes_ago=8 * 24 * 60) for person in ("a", "b") for _ in range(5)],
        # Last week's dead taps on the report are gone this week.
        *[
            _row(
                "sx.tap_issue",
                "c",
                minutes_ago=8 * 24 * 60,
                kind="dead",
                screen="report",
                target="text",
            )
            for _ in range(4)
        ],
    ]
    result = fix_next(current, before, now=NOW, window="7d", environment="production")
    assert [item["key"] for item in result["items"]] == [
        "slow:lead_open:leads",
        "error:typeerror:0a1b2c3d",
        "exit:crash",
        "tap:rage:chats:button",
    ]
    slow = result["items"][0]
    assert (slow["people"], slow["severity"], slow["score"]) == (3, 3, 9)
    assert slow["owner"] == "Lead OS"
    assert slow["title"] == "Open a lead is slow on Leads"
    assert (slow["now"], slow["before"], slow["new"]) == (2_400, 2_000, False)
    assert slow["evidence"]["slow_share"] == 0.6
    assert slow["by_release"] == [{"release": "v2", "value": 2_400}]
    assert "Suggested owner: Lead OS" in slow["task"]
    assert "slow:lead_open:leads" in slow["task"]
    error = result["items"][1]
    assert (error["owner"], error["new"]) == ("Report (Brain 4.0)", True)
    assert result["items"][2]["owner"] == "Android app"
    [gone] = result["improved"]
    assert (gone["key"], gone["gone"], gone["people_before"]) == ("tap:dead:report:text", True, 1)
