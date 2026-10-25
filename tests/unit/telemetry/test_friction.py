"""The weekly friction report: screens, flows, permission prompts, workspace switching and
the ranked findings, over fictional events (no person or workspace is ever named)."""

from __future__ import annotations

import json
from datetime import UTC, date, datetime, timedelta
from typing import Any

from ac_platform.telemetry import friction
from ac_platform.telemetry.admin_view import Row

# Monday 19 Oct 2026, 10:00 IST.
WEEK = date(2026, 10, 19)
T0 = datetime(2026, 10, 19, 4, 30, tzinfo=UTC)
NOW = datetime(2026, 10, 26, 6, 0, tzinfo=UTC)
PERSONAL = "workspace-personal-0001"
ORG = "workspace-org-0002"


def row(
    event: str,
    seconds: float,
    person: str = "person-a",
    *,
    session: str | None = None,
    workspace: str = ORG,
    **payload: Any,
) -> Row:
    return Row(
        event=event,
        at=T0 + timedelta(seconds=seconds),
        release="v0.89",
        person=person,
        workspace=workspace,
        session=session or f"session-{person}",
        payload={"app": "android", "device": "phone", **payload},
    )


def view(seconds: float, screen: str, source: str, nav: str, seen: int | None, **kw: Any) -> Row:
    extra: dict[str, Any] = {"seen_ms": seen} if seen is not None else {}
    return row(
        "sx.screen_viewed", seconds, screen=screen, nav=nav, **{"from": source}, **extra, **kw
    )


def report(rows: list[Row], before: list[Row] | None = None, **kw: Any) -> dict[str, Any]:
    return friction.report(rows, before or [], week=WEEK, now=NOW, environment="test", **kw)


def test_a_week_is_monday_to_monday_in_india() -> None:
    start, end = friction.week_window(date(2026, 10, 22))
    assert start == datetime(2026, 10, 18, 18, 30, tzinfo=UTC)
    assert end == datetime(2026, 10, 25, 18, 30, tzinfo=UTC)
    # Sunday night in India is still the week before.
    assert friction.last_full_week(datetime(2026, 10, 25, 18, 0, tzinfo=UTC)) == date(2026, 10, 12)
    assert friction.last_full_week(datetime(2026, 10, 25, 19, 0, tzinfo=UTC)) == date(2026, 10, 19)


def test_fewer_than_three_people_are_never_shown_as_a_number() -> None:
    assert [friction.people_count(n) for n in (0, 1, 2, 3, 40)] == [0, "<3", "<3", 3, 40]


def test_screens_count_dwell_quick_backs_loops_exits_and_taps() -> None:
    rows: list[Row] = []
    for index in range(10):
        person, base = f"p{index}", index * 1000
        rows += [
            view(base, "leads", "none", "first", None, person=person),
            view(base + 2, "lead", "leads", "push", 2_000, person=person),
            # In and straight out again: a quick back from the lead.
            view(base + 3, "leads", "lead", "back", 1_000, person=person),
            # Leads and Calls, back and forth.
            view(base + 10, "calls", "leads", "push", 7_000, person=person),
            view(base + 20, "leads", "calls", "back", 10_000, person=person),
            view(base + 30, "calls", "leads", "push", 10_000, person=person),
            row(
                "sx.tap_issue",
                base + 31,
                person,
                kind="dead",
                target="text",
                screen="calls",
                zone="r1c3",
                element="calls-list.duration",
            ),
            row("sx.screen_hidden", base + 40, person, screen="calls", kind="exit", seen_ms=9_000),
        ]
    data = report(rows)
    by_screen = {item["screen"]: item for item in data["screens"]}
    lead = by_screen["lead"]
    assert (lead["views"], lead["quick_back_share"]) == (10, 1.0)
    assert by_screen["calls"]["exit_share"] == 0.5
    assert by_screen["calls"]["dead_per_100"] == 50.0
    assert by_screen["calls"]["seen_p50_ms"] == 9_000
    [loop] = data["loops"]
    assert (loop["screens"], loop["count"], loop["people"]) == (["calls", "leads"], 10, 10)
    kinds = {item["kind"] for item in data["findings"]}
    assert {"quick_back", "loop", "dead_tap"} <= kinds
    dead = next(item for item in data["findings"] if item["kind"] == "dead_tap")
    assert dead["key"] == "dead:calls:calls-list.duration"
    assert dead["evidence"]["zones"] == ["r1c3"]
    assert "`calls-list.duration`" in dead["title"]


def _run(person: str, *steps: tuple[str, str], seconds: float = 0, **extra: Any) -> list[Row]:
    return [
        row(
            "sx.flow",
            seconds + index,
            person,
            flow=extra.get("flow", "onboarding"),
            outcome=o,
            **({"step": s} if s else {}),
            **{k: v for k, v in extra.items() if k != "flow"},
        )
        for index, (o, s) in enumerate(steps)
    ]


def test_flows_say_how_far_people_get_and_where_they_stop() -> None:
    rows: list[Row] = []
    for person in ("p1", "p2", "p3"):
        rows += _run(person, ("start", "start"), ("step", "name"), ("abandon", "name"))
    rows += _run(
        "p4",
        ("start", "start"),
        ("step", "name"),
        ("step", "business"),
        ("step", "team"),
        ("step", "first"),
        ("done", "first"),
    )
    rows[-1] = Row(**{**rows[-1].__dict__, "payload": {**rows[-1].payload, "ms": 95_000}})
    # Started and never ended: the app was closed.
    rows += _run("p5", ("start", "start"))
    # "How did it go?": Save refused three times for something missing, then saved.
    for person in ("p1", "p2", "p3"):
        rows += _run(
            person,
            ("start", "talk"),
            ("blocked", "stage"),
            ("done", "save"),
            seconds=500,
            flow="log_result",
        )
    data = report(rows)
    onboarding = next(flow for flow in data["flows"] if flow["flow"] == "onboarding")
    assert (onboarding["started"], onboarding["done"], onboarding["abandoned"]) == (5, 1, 3)
    assert onboarding["no_end"] == 1
    assert onboarding["done_p50_ms"] == 95_000
    assert onboarding["worst_step"] == "name"
    name = next(step for step in onboarding["steps"] if step["step"] == "name")
    assert (name["reached"], name["quit"]) == (4, 3)
    keys = [item["key"] for item in data["findings"]]
    assert "flow_quit:onboarding:name" in keys
    assert "flow_blocked:log_result:stage" in keys
    quit_ = next(item for item in data["findings"] if item["key"] == "flow_quit:onboarding:name")
    assert (quit_["severity"], quit_["people"], quit_["owner"]) == (
        4,
        3,
        "Builder (sign-in and first-run setup)",
    )


def test_permission_prompts_are_summed_and_refusals_become_findings() -> None:
    rows = [
        row(
            "sx.permission_prompt",
            index,
            f"p{index}",
            permission="calls",
            outcome=outcome,
            via="prompt",
            ms=4_000,
        )
        for index, outcome in enumerate(("denied", "blocked", "denied", "granted", "granted"))
    ]
    data = report(rows)
    [calls] = data["permissions"]
    assert (calls["asked"], calls["granted"], calls["denied"], calls["blocked"]) == (5, 2, 2, 1)
    assert calls["granted_share"] == 0.4 and calls["answer_p50_ms"] == 4_000
    finding = next(item for item in data["findings"] if item["kind"] == "permission")
    assert (finding["key"], finding["severity"], finding["people"]) == (
        "permission_prompt:calls",
        3,
        3,
    )


def test_workspace_switching_reads_bounces_ping_pong_and_early_switches() -> None:
    rows: list[Row] = []
    for index, person in enumerate(("p1", "p2", "p3")):
        base = index * 3600
        rows += [
            row("sx.app_start", base, person, workspace=PERSONAL),
            # Switched within a minute of opening, then straight back, then again.
            row("sx.screen_viewed", base + 30, person, workspace=ORG, screen="home", nav="first"),
            row(
                "sx.screen_viewed",
                base + 90,
                person,
                workspace=PERSONAL,
                screen="home",
                nav="first",
            ),
            row("sx.screen_viewed", base + 200, person, workspace=ORG, screen="home", nav="first"),
            row("sx.feature_used", base + 400, person, workspace=ORG, feature="workspace_menu"),
        ]
    data = report(rows, kinds={PERSONAL: "personal"})
    switching = data["workspaces"]
    # Personal → org → Personal → org: the second and third switches each went straight back.
    assert (switching["switches"], switching["bounces"], switching["early_switches"]) == (9, 6, 3)
    assert switching["ping_pong_people"] == 3
    assert switching["directions"] == {"personal_to_organisation": 6, "organisation_to_personal": 3}
    assert (switching["menu_opens"], switching["menu_left"]) == (3, 3)
    keys = {item["key"] for item in data["findings"]}
    assert {"workspace:bounce", "workspace:early"} <= keys


def test_findings_need_three_people_rank_by_people_times_severity_and_compare_weeks() -> None:
    def rage(person: str, seconds: float) -> Row:
        return row(
            "sx.tap_issue",
            seconds,
            person,
            kind="rage",
            target="button",
            screen="lead",
            element="lead-sheet.save",
        )

    def dead(person: str, seconds: float) -> Row:
        return row(
            "sx.tap_issue",
            seconds,
            person,
            kind="dead",
            target="text",
            screen="home",
            element="home.stat",
        )

    two = [rage("p1", 1), rage("p2", 2)]
    assert report(two)["findings"] == []
    rows = [rage(f"p{n}", n) for n in range(3)] + [dead(f"p{n}", 50 + n) for n in range(5)]
    before = [
        Row(**{**item.__dict__, "at": item.at - timedelta(days=7)})
        for item in [dead(f"p{n}", n) for n in range(4)]
        + [row("sx.error_shown", n, f"p{n}", surface="leads", code="save_failed") for n in range(3)]
    ]
    data = report(rows, before)
    first, second = data["findings"][:2]
    # 5 people × 2 (dead) beats 3 people × 3 (rage).
    assert (first["key"], first["score"], first["new"], first["people_before"]) == (
        "dead:home:home.stat",
        10,
        False,
        4,
    )
    assert (second["key"], second["score"], second["new"]) == ("rage:lead:lead-sheet.save", 9, True)
    assert data["gone"] == [
        {
            "key": "error_shown:leads:save_failed",
            "title": "People see the error “save failed” on leads",
            "people_before": 3,
        }
    ]


def _all_strings(value: Any) -> str:
    return json.dumps(value, default=str)


def test_nothing_names_a_person_or_workspace_and_the_markdown_reads_whole() -> None:
    rows: list[Row] = []
    for person in ("person-secret-1", "person-secret-2", "person-secret-3"):
        rows += [
            view(0, "leads", "none", "first", None, person=person, session=f"{person}-s"),
            row(
                "sx.tap_issue",
                1,
                person,
                session=f"{person}-s",
                kind="rage",
                target="row",
                screen="leads",
                element="leads-table.row",
                zone="r2c2",
            ),
            row("sx.app_start", 900, person, session=f"{person}-s", workspace=PERSONAL),
        ]
    data = report(rows, kinds={PERSONAL: "personal"})
    text = friction.to_markdown(data)
    for secret in ("person-secret", PERSONAL, ORG):
        assert secret not in _all_strings(data), secret
        assert secret not in text, secret
    for heading in (
        "# Sales X-Ray friction report: week of 19 Oct 2026",
        "## What to fix first",
        "## Flows: where people stop",
        "## Permission prompts (phone setup)",
        "## Workspace switching",
        "## Screens by friction",
        "## How this is worked out",
    ):
        assert heading in text
    assert "1. **Repeated taps on `leads-table.row` on Leads**" in text
    assert data["complete"] is True


def test_an_empty_week_still_reads() -> None:
    data = report([])
    assert data["findings"] == [] and data["flows"] == [] and data["coverage"]["events"] == 0
    assert "Nothing reached the bar this week" in friction.to_markdown(data)


def test_the_report_is_plain_json() -> None:
    data = report(_run("p1", ("start", "start"), ("abandon", "start")))
    assert json.loads(json.dumps(data))["flows"][0]["abandoned"] == 1
