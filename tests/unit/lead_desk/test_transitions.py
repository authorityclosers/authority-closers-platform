"""Lead OS (24 Oct 2026): where a lead may go from its stage, and what a seller is asked.

The sales team's spec (section 3) is the table below: every pair it lists is allowed,
every other pair is refused, and each stage asks for exactly what it needs. A stage list
saved before Lead OS keeps letting a lead go anywhere.
"""

from __future__ import annotations

from dataclasses import replace

import pytest

from ac_platform.lead_desk.journey import mapping
from ac_platform.lead_desk.journey import transitions as t
from ac_platform.lead_desk.journey.model import (
    JUNK,
    Journey,
    JourneyError,
    Stage,
    build,
    check,
    default_journey,
    from_rows,
    from_template,
)
from ac_platform.lead_desk.journey.templates import template
from ac_platform.lead_desk.vocabulary import (
    CLOSED_STAGES,
    JUNK_REASONS,
    LOST_REASONS,
    STAGES,
    stage_after_not_connected,
)

NINE = (
    "new",
    "not_connected",
    "interested",
    "discussion_incomplete",
    "meeting_scheduled",
    "demo_completed",
    "won",
    "lost",
    "junk",
)
LABELS = {
    "new": "New Lead",
    "not_connected": "Not Connected",
    "interested": "Interested (In Follow-Up)",
    "discussion_incomplete": "Discussion Incomplete",
    "meeting_scheduled": "Meeting / Demo Scheduled",
    "demo_completed": "Demo / Zoom Meeting Completed",
    "won": "Closed / Won",
    "lost": "Closed / Lost",
    "junk": "Junk Lead",
}
# The spec's section 3, plus "any active stage → Lost" and "any stage → Junk".
WORKING = {"not_connected", "interested", "discussion_incomplete", "meeting_scheduled"}
ALLOWED: dict[str, set[str]] = {
    "new": {*WORKING, "lost", "junk"},
    "not_connected": {"interested", "discussion_incomplete", "meeting_scheduled", "lost", "junk"},
    "interested": {"discussion_incomplete", "meeting_scheduled", "lost", "junk"},
    "discussion_incomplete": {"interested", "meeting_scheduled", "lost", "junk"},
    "meeting_scheduled": {
        "demo_completed",
        "not_connected",
        "interested",
        "discussion_incomplete",
        "lost",
        "junk",
    },
    "demo_completed": {"won", "lost", "junk"},
    # Closed: where each can be reopened to; Junk is a manager's reclassify.
    "won": {"interested", "discussion_incomplete", "meeting_scheduled", "demo_completed", "junk"},
    "lost": {*WORKING, "demo_completed", "junk"},
    "junk": {"new", "not_connected", "interested", "discussion_incomplete"},
}
NEEDS: dict[str, tuple[str, ...]] = {
    "new": (),
    "not_connected": ("nc_reason",),
    "interested": ("next_action",),
    "discussion_incomplete": ("next_action",),
    "meeting_scheduled": ("meeting",),
    "demo_completed": ("next_action",),
    "won": (),
    "lost": ("reason",),
    "junk": ("reason",),
}
EVERYTHING = t.Given(
    reason="not_interested",
    nc_reason="did_not_pick",
    next_action=True,
    meeting=True,
)


def nine() -> Journey:
    stages = from_template("inside_sales_demos", default_journey(), {})
    return Journey(1, "inside_sales_demos", stages)


def given_for(target: str) -> t.Given:
    if target == "junk":
        return replace(EVERYTHING, reason="fake")
    return EVERYTHING


# ----- the template ---------------------------------------------------------------------


def test_the_template_has_the_specs_nine_stages_in_order() -> None:
    journey = nine()
    assert [stage.key for stage in journey.live] == list(NINE)
    assert {stage.key: stage.label for stage in journey.live} == LABELS
    kinds = {stage.key: stage.kind for stage in journey.live}
    assert kinds["discussion_incomplete"] == "follow_up"
    assert kinds["meeting_scheduled"] == kinds["demo_completed"] == "interested"
    assert kinds["junk"] == "junk" and kinds["lost"] == "lost" and kinds["won"] == "won"
    # Junk is apart from the funnel; Lost and Not Connected sit beside it.
    assert "junk" not in [stage.key for stage in journey.funnel()]
    assert journey.ruled and journey.has_junk
    assert [stage.key for stage in journey.board()] == list(NINE)


def test_the_template_is_named_by_industry_not_by_a_customer() -> None:
    profile = template("inside_sales_demos")
    assert profile is not None
    assert profile.name == "Inside sales with demos"


def test_the_rules_survive_saving_and_reading_back() -> None:
    journey = nine()
    again = from_rows([stage.as_json() for stage in journey.stages])
    assert again == journey.stages
    lost = journey.by_key["lost"]
    assert lost.reasons == LOST_REASONS
    assert journey.by_key["junk"].reasons == JUNK_REASONS


def test_a_list_saved_before_lead_os_reads_back_without_rules() -> None:
    stored = [
        {
            "key": "new",
            "label": "New",
            "kind": "new",
            "milestone": "lead",
            "archived": False,
            "origin": "template",
        }
    ]
    (stage,) = from_rows(stored)
    assert stage.moves is None and stage.needs is None and stage.reasons is None
    # Written back byte for byte: no new keys.
    assert stage.as_json() == stored[0]


def test_unreadable_rules_are_dropped_never_guessed() -> None:
    (stage,) = from_rows(
        [
            {
                "key": "lost",
                "label": "Lost",
                "kind": "lost",
                "milestone": "lost",
                "moves": ["new", "Bad Key", 7, "new"],
                "needs": ["reason", "fly"],
                "reasons": [{"key": "price", "label": "  Price  "}, {"key": 1}, "x"],
                "rot_hours": True,
            }
        ]
    )
    assert stage.moves == ("new",)
    assert stage.needs == ("reason",)
    assert stage.reasons == (("price", "Price"),)
    assert stage.rot_hours is None


def test_saving_the_list_keeps_rules_the_page_did_not_send() -> None:
    before = nine()
    wanted = [
        {"key": stage.key, "label": stage.label, "kind": stage.kind, "milestone": stage.milestone}
        for stage in before.stages
    ]
    wanted[2]["label"] = "Interested"
    after = build(wanted, before, {})
    by_key = {stage.key: stage for stage in after}
    assert by_key["interested"].label == "Interested"
    assert by_key["interested"].moves == before.by_key["interested"].moves
    assert by_key["lost"].reasons == LOST_REASONS


def test_a_renamed_key_is_followed_in_the_moves() -> None:
    # A business already has a "meeting_scheduled" stage of another kind with leads in it:
    # the template's stage gets a fresh key, and the moves follow it.
    old = Journey(
        3,
        None,
        (
            *default_journey().stages,
            Stage("meeting_scheduled", "Meeting", "follow_up", "contacted"),
        ),
    )
    stages = from_template("inside_sales_demos", old, {"meeting_scheduled": 3})
    by_key = {stage.key: stage for stage in stages}
    assert by_key["meeting_scheduled"].archived and by_key["meeting_scheduled"].kind == "follow_up"
    assert by_key["meeting_scheduled_2"].label == "Meeting / Demo Scheduled"
    assert "meeting_scheduled_2" in (by_key["new"].moves or ())
    assert "meeting_scheduled" not in (by_key["new"].moves or ())


def test_a_list_keeps_one_junk_stage_at_most() -> None:
    stages = (*nine().stages, Stage("spam", "Spam", "junk", "disqualified"))
    with pytest.raises(JourneyError, match="one Junk stage"):
        check(stages)


def test_no_ad_platform_hears_about_junk() -> None:
    names = mapping.suggestions("meta", nine())
    assert names["junk"] is None
    assert names["new"] == "Lead"


# ----- the graph ------------------------------------------------------------------------


PAIRS = [(a, b) for a in NINE for b in NINE if a != b]


@pytest.mark.parametrize(("source", "target"), PAIRS)
def test_the_spec_graph_allows_exactly_its_moves(source: str, target: str) -> None:
    journey = nine()
    current = journey.by_key[source]
    if target in ALLOWED[source]:
        move = t.check(journey, current, target, given_for(target), can_manage=True)
        assert move.stage.key == target
    else:
        with pytest.raises(t.MoveRefused) as refused:
            t.check(journey, current, target, given_for(target), can_manage=True)
        assert refused.value.status == 409
        assert set(refused.value.allowed) == ALLOWED[source]


@pytest.mark.parametrize("target", NINE)
def test_each_stage_asks_for_exactly_what_it_needs(target: str) -> None:
    journey = nine()
    source = next(key for key in NINE if target in ALLOWED[key])
    current = journey.by_key[source]
    needs = NEEDS[target]
    if not needs:
        assert t.check(journey, current, target, t.Given(), can_manage=True).needs == ()
        return
    with pytest.raises(t.MoveRefused) as refused:
        t.check(journey, current, target, t.Given(), can_manage=True)
    assert refused.value.status == 422
    assert refused.value.needs == needs


def test_staying_put_is_not_a_move() -> None:
    journey = nine()
    with pytest.raises(t.MoveRefused) as refused:
        t.check(
            journey, journey.by_key["demo_completed"], "demo_completed", EVERYTHING, can_manage=True
        )
    assert refused.value.status == 409
    assert "already" in str(refused.value)


def test_lost_and_junk_take_only_their_own_reasons() -> None:
    journey = nine()
    current = journey.by_key["interested"]
    for reason, _ in LOST_REASONS[:-1]:
        t.check(journey, current, "lost", t.Given(reason=reason), can_manage=False)
    with pytest.raises(t.MoveRefused) as refused:
        t.check(journey, current, "lost", t.Given(reason="fake"), can_manage=False)
    assert refused.value.needs == ("reason",)
    with pytest.raises(t.MoveRefused) as refused:
        t.check(journey, current, "junk", t.Given(reason="price"), can_manage=False)
    assert refused.value.status == 422


def test_other_needs_a_note() -> None:
    journey = nine()
    current = journey.by_key["new"]
    with pytest.raises(t.MoveRefused) as refused:
        t.check(journey, current, "junk", t.Given(reason="other"), can_manage=False)
    assert refused.value.needs == ("reason_note",)
    with pytest.raises(t.MoveRefused):
        t.check(
            journey, current, "lost", t.Given(reason="other", reason_note="  "), can_manage=False
        )
    move = t.check(
        journey,
        current,
        "lost",
        t.Given(reason="other", reason_note="Moved city"),
        can_manage=False,
    )
    assert move.action == "close" and move.group == "lost"


def test_who_may_reopen_and_reclassify() -> None:
    journey = nine()
    won, lost, junk = (journey.by_key[key] for key in ("won", "lost", "junk"))
    # A seller reopens their Lost or Junk lead; only a manager reopens Won.
    assert t.check(journey, lost, "interested", EVERYTHING, can_manage=False).action == "reopen"
    assert t.check(journey, junk, "new", EVERYTHING, can_manage=False).action == "reopen"
    with pytest.raises(t.MoveRefused) as refused:
        t.check(journey, won, "interested", EVERYTHING, can_manage=False)
    assert refused.value.status == 403
    assert t.check(journey, won, "interested", EVERYTHING, can_manage=True).action == "reopen"
    # Making a closed lead Junk is a manager's; marking an open one Junk is anyone's.
    with pytest.raises(t.MoveRefused) as refused:
        t.check(journey, lost, "junk", given_for("junk"), can_manage=False)
    assert refused.value.status == 403
    assert t.check(journey, lost, "junk", given_for("junk"), can_manage=True).action == (
        "reclassify"
    )
    assert (
        t.check(journey, journey.by_key["new"], "junk", given_for("junk"), can_manage=False).action
        == "close"
    )


def test_a_seller_is_shown_only_the_moves_they_may_make() -> None:
    journey = nine()
    won = journey.by_key["won"]
    assert [m.stage.key for m in t.moves(journey, won, can_manage=False)] == []
    assert {m.stage.key for m in t.moves(journey, won, can_manage=True)} == ALLOWED["won"]
    shown = t.moves(journey, journey.by_key["interested"], can_manage=False)
    assert [m.stage.key for m in shown] == [
        "discussion_incomplete",
        "meeting_scheduled",
        "lost",
        "junk",
    ]
    lost = next(m for m in shown if m.stage.key == "lost")
    assert lost.needs == ("reason",) and "confirm" in lost.asks
    assert t.as_json(lost)["reasons"][0] == {"key": "not_interested", "label": "Not interested"}


def test_an_import_skips_the_graph_but_never_a_reason() -> None:
    journey = nine()
    current = journey.by_key["new"]
    move = t.check(journey, current, "won", t.Given(), can_manage=True, source="import")
    assert move.stage.key == "won"
    # New → Demo completed isn't a move; an import can say a lead stands there.
    t.check(journey, current, "demo_completed", EVERYTHING, can_manage=True, source="import")
    # Nor what a seller gives with a move: a file has no follow-up time, meeting or why a
    # call didn't connect (universal intake, 25 Oct 2026).
    for key in ("not_connected", "interested", "meeting_scheduled"):
        moved = t.check(journey, current, key, t.Given(), can_manage=True, source="import")
        assert moved.stage.key == key
    with pytest.raises(t.MoveRefused) as refused:
        t.check(journey, current, "lost", t.Given(), can_manage=True, source="import")
    assert refused.value.needs == ("reason",)


# ----- lists saved before Lead OS ---------------------------------------------------------


def test_a_list_without_rules_lets_a_lead_go_anywhere_as_before() -> None:
    journey = default_journey()
    new = journey.by_key["new"]
    for key in ("follow_up", "interested", "won", "lost"):
        move = t.check(journey, new, key, t.Given(), can_manage=False)
        assert move.needs == ()
    won = journey.by_key["won"]
    # Today's rule stands: whoever works the lead moves it back from Won.
    assert t.check(journey, won, "interested", t.Given(), can_manage=False).action == "reopen"
    assert t.check(journey, won, "lost", t.Given(), can_manage=False).action == "reclassify"


def test_every_list_can_mark_a_lead_junk_with_a_reason() -> None:
    journey = default_journey()
    current = journey.by_key["interested"]
    with pytest.raises(t.MoveRefused) as refused:
        t.check(journey, current, "junk", t.Given(), can_manage=False)
    assert refused.value.needs == ("reason",)
    move = t.check(journey, current, "junk", t.Given(reason="fake"), can_manage=False)
    assert move.stage is JUNK
    # Back out of Junk to any open stage.
    assert t.check(journey, JUNK, "new", t.Given(), can_manage=False).action == "reopen"


def test_couldnt_reach_needs_why_the_call_did_not_connect() -> None:
    journey = default_journey()
    with pytest.raises(t.MoveRefused) as refused:
        t.check(journey, journey.by_key["new"], "not_connected", t.Given(), can_manage=False)
    assert refused.value.needs == ("nc_reason",)
    t.check(
        journey,
        journey.by_key["new"],
        "not_connected",
        t.Given(nc_reason="busy"),
        can_manage=False,
    )


# ----- unanswered calls never make a lead Junk (acceptance test 10) -------------------


@pytest.mark.parametrize("stage", STAGES)
def test_an_unanswered_call_never_makes_a_lead_junk_or_reopens_it(stage: str) -> None:
    after = stage_after_not_connected(stage)
    assert after != "junk" or stage == "junk"
    if stage in CLOSED_STAGES:
        assert after == stage
