"""Stages a business already uses in a connected app (Pulse's workflow steps), offered on
Lead stages and never applied by themselves."""

from __future__ import annotations

import pytest

from ac_platform.lead_desk.journey import catalogue
from ac_platform.lead_desk.journey.model import Journey, Stage, default_journey, from_template

SENT = {
    "source": "pulse",
    "revision": "r1",
    "workflows": [
        {
            "id": "wf_sales",
            "name": "Sunrise Rooftops sales",
            "steps": [
                {"id": "st_4", "name": "Quotation", "block": "quotation", "position": 4},
                {"id": "st_1", "name": "Lead capture", "block": "lead_capture", "position": 1},
                {"id": "st_3", "name": "Site visit", "block": "site_visit", "position": 3},
                {"id": "st_2", "name": "Call the lead", "block": "follow_up", "position": 2},
                {"id": "st_5", "name": "Prepare the van", "block": "checklist", "position": 5},
                {
                    "id": "st_6",
                    "name": "Approve the discount quote",
                    "block": "approval",
                    "position": 6,
                },
            ],
        }
    ],
}


def test_a_catalogue_is_kept_bounded_and_in_order() -> None:
    kept = catalogue.clean("pulse", SENT, now=100)
    steps = kept["workflows"][0]["steps"]
    assert [step["id"] for step in steps] == ["st_1", "st_2", "st_3", "st_4", "st_5", "st_6"]
    assert kept["revision"] == "r1" and kept["received_at"] == 100
    with pytest.raises(catalogue.CatalogueError):
        catalogue.clean("crm_x", SENT, now=1)
    with pytest.raises(catalogue.CatalogueError):
        catalogue.clean(
            "pulse", {"workflows": [{"id": "bad id!", "name": "x", "steps": []}]}, now=1
        )
    with pytest.raises(catalogue.CatalogueError):
        catalogue.clean("pulse", {"workflows": [{}] * 21}, now=1)


def test_only_sales_steps_that_are_not_stages_yet_are_offered() -> None:
    config = {catalogue.KEY: catalogue.clean("pulse", SENT, now=1)}
    journey = Journey(1, "simple", default_journey().stages)
    offered = catalogue.suggestions(config, journey)
    # The capture step is the first stage already; the van checklist is an inside task.
    assert [item["label"] for item in offered] == ["Call the lead", "Site visit", "Quotation"]
    visit = offered[1]
    assert visit["ref"] == "pulse:st_3"
    assert (visit["milestone"], visit["kind"], visit["source"]) == (
        "appointment_booked",
        "interested",
        "Pulse",
    )


def test_a_step_already_added_is_not_offered_again() -> None:
    config = {catalogue.KEY: catalogue.clean("pulse", SENT, now=1)}
    stages = from_template("home_services", default_journey(), {})
    added = (
        *stages,
        Stage(
            "site_visit",
            "Site visit",
            "interested",
            "appointment_booked",
            origin="pulse",
            ref="pulse:st_3",
        ),
    )
    offered = catalogue.suggestions(config, Journey(2, "home_services", added))
    assert "Site visit" not in [item["label"] for item in offered]
    assert catalogue.suggestions({}, Journey(2, None, added)) == []
