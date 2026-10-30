"""The stage editor (stages-views-sources.md §3, owner + Dipak, 30 Oct 2026): the
recommended nine, "Sellers see this", a colour per stage, the first stage's Cold Leads
name, and where a removed stage's leads go."""

from __future__ import annotations

from typing import Any

import pytest

from ac_platform.lead_desk.journey.model import (
    Journey,
    JourneyError,
    build,
    check_places,
    default_journey,
    from_rows,
    from_template,
    journey_of,
)
from ac_platform.lead_desk.journey.templates import template


def recommended(version: int = 1) -> Journey:
    profile = template("recommended")
    assert profile is not None
    return journey_of(profile, version)


def sent(journey: Journey, **changes: dict[str, Any]) -> list[dict[str, Any]]:
    """The page's list: every live stage by its key, with the changes asked for."""
    return [
        {"key": stage.key, "label": stage.label, **changes.get(stage.key, {})}
        for stage in journey.live
    ]


def test_the_recommended_nine_differ_between_inbound_and_cold_only_in_the_first_name() -> None:
    journey = recommended()
    assert [(s.label, s.kind, s.milestone) for s in journey.stages] == [
        ("New Lead", "new", "lead"),
        ("Not Connected", "not_connected", "unreachable"),
        ("Open Leads", "follow_up", "contacted"),
        ("Interested", "interested", "qualified"),
        ("Meeting Scheduled", "interested", "appointment_booked"),
        ("Meeting Done", "interested", "appointment_done"),
        ("Won", "won", "won"),
        ("Closed / Lost", "lost", "lost"),
        ("Junk Lead", "junk", "disqualified"),
    ]
    assert [s.cold_label for s in journey.stages] == ["Unworked"] + [None] * 8
    assert from_template("recommended", default_journey(), {})[0].cold_label == "Unworked"


def test_a_list_saved_before_the_editor_reads_back_unchanged() -> None:
    row = {
        "key": "new",
        "label": "New",
        "kind": "new",
        "milestone": "lead",
        "archived": False,
        "origin": "template",
    }
    [stage] = from_rows([row])
    assert (stage.hidden, stage.color, stage.cold_label) == (False, None, None)
    assert stage.as_json() == row


def test_the_editor_settings_are_stored_and_read_back() -> None:
    rows = [stage.as_json() for stage in recommended().stages]
    rows[2] |= {"hidden": True, "color": "amber"}
    rows[3] |= {"color": "purple"}  # not one of the dots: read as none
    read = from_rows(rows)
    assert (read[2].hidden, read[2].color) == (True, "amber")
    assert read[3].color is None
    assert read[0].cold_label == "Unworked"
    assert read[2].as_json() == rows[2]


def test_the_page_sets_keeps_and_clears_visibility_colour_and_the_cold_name() -> None:
    before = recommended()
    stages = build(
        sent(
            before,
            new={"cold_label": "  Fresh   list "},
            open_leads={"visible": False, "color": "amber"},
            won={"color": "green"},
        ),
        before,
        {},
    )
    by = {stage.key: stage for stage in stages}
    assert by["new"].cold_label == "Fresh list"
    assert (by["open_leads"].hidden, by["open_leads"].color) == (True, "amber")
    assert (by["won"].hidden, by["won"].color) == (False, "green")

    # Left out, each keeps what it had; an empty colour or name clears it.
    saved = Journey(2, None, stages)
    again = {
        stage.key: stage
        for stage in build(
            sent(saved, won={"color": ""}, new={"cold_label": ""}, open_leads={"visible": True}),
            saved,
            {},
        )
    }
    assert again["won"].color is None and again["new"].cold_label is None
    assert (again["open_leads"].hidden, again["open_leads"].color) == (False, "amber")


def test_a_new_stage_can_start_hidden_and_coloured() -> None:
    before = recommended()
    wanted = sent(before)
    wanted.insert(
        6,
        {
            "label": "Demo booked",
            "milestone": "appointment_booked",
            "visible": False,
            "color": "violet",
        },
    )
    stage = build(wanted, before, {})[6]
    assert (stage.key, stage.kind, stage.hidden, stage.color) == (
        "demo_booked",
        "interested",
        True,
        "violet",
    )


@pytest.mark.parametrize(
    ("changes", "words"),
    [
        ({"new": {"visible": False}}, "Sellers always see the first stage."),
        ({"won": {"cold_label": "Cold won"}}, "Only the first stage has a Cold Leads name."),
        ({"won": {"color": "#ff0000"}}, "Pick a colour from the dots."),
    ],
)
def test_editor_settings_that_would_confuse_sellers_are_refused(
    changes: dict[str, dict[str, Any]], words: str
) -> None:
    before = recommended()
    with pytest.raises(JourneyError, match=words.replace(".", r"\.")):
        build(sent(before, **changes), before, {})


def test_a_removed_stage_with_leads_goes_where_the_manager_picked() -> None:
    before = recommended()
    wanted = [item for item in sent(before) if item["key"] != "meeting_done"]
    after = Journey(2, None, build(wanted, before, {"meeting_done": 3}))
    assert after.by_key["meeting_done"].archived
    assert check_places(before, after, {"meeting_done": "interested"}) == {
        "meeting_done": "interested"
    }
    # An open stage's leads stay open; Won and Lost keep their kind.
    with pytest.raises(JourneyError):
        check_places(before, after, {"meeting_done": "won"})
