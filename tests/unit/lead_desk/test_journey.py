"""Lead stages per business (20 Oct 2026): industry profiles, the rules every saved list
keeps, what a stage the business names itself means, Meta's matches, and which stage a
Lead Desk event reaches."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import replace
from typing import Any
from uuid import UUID

import pytest

from ac_platform.lead_desk.journey import engine, mapping
from ac_platform.lead_desk.journey.model import (
    JUNK,
    Journey,
    JourneyError,
    Stage,
    build,
    change_note,
    check,
    default_journey,
    from_template,
)
from ac_platform.lead_desk.journey.providers import click_ids, event_id
from ac_platform.lead_desk.journey.providers import meta as meta_provider
from ac_platform.lead_desk.journey.templates import (
    KINDS,
    MILESTONE_KIND,
    TEMPLATES,
    guess_milestone,
    slug,
)


def saved(stages: tuple[Stage, ...], version: int = 1, industry: str | None = None) -> Journey:
    return Journey(version, industry, stages)


# ----- profiles ------------------------------------------------------------------------


def test_every_profile_is_a_valid_list_and_named_by_industry() -> None:
    ids = [template.id for template in TEMPLATES]
    assert len(ids) == len(set(ids))
    for template in TEMPLATES:
        stages = tuple(Stage(s.key, s.label, s.kind, s.milestone) for s in template.stages)
        check(stages)
        assert stages[0].kind == "new"
        assert template.id == slug(template.id)


def test_the_default_profile_keeps_the_desks_own_six_stages() -> None:
    journey = default_journey()
    assert journey.version == 0
    six = [kind for kind in KINDS if kind != "junk"]
    assert [stage.key for stage in journey.stages] == six
    for kind in KINDS:
        stage = journey.resolve(kind, None)
        assert stage is not None and stage.key == kind
    # Junk (Lead OS, 24 Oct 2026) is the desk's own stage in a list without one.
    assert journey.resolve("junk", None) is JUNK
    assert [stage.key for stage in journey.board()] == [*six, "junk"]


@pytest.mark.parametrize(
    ("label", "milestone"),
    [
        ("Site visit booked", "appointment_booked"),
        ("Site visit done", "appointment_done"),
        ("Visited store", "appointment_done"),
        ("Demo attended", "appointment_done"),
        ("Booked", "won"),
        ("Policy issued", "won"),
        ("Enrolled", "won"),
        ("Not interested", "lost"),
        ("Junk", "disqualified"),
        ("Spam", "disqualified"),
        ("Fake enquiry", "disqualified"),
        ("Wrong number", "disqualified"),
        ("Interested", "qualified"),
        ("Quote shared", "proposal"),
        ("Documents collected", "application"),
        ("Negotiation", "negotiation"),
        ("Contacted", "contacted"),
        ("Couldn't reach", "unreachable"),
        ("New enquiry", "lead"),
        ("Blue folder", "other"),
    ],
)
def test_a_stage_named_by_the_business_gets_a_likely_meaning(label: str, milestone: str) -> None:
    assert guess_milestone(label) == milestone


def test_keys_come_from_names() -> None:
    assert slug("Site visit — done!") == "site_visit_done"
    assert slug("2nd call") == "stage_2nd_call"
    assert len(slug("x" * 90)) <= 40


# ----- the rules a saved list keeps ----------------------------------------------------


def test_a_new_stage_gets_a_key_meaning_and_type_from_its_words() -> None:
    before = default_journey()
    wanted = [stage.as_json() for stage in before.stages]
    wanted.insert(4, {"label": "Site visit done"})
    stages = build(wanted, before, {})
    added = next(stage for stage in stages if stage.label == "Site visit done")
    assert (added.key, added.milestone, added.kind, added.origin) == (
        "site_visit_done",
        "appointment_done",
        "interested",
        "custom",
    )


def test_a_stage_left_out_stays_archived_so_history_keeps_its_words() -> None:
    before = saved(default_journey().stages)
    wanted = [stage.as_json() for stage in before.stages if stage.key != "interested"]
    stages = build(wanted, before, {})
    gone = next(stage for stage in stages if stage.key == "interested")
    assert gone.archived


def test_a_stage_with_leads_keeps_its_type() -> None:
    before = saved(default_journey().stages)
    wanted = [stage.as_json() for stage in before.stages]
    for item in wanted:
        if item["key"] == "interested":
            item["kind"] = "follow_up"
    with pytest.raises(JourneyError, match="has leads"):
        build(wanted, before, {"interested": 3})
    assert build(wanted, before, {}) is not None


@pytest.mark.parametrize(
    ("change", "words"),
    [
        (lambda s: [x for x in s if x["kind"] != "won"], "Won stage"),
        (lambda s: [x for x in s if x["kind"] != "lost"], "Lost stage"),
        (lambda s: [s[2], *s[:2], *s[3:]], "New stage comes first"),
        (lambda s: [*s, {"label": "Follow-up"}], "same name"),
        (lambda s: [*s, {"label": "x" * 41}], "40 letters"),
    ],
)
def test_lists_that_would_break_the_desk_are_refused(
    change: Callable[[list[dict[str, Any]]], list[dict[str, Any]]], words: str
) -> None:
    before = saved(default_journey().stages)
    with pytest.raises(JourneyError, match=words):
        build(change([stage.as_json() for stage in before.stages]), before, {})


def test_a_profile_replaces_the_list_and_keeps_used_stages_archived() -> None:
    before = default_journey()
    stages = from_template("real_estate", before, {"interested": 2, "follow_up": 0})
    keys = [stage.key for stage in stages if not stage.archived]
    assert keys[0] == "new" and "site_visit_booked" in keys and "booked" in keys
    archived = {stage.key for stage in stages if stage.archived}
    # Never saved before: only stages that hold leads come along.
    assert archived == {"interested"}
    journey = saved(stages, industry="real_estate")
    # A lead that was Interested before keeps its words.
    stage = journey.resolve("interested", None)
    assert stage is not None and stage.label == "Interested"


def test_unknown_profiles_are_refused() -> None:
    with pytest.raises(JourneyError):
        from_template("acme_corp", default_journey(), {})


def test_the_funnel_and_skipped_stages() -> None:
    journey = saved(from_template("real_estate", default_journey(), {}))
    assert journey.with_earlier("site_visit_done") == [
        "new",
        "contacted",
        "site_visit_booked",
        "site_visit_done",
    ]
    assert journey.with_earlier("lost") == ["lost"]
    assert journey.with_earlier("not_connected") == ["not_connected"]


def test_change_notes_say_what_changed() -> None:
    before = saved(default_journey().stages)
    renamed = tuple(
        replace(stage, label="Spoke to them") if stage.key == "follow_up" else stage
        for stage in before.stages
    )
    assert change_note(before, renamed) == "Renamed Follow-up → Spoke to them"


# ----- Meta's matches ------------------------------------------------------------------


def test_meta_hears_lead_first_then_each_stages_own_name() -> None:
    journey = saved(from_template("real_estate", default_journey(), {}))
    names = mapping.suggestions("meta", journey)
    assert names["new"] == "Lead"
    assert names["site_visit_booked"] == "Site visit booked"
    assert names["not_connected"] is None
    assert names["lost"] == "Lost"


def test_only_confirmed_matches_are_sent_and_new_stages_wait() -> None:
    journey = saved(from_template("real_estate", default_journey(), {}))
    config = mapping.confirmed(
        {}, "meta", journey, {"new": "Lead", "booked": "Booked"}, by=_PERSON, now=1
    )
    settings = mapping.read(config, "meta")
    states = {m.stage.key: m.state for m in mapping.matches("meta", journey, settings)}
    assert states["new"] == "on" and states["booked"] == "on"
    assert states["site_visit_done"] == "new"


def test_names_meta_refuses_are_refused_here() -> None:
    journey = saved(default_journey().stages)
    with pytest.raises(JourneyError):
        mapping.clean_events("meta", journey, {"won": "Won!!"})
    with pytest.raises(JourneyError):
        mapping.clean_events("meta", journey, {"won": "Lead", "new": "lead"})


def test_the_meta_only_settings_are_read_as_metas() -> None:
    legacy = {
        "meta_conversions": {
            "dataset_id": "1750520232917169",
            "dataset_name": "Sales Xray lead stages",
            "on": True,
            "events": {"new": "Lead", "won": "Won", "not_connected": None},
            "since": 100,
            "cursor": {"at": "2026-10-19T10:00:00+00:00", "id": str(_PERSON)},
        }
    }
    settings = mapping.read(legacy, "meta")
    assert settings.ready and settings.destination_id == "1750520232917169"
    assert settings.events["won"] == "Won"
    assert mapping.cursor(legacy) is not None
    moved = mapping.destination_saved(
        legacy,
        "meta",
        destination_id="1750520232917169",
        destination_name="x",
        on=True,
        test_code=None,
        now=200,
    )
    assert moved["meta_conversions"]["moved"] is True
    assert moved["meta_conversions"]["on"] is False
    assert mapping.read(moved, "meta").since == 100
    assert mapping.cursor(moved) == mapping.cursor(legacy)


def test_meta_event_ids_match_the_meta_only_sender() -> None:
    from ac_platform.lead_desk.connectors import meta_capi

    assert event_id("meta", "123456789012345", "Won") == meta_capi.event_id(
        "123456789012345", "Won"
    )
    assert event_id("google_ads", "x", "Won") != event_id("meta", "x", "Won")


def test_meta_names_are_cleaned() -> None:
    assert meta_provider.clean_name("Site visit (done)!") == "Site visit done"
    assert meta_provider.clean_name("!!!") is None


def test_click_ids_are_read_from_a_leads_record() -> None:
    found = click_ids({"gclid": "Cj0KCQjw-abc123", "utm": {"fbclid": "IwAR0xyz123"}, "x": 1})
    assert found == {"gclid": "Cj0KCQjw-abc123", "fbclid": "IwAR0xyz123"}
    assert click_ids({"gclid": "bad id with spaces"}) == {}


# ----- which stage an event reaches ------------------------------------------------------


def test_the_stage_each_lead_desk_event_reaches() -> None:
    journey = saved(from_template("real_estate", default_journey(), {}))
    assert engine.reached(journey, "captured", {}) == "new"
    assert engine.reached(journey, "repeat", {"reopened": True}) == "new"
    assert engine.reached(journey, "repeat", {}) is None
    # A call that kept the stage moves nowhere.
    assert (
        engine.reached(journey, "result", {"stage": "follow_up", "from_stage": "follow_up"}) is None
    )
    # Old results with only the desk stage reach the business's stage for it.
    assert (
        engine.reached(journey, "result", {"stage": "won", "from_stage": "follow_up"}) == "booked"
    )
    assert (
        engine.reached(
            journey,
            "stage",
            {"stage": "interested", "step": "site_visit_done", "from_step": "site_visit_booked"},
        )
        == "site_visit_done"
    )
    assert engine.reached(journey, "note", {}) is None


def test_every_milestone_has_a_desk_kind() -> None:
    assert set(MILESTONE_KIND.values()) <= set(KINDS)


_PERSON = UUID("00000000-0000-4000-8000-000000000001")
