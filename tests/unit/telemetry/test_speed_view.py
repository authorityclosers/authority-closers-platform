"""Admin → Speed and journeys: frames, slow APIs, load and the CPU test, taps by tier and the
journey from Leads, every number with its sample count."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

from ac_platform.telemetry.admin_view import Read, Row
from ac_platform.telemetry.speed_view import MIN_P95, journey, speed, stat

NOW = datetime(2026, 10, 27, 6, 0, tzinfo=UTC)


def _row(
    event: str,
    person: str = "p1",
    *,
    minutes_ago: float = 10,
    release: str = "v1.00",
    **payload: Any,
) -> Row:
    return Row(
        event=event,
        at=NOW - timedelta(minutes=minutes_ago),
        release=release,
        person=person,
        workspace="w1",
        session=f"s-{person}",
        payload=payload,
    )


def _speed(rows: list[Row], app: str | None = None) -> dict[str, Any]:
    return speed(Read(rows=rows), now=NOW, window="7d", app=app, environment="development")


def test_a_stat_says_how_many_and_leaves_out_a_95th_from_few() -> None:
    few = stat([100, 200, 300])
    assert few == {"n": 3, "p50": 200, "p75": 300, "p95": None, "few": True}
    many = stat([float(value) for value in range(1, MIN_P95 + 1)])
    assert many["n"] == MIN_P95
    assert many["p95"] == 19
    assert many["few"] is False
    assert stat([]) == {"n": 0, "p50": None, "p75": None, "p95": None, "few": True}
    assert stat([4.26, 7.04], digits=1)["p75"] == 7.0


def test_frames_by_app_version_and_phone_model() -> None:
    rows = [
        _row("sx.device_profile", "p1", minutes_ago=600, model_label="m1906g7g", app="android"),
        # A newer app start that names the model wins over the daily profile.
        _row("sx.app_start", "p2", start="cold", ms=900, model_label="sm-a155f", app="android"),
        _row("sx.device_profile", "p2", minutes_ago=900, model_label="old-name", app="android"),
        _row(
            "sx.app_frames",
            "p1",
            frames=1000,
            slow=600,
            frozen=10,
            p90_ms=48,
            app_version="1.0.36",
            app="android",
        ),
        _row(
            "sx.app_frames",
            "p1",
            minutes_ago=5,
            frames=500,
            slow=100,
            frozen=0,
            p90_ms=30,
            app_version="1.0.38",
            app="android",
        ),
        _row(
            "sx.app_frames",
            "p2",
            frames=500,
            slow=400,
            frozen=50,
            p90_ms=740,
            app_version="1.0.38",
            app="android",
        ),
    ]
    frames = _speed(rows)["frames"]
    assert frames["all"]["sessions"] == 3
    assert frames["all"]["slow_share"] == round(1100 / 2000, 4)
    assert frames["all"]["frozen_share"] == round(60 / 2000, 4)
    assert frames["all"]["p90_ms"]["n"] == 3
    # Newest version first.
    assert [part["version"] for part in frames["by_version"]] == ["1.0.38", "1.0.36"]
    assert frames["by_version"][0]["slow_share"] == round(500 / 1000, 4)
    models = {part["model"]: part for part in frames["by_model"]}
    assert set(models) == {"m1906g7g", "sm-a155f"}
    assert models["sm-a155f"]["frozen_share"] == 0.1


def test_slow_apis_per_hundred_screen_views_by_release_and_by_endpoint() -> None:
    views = [
        _row("sx.screen_viewed", f"p{n}", release="v0.97", minutes_ago=3000, screen="leads")
        for n in range(4)
    ] + [_row("sx.screen_viewed", "p1", release="v0.98", screen="leads") for _ in range(10)]
    slow = [
        _row(
            "sx.api_slow",
            "p1",
            release="v0.97",
            minutes_ago=3000,
            endpoint="v1_updates",
            status="2xx",
            ms=6600,
        ),
        _row(
            "sx.api_slow",
            "p2",
            release="v0.97",
            minutes_ago=2990,
            endpoint="v1_updates",
            status="5xx",
            ms=5200,
        ),
        # Since 27 Oct: the first byte, apart from the download.
        _row(
            "sx.api_slow",
            "p1",
            release="v0.98",
            endpoint="v1_conversation_acquisition_submissions_id_sourc",
            status="2xx",
            ms=9000,
            wait_ms=1600,
            screen="report",
        ),
    ]
    apis = _speed(views + slow)["apis"]
    assert apis["calls"] == 3
    assert apis["per_100_views"] == round(100 * 3 / 14, 1)
    by_release = {part["release"]: part for part in apis["by_release"]}
    assert by_release["v0.97"]["per_100_views"] == 50.0
    assert by_release["v0.98"]["per_100_views"] == 10.0
    # Newest release first.
    assert apis["by_release"][0]["release"] == "v0.98"
    updates = next(part for part in apis["endpoints"] if part["endpoint"] == "v1_updates")
    assert updates["calls"] == 2
    assert updates["failed"] == 1
    assert updates["wait"]["n"] == 0
    assert updates["total"]["p75"] == 6600
    media = next(part for part in apis["endpoints"] if part["endpoint"].endswith("sourc"))
    assert media["wait"]["p50"] == 1600
    assert media["total"]["p50"] == 9000
    assert media["screens"] == ["report"]


def test_load_by_tier_and_the_cpu_test_by_phone_model() -> None:
    rows = [
        _row("sx.web_vital", "p1", metric="lcp", value=2300, tier="high"),
        _row("sx.web_vital", "p2", metric="lcp", value=4700, tier="mid"),
        _row("sx.web_vital", "p2", metric="inp", value=900, tier="mid"),
        _row("sx.app_start", "p1", start="cold", ms=2000, app="web", cpu_ms=1.2),
        _row(
            "sx.app_start",
            "p2",
            start="cold",
            ms=3200,
            app="android",
            cpu_ms=7.4,
            model_label="redmi-13c",
        ),
        _row(
            "sx.app_start",
            "p3",
            start="warm",
            ms=800,
            app="android",
            cpu_ms=4.0,
            model_label="redmi-13c",
        ),
        _row("sx.app_start", "p4", start="warm", ms=700, app="android"),
        _row("sx.app_launch", "p2", start="cold", ms=1000, pages="app", app="android"),
    ]
    load = _speed(rows)["load"]
    tiers = {part["tier"]: part for part in load["lcp_by_tier"]}
    assert tiers["high"]["p75"] == 2300
    assert tiers["high"]["rating"] == "good"
    assert tiers["mid"]["rating"] == "poor"
    assert tiers["mid"]["n"] == 1
    starts = {(part["app"], part["start"], part["what"]): part for part in load["starts"]}
    assert starts[("android", "cold", "launch")]["p50"] == 1000
    assert starts[("android", "warm", "page")]["n"] == 2
    cpu = load["cpu"]
    assert cpu["tests"] == 3
    assert cpu["bands"] == {"high": 1, "mid": 1, "low": 1}
    phones = {part["model"]: part for part in cpu["by_model"]}
    assert phones["redmi-13c"]["people"] == 2
    assert phones["redmi-13c"]["cpu"]["p50"] == 4.0
    assert phones["redmi-13c"]["tier"] == "mid"
    assert phones["unknown"]["cpu"]["p50"] == 1.2


def test_taps_by_measured_tier_with_their_counts() -> None:
    rows = [
        _row("sx.action_timing", "p1", action="lead_open", ms=300, tier="high"),
        _row("sx.action_timing", "p2", action="lead_open", ms=1400, tier="low"),
        _row("sx.action_timing", "p2", action="lead_open", ms=900, tier="low"),
        _row("sx.action_timing", "p2", action="search", ms=900, tier="low"),
    ]
    taps = _speed(rows)["taps"]
    assert [part["action"] for part in taps] == ["lead_open"]
    tiers = {part["tier"]: part for part in taps[0]["by_tier"]}
    assert tiers["low"]["n"] == 2
    assert tiers["low"]["slow_share"] == 0.5
    assert tiers["low"]["few"] is True
    assert taps[0]["slow_ms"] == 1_000


def test_the_journey_starts_at_leads_until_a_sign_in_is_recorded() -> None:
    rows = [
        _row("sx.screen_viewed", "p1", screen="leads"),
        _row("sx.screen_viewed", "p2", screen="leads"),
        _row("sx.screen_viewed", "p3", screen="calls"),
        _row("sx.action_timing", "p1", action="lead_open", ms=200),
        _row("sx.action_timing", "p1", action="call_start", ms=200),
        _row("sx.upload_started", "p1", size_band="under_5mb", format="m4a"),
        _row("sx.upload_finished", "p1", outcome="saved", seconds=4),
        _row("sx.report_opened", "p1", view="tabs"),
        # Opened a report without opening Leads: not on this journey.
        _row("sx.report_opened", "p3", view="tabs"),
    ]
    steps = journey(rows)["steps"]
    assert [step["key"] for step in steps] == ["leads", "lead", "call", "upload", "saved", "report"]
    assert [step["people"] for step in steps] == [2, 1, 1, 1, 1, 1]
    assert steps[1]["of_first"] == 0.5
    assert steps[1]["of_previous"] == 0.5
    assert steps[0]["of_previous"] is None
    signed = journey([*rows, _row("sx.sign_in", "p1", method="google")])
    assert signed["from"] == "signed_in"
    assert [step["people"] for step in signed["steps"]][:2] == [1, 1]


def test_the_app_filter_and_the_page_frame() -> None:
    rows = [
        _row("sx.screen_viewed", "p1", screen="leads", app="web"),
        _row("sx.screen_viewed", "p2", screen="leads", app="android"),
    ]
    view = _speed(rows, app="android")
    assert view["totals"]["people"] == 1
    assert view["app"] == "android"
    assert view["schema"] == "ac.sales-xray.speed-journeys/1"
    assert view["since"] == (NOW - timedelta(days=7)).isoformat()
    empty = _speed([])
    assert empty["frames"]["all"]["slow_share"] is None
    assert empty["apis"]["per_100_views"] is None
    assert empty["journey"]["steps"][0]["people"] == 0
