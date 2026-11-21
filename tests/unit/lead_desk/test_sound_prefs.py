"""Sounds, one pick per moment (round-2 board 4, 20 Nov 2026): the library's default until the
team picks, the team's until a person picks their own, only sounds of the moment's kind, and
"sellers pick their own" turned off makes the team's the only one."""

from __future__ import annotations

import asyncio
import json
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from uuid import uuid4

import pytest

from ac_platform.lead_desk import sound_prefs
from ac_platform.lead_desk.errors import DeskError

LIBRARY = Path(__file__).resolve().parents[3] / "apps/sales-xray-web/public/sounds/library.json"


def test_the_moments_and_defaults_are_the_librarys() -> None:
    library = json.loads(LIBRARY.read_text())
    events = {event["id"]: event for event in library["events"] if event["app"] == "sales-x-ray"}
    assert set(events) == set(sound_prefs.EVENTS)
    for event_id, event in events.items():
        assert sound_prefs.KIND[event_id] == event["kind"]
        assert sound_prefs.DEFAULT[event_id] == event["default"]
    assert {pack["id"] for pack in library["packs"]} == set(sound_prefs.PACKS)
    assert set(library["kinds"]) == set(sound_prefs.KINDS)
    # Every pack has every kind, so any pack's sound of the right kind is a real file.
    ids = {sound["id"] for sound in library["sounds"]}
    assert ids == {f"{pack}.{kind}" for pack in sound_prefs.PACKS for kind in sound_prefs.KINDS}


def test_only_a_sound_of_the_moments_kind_none_or_the_phones_own() -> None:
    assert sound_prefs.valid("sx.new_lead", "warm-v1.mention")
    assert sound_prefs.valid("sx.incoming_call", "A.ringtone")
    assert sound_prefs.valid("sx.new_lead", "none")
    assert sound_prefs.valid("sx.new_lead", "system")
    assert not sound_prefs.valid("sx.new_lead", "warm-v1.ringtone")
    assert not sound_prefs.valid("sx.new_lead", "nope-v9.mention")
    assert not sound_prefs.valid("sx.new_lead", "/sounds/glass-v1/mention.webm")
    assert not sound_prefs.valid("pulse.mention", "glass-v1.mention")
    assert not sound_prefs.valid("sx.new_lead", 7)


def test_library_default_then_team_then_mine() -> None:
    person, other = uuid4(), uuid4()
    assert sound_prefs.resolve({}, person, "sx.new_lead") == "glass-v2.mention"
    config: dict[str, Any] = {
        "sounds": {
            "team": {"sx.new_lead": "warm-v1.mention", "sx.report_ready": "glass-v1.error"},
            "people": {str(person): {"sx.new_lead": "none"}},
        }
    }
    assert sound_prefs.resolve(config, person, "sx.new_lead") == "none"
    assert sound_prefs.resolve(config, other, "sx.new_lead") == "warm-v1.mention"
    # A stored sound of the wrong kind is left out, so the library's plays.
    assert sound_prefs.resolve(config, other, "sx.report_ready") == "glass-v1.success"
    view = sound_prefs.view_of(config, person, manager=False)
    row = next(row for row in view.events if row.id == "sx.new_lead")
    assert (row.team, row.mine, row.plays) == ("warm-v1.mention", "none", "none")
    assert view.sellers_pick is True and view.own_picks == 1
    # Sellers' own sounds off: the team's plays for everyone.
    config["sounds"]["sellers_pick"] = False
    assert sound_prefs.resolve(config, person, "sx.new_lead") == "warm-v1.mention"


class _Db:
    def __init__(self, row: Any) -> None:
        self.row = row
        self.added: list[Any] = []

    async def get(self, *_: Any, **__: Any) -> Any:
        return self.row

    def add(self, row: Any) -> None:
        self.row = row
        self.added.append(row)

    async def flush(self) -> None:
        return None


def _desk(row: Any, role_manager: bool, person_id: Any = None) -> Any:
    return SimpleNamespace(
        db=_Db(row),
        tenant_id=uuid4(),
        now=datetime(2026, 11, 20, tzinfo=UTC),
        viewer=SimpleNamespace(person_id=person_id or uuid4(), can_manage=role_manager),
    )


def test_a_person_picks_their_own_and_goes_back_to_the_teams() -> None:
    row = SimpleNamespace(config={"work_hours": {"days": [0]}})
    desk = _desk(row, role_manager=False)
    command = sound_prefs.MySoundsCommand(mine={"sx.new_lead": "pulse-v2.mention"})
    view = asyncio.run(sound_prefs.save_mine(desk, command))
    assert next(r for r in view.events if r.id == "sx.new_lead").plays == "pulse-v2.mention"
    # Other settings in the row are kept.
    assert row.config["work_hours"] == {"days": [0]}
    back = sound_prefs.MySoundsCommand(mine={"sx.new_lead": None})
    view = asyncio.run(sound_prefs.save_mine(desk, back))
    assert next(r for r in view.events if r.id == "sx.new_lead").mine is None
    assert row.config["sounds"]["people"] == {}


def test_wrong_kind_refused_and_own_sounds_refused_when_the_team_says_so() -> None:
    row = SimpleNamespace(config={"sounds": {"sellers_pick": False}})
    seller = _desk(row, role_manager=False)
    with pytest.raises(DeskError) as wrong:
        asyncio.run(
            sound_prefs.save_mine(
                seller, sound_prefs.MySoundsCommand(mine={"sx.new_lead": "A.ringtone"})
            )
        )
    assert wrong.value.status == 422
    with pytest.raises(DeskError) as closed:
        asyncio.run(
            sound_prefs.save_mine(
                seller, sound_prefs.MySoundsCommand(mine={"sx.new_lead": "A.mention"})
            )
        )
    assert closed.value.status == 403


def test_the_team_default_keeps_the_librarys_as_no_pick() -> None:
    desk = _desk(None, role_manager=True)
    command = sound_prefs.TeamSoundsCommand(
        team={"sx.new_lead": "glass-v2.mention", "sx.incoming_call": "warm-v3.ringtone"},
        sellers_pick=False,
    )
    view = asyncio.run(sound_prefs.save_team(desk, command))
    stored = desk.db.row.config["sounds"]
    assert stored["team"] == {"sx.incoming_call": "warm-v3.ringtone"}
    assert stored["sellers_pick"] is False
    assert view.sellers_pick is False
    assert next(r for r in view.events if r.id == "sx.incoming_call").plays == "warm-v3.ringtone"
    with pytest.raises(DeskError):
        asyncio.run(
            sound_prefs.save_team(
                desk,
                sound_prefs.TeamSoundsCommand(team={"sx.nope": "none"}, sellers_pick=True),
            )
        )


def test_sound_telemetry_takes_the_librarys_moments_and_packs_only() -> None:
    from ac_platform.telemetry.ingest import check_payload_values
    from ac_platform.telemetry.sales_xray import SALES_XRAY_EVENTS, SOUND_EVENTS, SOUND_PACKS

    assert set(SOUND_EVENTS) == set(sound_prefs.EVENTS)
    assert set(SOUND_PACKS) == {*sound_prefs.PACKS, "none", "system"}
    check_payload_values(
        SALES_XRAY_EVENTS["sx.sound_picked"],
        {"event": "sx.new_lead", "pack": "warm-v1", "scope": "team"},
    )
    check_payload_values(SALES_XRAY_EVENTS["sx.sound_previewed"], {"pack": "none"})
    check_payload_values(
        SALES_XRAY_EVENTS["sx.sound_played"],
        {"event": "sx.incoming_call", "pack": "glass-v3", "platform": "android"},
    )
    with pytest.raises(ValueError):
        check_payload_values(
            SALES_XRAY_EVENTS["sx.sound_picked"],
            {"event": "sx.new_lead", "pack": "/sounds/x.webm", "scope": "me"},
        )
