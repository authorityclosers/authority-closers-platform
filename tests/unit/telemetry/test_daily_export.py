"""The daily export for the cost optimiser: analysed calls' cost joined to how they were used."""

from __future__ import annotations

import os
from datetime import UTC, date, datetime, timedelta
from typing import Any

from ac_platform.conversation_intelligence.cost_metrics import Call, Export, Step, version_id
from ac_platform.telemetry.admin_view import Row
from ac_platform.telemetry.daily_export import daily_export, length_band, workspace_ref
from ac_platform.telemetry.sales_xray import call_ref
from ac_platform.usage_people.pseudonyms import pads

DAY = date(2026, 10, 23)
# 10:00 India time on the day.
ANALYSED = datetime(2026, 10, 23, 4, 30, tzinfo=UTC)
TENANT = "11111111-1111-4111-8111-111111111111"
VERSION = ("one-pass-v1", None, None)


def _call(call_id: str, minutes: float, *, report: bool) -> tuple[Call, list[Step]]:
    call = Call(
        environment="development",
        id=call_id,
        company=TENANT,
        at=ANALYSED - timedelta(minutes=5),
        kind="real",
        audio_ms=int(minutes * 60_000),
        billed_s=0,
        plan=None,
        accepted_at=None,
        delivered_at=None,
        report_at=ANALYSED + timedelta(minutes=2) if report else None,
        version=VERSION,  # type: ignore[arg-type]
        gold=(0, 0, 0),
        person="p_0123456789abcdef",
    )

    def step(stage: str, paise: int) -> Step:
        return Step(
            environment="development",
            call=call_id,
            company=TENANT,
            stage=stage,
            provider="google",
            model="m",
            status="succeeded",
            attempts=1,
            input_tokens=0,
            output_tokens=0,
            audio_ms=int(minutes * 60_000),
            elapsed_ms=1_000,
            paise=paise,
            at=ANALYSED,
        )

    return call, [step("C2", 40), step("C5", 120)]


def _row(event: str, at: datetime, **payload: Any) -> Row:
    return Row(
        event=event,
        at=at,
        release="v0.86",
        person="p1",
        workspace=TENANT,
        session="s1",
        payload=payload,
    )


def test_each_analysed_call_has_its_cost_and_use_and_unopened_calls_stay() -> None:
    inner, outer = pads(os.urandom(32))
    opened, opened_steps = _call("aaaaaaaa-1111-4111-8111-111111111111", 4.5, report=True)
    never, never_steps = _call("bbbbbbbb-2222-4222-8222-222222222222", 0.5, report=False)
    export = Export(
        environment="development",
        generated_at=ANALYSED,
        migration=None,
        window_days=7,
        calls=[opened, never],
        steps=opened_steps + never_steps,
    )
    ref = call_ref(inner, outer, opened.id)
    later = ANALYSED + timedelta(minutes=12)
    rows = [
        _row("sx.report_opened", later, view="report", call_ref=ref),
        _row("sx.report_opened", later + timedelta(hours=30), view="report", call_ref=ref),
        _row(
            "sx.section_read",
            later,
            section="analysis",
            read_band="5_30s",
            dwell_ms=12_000,
            look="brain4",
            call_ref=ref,
        ),
        _row(
            "sx.section_read",
            later,
            section="analysis",
            read_band="30_120s",
            dwell_ms=40_000,
            look="brain4",
            call_ref=ref,
        ),
        _row(
            "sx.section_action",
            later,
            section="analysis",
            action="expand",
            skill="d07",
            call_ref=ref,
        ),
        _row(
            "sx.on_demand_requested", later, section="transcript", level="data_only", call_ref=ref
        ),
        _row("sx.full_report_requested", later, surface="report", level="auto", call_ref=ref),
    ]
    out = daily_export(
        day=DAY,
        rows=rows,
        export=export,
        pads=(inner, outer),
        environment="development",
        now=ANALYSED + timedelta(days=2),
    )
    assert out["schema"] == "ac.sales-xray.telemetry-daily/1"
    assert out["ai_level_known"] is False
    by_ref = {item["call_ref"]: item for item in out["calls"]}
    first = by_ref[ref]
    assert first["workspace_ref"] == workspace_ref(inner, outer, TENANT)
    assert first["seller"] == "p_0123456789abcdef"
    assert first["length_band"] == "3_6"
    assert first["version"] == version_id(VERSION)  # type: ignore[arg-type]
    assert (first["cost_paise"], first["c5_paise"]) == (160, 120)
    assert first["opened"] == 2
    assert first["look"] == "brain4"
    assert first["first_open_seconds"] == 600
    assert first["opened_within_24h"] is True
    assert first["full_report_requested"] is True
    assert first["on_demand"] == [{"section": "transcript", "level": "data_only"}]
    [analysis] = first["sections"]
    assert analysis == {
        "section": "analysis",
        "max_band": "30_120s",
        "dwell_ms": 52_000,
        "actions": {"expand": 1},
    }
    unopened = by_ref[call_ref(inner, outer, never.id)]
    assert unopened["opened"] == 0
    assert unopened["length_band"] == "under_1"
    assert unopened["first_open_seconds"] is None
    assert unopened["full_report"] is False
    [workspace] = out["workspaces"]
    assert (workspace["analysed"], workspace["opened"], workspace["opened_within_24h"]) == (
        2,
        1,
        1,
    )
    assert {"section": "analysis", "read_band": "30_120s", "look": "brain4", "count": 1} in (
        workspace["reads"]
    )
    assert workspace["full_report"] == [{"surface": "report", "level": "auto", "count": 1}]
    # Nothing in it names a call, a workspace or a person.
    text = repr(out)
    for raw in (opened.id, never.id, TENANT):
        assert raw not in text


def test_lengths_and_a_missing_cost_store() -> None:
    assert [length_band(value) for value in (0.2, 2, 5, 8, 15, 45)] == [
        "under_1",
        "1_3",
        "3_6",
        "6_10",
        "10_20",
        "over_20",
    ]
    out = daily_export(
        day=DAY,
        rows=[],
        export=None,
        pads=pads(os.urandom(32)),
        environment="production",
        now=ANALYSED,
    )
    assert out["cost_store"] is False
    assert out["calls"] == []
