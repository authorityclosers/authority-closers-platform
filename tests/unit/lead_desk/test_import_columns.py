"""Stage and owner columns in a file or pasted import (owner P0, 23 Oct 2026).

A row may name its lead's stage and owner: the column is found by its header,
a stage by its label, key or kind, and an owner by a full name or a first
name only one teammate has.
"""

from __future__ import annotations

from dataclasses import replace
from uuid import uuid4

from ac_platform.lead_desk.intake import match_stage, people_index, suggest_columns
from ac_platform.lead_desk.journey.model import Journey, default_journey


def test_the_stage_and_owner_columns_are_found_by_their_headers() -> None:
    headers = ["Name", "Mobile", "Lead Status", "Assigned To", "Notes"]
    assert suggest_columns(headers, {"name": "Name", "phone": "Mobile"}) == {
        "stage": "Lead Status",
        "owner": "Assigned To",
    }
    # A header already used for a field is not taken again, and none is guessed.
    assert suggest_columns(["Name", "Status"], {"name": "Status"}) == {}
    assert suggest_columns(["Name", "Phone"], {}) == {}


def test_a_stage_is_matched_by_label_key_or_kind_and_never_an_archived_one() -> None:
    journey = default_journey()
    live = [stage for stage in journey.stages if not stage.archived]
    first = live[0]
    assert match_stage(journey, first.label.upper()) == first
    assert match_stage(journey, f"  {first.key} ") == first
    kind = live[-1].kind
    assert match_stage(journey, kind.replace("_", " ")) == next(
        stage for stage in live if stage.kind == kind
    )
    assert match_stage(journey, "Hot lead") is None
    archived = Journey(
        journey.version,
        journey.industry,
        tuple(replace(stage, archived=stage.key == first.key) for stage in journey.stages),
    )
    assert match_stage(archived, first.label) != first


def test_an_owner_is_a_full_name_or_a_first_name_only_one_teammate_has() -> None:
    asha, asha_two, ravi = uuid4(), uuid4(), uuid4()
    index = people_index(
        [(asha, "Asha Example"), (asha_two, "Asha Sample"), (ravi, "Ravi Fictional")]
    )
    assert index["asha_example"] == asha
    assert index["ravi"] == ravi
    assert index["ravi_fictional"] == ravi
    # Two Ashas: the first name alone names neither.
    assert index["asha"] is None
    # The same full name twice names neither either.
    twins = people_index([(asha, "Meera Joshi"), (ravi, "Meera Joshi")])
    assert twins["meera_joshi"] is None
