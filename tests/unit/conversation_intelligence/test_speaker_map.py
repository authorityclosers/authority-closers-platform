"""Fictional-only parity against the shipped web, plus server source boundaries."""

import json
from copy import deepcopy
from pathlib import Path
from typing import Any

import pytest

from ac_platform.conversation_intelligence.checkpoints import content_hash
from ac_platform.conversation_intelligence.speaker_map import (
    _names,
    _you,
    is_account_name,
    predict_speaker_map,
    project_speaker_roles,
    resolve_speaker_map,
)

CASES = json.loads((Path(__file__).parent / "fixtures/speaker_map/parity.json").read_text())


def test_user_icons_do_not_change_report_provenance_or_rewrite_sources() -> None:
    transcript = CASES[0]["transcript"]
    source = {
        "revision": 1,
        "transcript_revision": transcript["revision"],
        "speakers": [{"speaker_id": "s0", "role": "you"}, {"speaker_id": "s1", "role": "prospect"}],
    }
    baseline = resolve_speaker_map(
        transcript, account_holder_name="Suyash Rao", user_revision=source
    )
    for icon in ("carpentry", "business", None):
        decorated = deepcopy(source)
        decorated["speakers"][1]["icon"] = icon
        before = deepcopy((transcript, decorated))
        result = resolve_speaker_map(
            transcript, account_holder_name="Suyash Rao", user_revision=decorated
        )
        assert result["speakers"][1]["icon"] == icon
        assert result["map_revision"] == baseline["map_revision"]
        assert project_speaker_roles(result) == project_speaker_roles(baseline)
        assert (transcript, decorated) == before
        decorated["transcript_revision"] = "old-c2"
        stale = resolve_speaker_map(
            transcript, account_holder_name="Suyash Rao", user_revision=decorated
        )
        assert all("icon" not in speaker for speaker in stale["speakers"])
    model_source = deepcopy(source)
    model_source["speakers"][1]["icon"] = "carpentry"
    model = resolve_speaker_map(
        transcript, account_holder_name="Suyash Rao", model_revision=model_source
    )
    assert all("icon" not in speaker for speaker in model["speakers"])


@pytest.mark.parametrize("case", CASES, ids=lambda case: case["case"])
def test_shipped_web_parity_and_server_roles(case: dict[str, Any]) -> None:
    transcript, account = case["transcript"], case["account"]
    before = deepcopy(transcript)
    voices = list(
        dict.fromkeys(
            row["speaker_id"] for row in transcript["segments"] if row["speaker_id"] is not None
        )
    )
    names, evidence = _names(transcript["segments"], voices)
    assert names == case["names"]
    assert _you(transcript["segments"], voices, account) == case["web_you"]
    assert [key for key in names if is_account_name(names[key], account)] == case["account_matches"]
    result = predict_speaker_map(transcript, account_holder_name=account)
    assert result == predict_speaker_map(transcript, account_holder_name=account)
    assert transcript == before
    assert [row["speaker_id"] for row in result["speakers"]] == voices
    assert [row["number"] for row in result["speakers"]] == list(range(1, len(voices) + 1))
    assert result["map_revision"] == content_hash(
        {"transcript_revision": transcript["revision"], "speakers": result["speakers"]}
    )
    assert sum(row["role"] == "you" for row in result["speakers"]) <= 1
    assert all(
        row["channel"] is None and row["confidence"] is None and len(row["role_cues"]) <= 5
        for row in result["speakers"]
    )
    segments = {row["id"]: row for row in transcript["segments"]}
    for items in evidence.values():
        for item in items:
            assert item == {
                "segment_id": segments[item["segment_id"]]["id"],
                "start_ms": segments[item["segment_id"]]["start_ms"],
                "end_ms": segments[item["segment_id"]]["end_ms"],
            }
    if case["roles"] is not None:
        assert {row["speaker_id"]: row["role"] for row in result["speakers"]} == case["roles"]


def test_unavailable_unattributed_and_no_coaching_ownership() -> None:
    absent = resolve_speaker_map(None, account_holder_name="Rahul")
    assert absent["status"] == "unavailable" and absent["speakers"] == []
    assert absent["map_revision"] is None and absent["transcript_revision"] is None
    transcript = deepcopy(CASES[0]["transcript"])
    transcript["segments"][2]["speaker_id"] = "unattributed"
    result = predict_speaker_map(transcript, account_holder_name="Suyash Rao")
    assert all(row["role"] is None for row in result["speakers"])
    assert result["speakers"][-1]["display_name"] is None


def test_evidence_retains_native_time_in_projected_c2() -> None:
    transcript = deepcopy(CASES[0]["transcript"])
    transcript["playback_projection"] = {"segments": [{"id": "seg-2", "native_end_ms": 3100}]}
    before = deepcopy(transcript)
    result = predict_speaker_map(transcript, account_holder_name="Suyash Rao")
    assert result["speakers"][0]["name_evidence"] == [
        {"segment_id": "seg-2", "start_ms": 2000, "end_ms": 3100}
    ]
    assert transcript == before


@pytest.mark.parametrize(
    ("source_key", "extra", "status", "origin"),
    [
        ("user_revision", {"revision": 1}, "confirmed", "user_confirmed_roles"),
        ("saved_channel", {"saved_you_side": 0}, "channel", "channel_mapped_roles"),
    ],
)
def test_unattributed_segment_preserves_confirmed_or_channel_origin(
    source_key: str, extra: dict[str, int], status: str, origin: str
) -> None:
    transcript = deepcopy(CASES[0]["transcript"])
    transcript["segments"].append(
        {
            "id": "seg-3",
            "speaker_id": "unattributed",
            "start_ms": 3000,
            "end_ms": 3900,
            "text": "Unattributed background words.",
        }
    )
    source = {
        "transcript_revision": transcript["revision"],
        "speakers": [{"speaker_id": "s0", "role": "you"}, {"speaker_id": "s1", "role": "prospect"}],
        **extra,
    }
    before = deepcopy((transcript, source))
    result = resolve_speaker_map(
        transcript, account_holder_name="Suyash Rao", **{source_key: source}
    )
    assert result["status"] == status
    snapshot = project_speaker_roles(result)
    assert snapshot["origin"] == origin
    assert snapshot["speakers"] == [
        {"speaker_id": "s0", "role": "seller", "is_account_holder": True},
        {"speaker_id": "s1", "role": "prospect", "is_account_holder": False},
    ]
    assert result["speakers"][-1]["role"] is None
    assert result["speakers"][-1]["role_source"] is None
    assert (transcript, source) == before
    # A real unresolved speaker still prevents authoritative attribution.
    transcript["segments"].append(
        {"id": "seg-4", "speaker_id": "s2", "start_ms": 4000, "end_ms": 4900, "text": "Hello."}
    )
    unresolved = resolve_speaker_map(
        transcript, account_holder_name="Suyash Rao", **{source_key: source}
    )
    assert project_speaker_roles(unresolved)["origin"] == "unverified_provider_labels"


@pytest.mark.parametrize("stale_source", ["user_revision", "model_revision"])
def test_stale_sources_are_ignored(stale_source: str) -> None:
    transcript = CASES[0]["transcript"]
    source = {
        "revision": 9,
        "transcript_revision": "old-c2",
        "speakers": [{"speaker_id": "s1", "role": "you", "display_name": "Wrong"}],
    }
    result = resolve_speaker_map(
        transcript, account_holder_name="Suyash Rao", **{stale_source: source}
    )
    assert (
        result["speakers"]
        == predict_speaker_map(transcript, account_holder_name="Suyash Rao")["speakers"]
    )
    assert result["user_revision"] == 0
    assert len(result["diagnostics"]) == 1


def test_field_precedence_profile_default_and_names_free_snapshot() -> None:
    transcript = CASES[0]["transcript"]
    model = {
        "transcript_revision": transcript["revision"],
        "speakers": [
            {
                "speaker_id": "s0",
                "role": "you",
                "spoken_name": "Suyash",
                "confidence": "high",
                "evidence_segment_ids": ["seg-2"],
            },
            {"speaker_id": "s1", "role": "prospect", "spoken_name": "Rahul", "confidence": "low"},
        ],
    }
    channel = {
        "transcript_revision": transcript["revision"],
        "saved_you_side": 1,
        "speakers": [
            {"speaker_id": "s0", "role": "salesperson"},
            {"speaker_id": "s1", "role": "you"},
        ],
    }
    user = {
        "revision": 3,
        "transcript_revision": transcript["revision"],
        "speakers": [
            {"speaker_id": "s0", "role": "you", "display_name": "Chosen name"},
            {"speaker_id": "s1", "role": "prospect", "display_name": None},
        ],
    }
    before = deepcopy((transcript, model, channel, user))
    result = resolve_speaker_map(
        transcript,
        account_holder_name="Suyash Rao",
        model_revision=model,
        saved_channel=channel,
        user_revision=user,
    )
    assert (transcript, model, channel, user) == before
    assert result["user_revision"] == 3 and result["status"] == "confirmed"
    assert result["speakers"][0]["display_name"] == "Chosen name"
    assert result["speakers"][1]["display_name"] is None
    assert all(row["confidence"] is None for row in result["speakers"])
    assert project_speaker_roles(result) == {
        "origin": "user_confirmed_roles",
        "transcript_revision": transcript["revision"],
        "map_revision": result["map_revision"],
        "speakers": [
            {"speaker_id": "s0", "role": "seller", "is_account_holder": True},
            {"speaker_id": "s1", "role": "prospect", "is_account_holder": False},
        ],
    }
    channel_result = resolve_speaker_map(
        transcript, account_holder_name="Suyash Rao", model_revision=model, saved_channel=channel
    )
    assert channel_result["speakers"][0]["display_name"] == "Suyash"
    assert channel_result["speakers"][1]["display_name"] == "Suyash Rao"
    assert project_speaker_roles(channel_result)["origin"] == "channel_mapped_roles"
    user["speakers"][0]["display_name"] = None
    assert (
        resolve_speaker_map(transcript, account_holder_name="Suyash Rao", user_revision=user)[
            "speakers"
        ][0]["display_name"]
        == "Suyash Rao"
    )


def test_model_you_needs_matching_stated_name_and_mixed_sources_stay_uncertain() -> None:
    transcript = CASES[0]["transcript"]
    model = {
        "transcript_revision": transcript["revision"],
        "speakers": [
            {"speaker_id": "s1", "role": "you", "spoken_name": "Rahul", "confidence": "high"}
        ],
    }
    result = resolve_speaker_map(transcript, account_holder_name="Suyash Rao", model_revision=model)
    assert result["speakers"][1]["role"] == "salesperson"
    assert result["speakers"][1]["confidence"] == "high"
    assert project_speaker_roles(result)["origin"] == "text_predicted_roles"
    assert project_speaker_roles(result)["speakers"][1] == {
        "speaker_id": "s1",
        "role": "seller",
        "is_account_holder": False,
    }
    user = {
        "transcript_revision": transcript["revision"],
        "speakers": [{"speaker_id": "s1", "role": "you"}],
    }
    result = resolve_speaker_map(transcript, account_holder_name="Suyash Rao", user_revision=user)
    assert [row["role"] for row in result["speakers"]] == ["salesperson", "you"]
    assert result["speakers"][0]["display_name"] == "Suyash"
    assert project_speaker_roles(result)["origin"] == "text_predicted_roles"


@pytest.mark.parametrize(
    "entries",
    [
        [{"speaker_id": "missing", "role": "you"}],
        [{"speaker_id": "s0", "role": "you"}, {"speaker_id": "s0", "role": "prospect"}],
        [{"speaker_id": "s0", "role": "you"}, {"speaker_id": "s1", "role": "you"}],
    ],
)
def test_malformed_map_falls_back_without_authority(entries: list[dict[str, Any]]) -> None:
    transcript = CASES[0]["transcript"]
    result = resolve_speaker_map(
        transcript,
        account_holder_name="Suyash Rao",
        user_revision={"transcript_revision": transcript["revision"], "speakers": entries},
    )
    assert project_speaker_roles(result)["origin"] == "text_predicted_roles"
    assert result["diagnostics"] == ["speaker_map_source_invalid_confirmed"]
