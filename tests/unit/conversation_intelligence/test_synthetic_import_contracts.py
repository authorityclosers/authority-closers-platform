"""Authored fictional reports stay distinct from scored/provider/media evidence."""

from copy import deepcopy

import pytest
from pydantic import ValidationError

from ac_platform.conversation_intelligence.synthetic_import_contracts import (
    COACHING,
    PILLARS,
    SyntheticCallBundle,
)


def bundle() -> dict:
    business, call = "syn-fixture", "syn-fixture-call-1"
    lineage = {
        "business_id": business,
        "journey_id": business + "-journey-1",
        "company_id": business + "-company-1",
        "prospect_id": business + "-buyer-1",
        "rep_id": business + "-rep-1",
        "at": "2017-01-01T10:00:00+05:30",
        "duration_ms": 1000,
    }
    header = {"synthetic": True, "schema_version": "synthetic-sales-v1.0", "call_id": call}
    report = {**header, **{section: {"authored": section} for section in PILLARS}}
    coaching = {**header, **{section: {"authored": section} for section in COACHING}}
    return {
        "schema": "synthetic-call-bundle/1",
        "synthetic": True,
        "metadata": {
            **header,
            **lineage,
            "team_namespace": business + "-sandbox-synthetic",
            "private_coaching": True,
            "audio_file": None,
        },
        "transcript": {
            **header,
            **lineage,
            "participants": [
                {"synthetic": True, "person_id": lineage["rep_id"]},
                {"synthetic": True, "person_id": lineage["prospect_id"]},
            ],
            "lines": [
                {
                    "synthetic": True,
                    "line_id": call + ":L001",
                    "person_id": lineage["rep_id"],
                    "start_ms": 0,
                    "end_ms": 1000,
                    "text": "नमस्ते, fictional sandbox conversation.",
                    "playable": False,
                }
            ],
        },
        "answer_key": {
            **header,
            **{key: lineage[key] for key in ("business_id", "journey_id", "rep_id")},
            "as_of": lineage["at"],
            "report": {key: value for key, value in report.items() if key != "call_id"},
            "per_call_coaching": {
                key: value for key, value in coaching.items() if key != "call_id"
            },
        },
        "report": report,
        "coaching": coaching,
    }


def test_preserves_authored_sections_and_backdated_estimated_transcript() -> None:
    original = bundle()
    parsed = SyntheticCallBundle.model_validate(original)
    assert parsed.model_dump(by_alias=True) == original
    assert parsed.occurred_at.isoformat() == "2017-01-01T04:30:00+00:00"
    assert parsed.report == original["report"]
    assert parsed.coaching == original["coaching"]


@pytest.mark.parametrize(
    "component", ["metadata", "transcript", "answer_key", "report", "coaching"]
)
@pytest.mark.parametrize("value", [False, 1, "true"])
def test_every_component_must_be_explicitly_synthetic(component, value) -> None:
    data = bundle()
    data[component]["synthetic"] = value
    with pytest.raises(ValidationError):
        SyntheticCallBundle.model_validate(data)


@pytest.mark.parametrize("field", ["report", "coaching"])
def test_authored_sections_cannot_be_substituted_or_scored(field) -> None:
    data = bundle()
    section = next(iter(PILLARS if field == "report" else COACHING))
    data[field][section] = {"score": 99}
    with pytest.raises(ValidationError, match="preserve the exact authored"):
        SyntheticCallBundle.model_validate(data)


@pytest.mark.parametrize(
    "kind",
    [
        "audio",
        "playable",
        "real_person",
        "future_key",
        "overlap",
        "no_timezone",
        "wrong_business",
        "public_coaching",
    ],
)
def test_refuses_unverified_media_mixed_lineage_and_changed_authority(kind) -> None:
    data = bundle()
    if kind == "audio":
        data["metadata"]["audio_file"] = "audio.mp3"
    elif kind == "playable":
        data["transcript"]["lines"][0]["playable"] = True
    elif kind == "real_person":
        data["transcript"]["participants"][0]["person_id"] = "real-member"
    elif kind == "future_key":
        data["answer_key"]["as_of"] = "2026-01-01T00:00:00Z"
    elif kind == "overlap":
        data["transcript"]["lines"].append(deepcopy(data["transcript"]["lines"][0]))
    elif kind == "no_timezone":
        data["metadata"]["at"] = "2017-01-01T10:00:00"
    elif kind == "wrong_business":
        data["metadata"]["company_id"] = "syn-other-company"
    else:
        data["metadata"]["private_coaching"] = False
    with pytest.raises(ValidationError):
        SyntheticCallBundle.model_validate(data)


def test_documented_simulation_envelope_preserves_older_key_sections() -> None:
    data = bundle()
    data["report"]["schema_version"] = "synthetic-sales-simulation/1"
    data["coaching"]["schema_version"] = "synthetic-sales-simulation/1"
    assert SyntheticCallBundle.model_validate(data).report == data["report"]
