"""Fictional text-only attribution; predictions never become confirmed identity."""

from copy import deepcopy

import pytest

from ac_platform.conversation_intelligence.speaker_map import (
    predict_speaker_map,
    project_speaker_roles,
)


def transcript(*turns):
    return {
        "revision": "fictional-c2",
        "segments": [
            {
                "id": f"seg-{index}",
                "speaker_id": voice,
                "text": text,
                "start_ms": index * 1_000,
                "end_ms": (index + 1) * 1_000,
            }
            for index, (voice, text) in enumerate(turns)
        ],
    }


@pytest.mark.parametrize(
    "introduction",
    [
        "Hi Priya, Arun Kale here from Fictional Tools. Can you hear me?",
        "Hello Priya, Arun speaking from Fictional Tools.",
        "नमस्ते Priya, मैं Arun Kale, Fictional Tools से। आवाज़ आ रही है?",
        "नमस्कार Priya, मी Arun Kale, Fictional Tools मधून बोलतोय.",
        "नमस्कार Priya, Arun Kale बोलतोय, Fictional Tools मधून. आवाज ठीक है?",
    ],
)
def test_self_introduction_outweighs_repeated_buyer_questions(introduction):
    source = transcript(
        ("s1", "What is your current offer?"),
        ("s0", introduction),
        ("s1", "Tell me about your support."),
        ("s1", "Tell me about your price."),
        ("s1", "I checked with our team. They will review this."),
        ("s1", "What is your current plan?"),
        ("s0", "I can explain that."),
    )
    before = deepcopy(source)
    result = predict_speaker_map(source, account_holder_name=None)
    assert {row["speaker_id"]: row["role"] for row in result["speakers"]} == {
        "s1": "prospect",
        "s0": "salesperson",
    }
    assert result["status"] == "predicted"
    assert project_speaker_roles(result)["origin"] == "text_predicted_roles"
    assert all(not row["is_account_holder"] for row in project_speaker_roles(result)["speakers"])
    assert all(row["role_source"] == "predicted" for row in result["speakers"])
    assert source == before


def test_two_business_self_introductions_remain_ambiguous():
    source = transcript(
        ("s0", "Arun here from Fictional Tools."),
        ("s1", "Priya here from Fictional Services."),
        ("s1", "Tell me about your price."),
    )
    result = predict_speaker_map(source, account_holder_name=None)
    assert all(row["role"] is None for row in result["speakers"])


def test_mentioning_a_team_or_company_is_not_a_self_introduction():
    source = transcript(
        ("s0", "I checked with our team. Our team needs a decision."),
        ("s1", "हमारी कंपनी यह देखेगी।"),
    )
    result = predict_speaker_map(source, account_holder_name=None)
    assert all(row["role"] is None for row in result["speakers"])


def test_moving_away_from_a_location_is_not_a_self_introduction():
    source = transcript(
        ("s0", "Arun Kale here from Fictional Tools."),
        ("s1", "I am moving away from the reception desk. Please wait."),
    )
    result = predict_speaker_map(source, account_holder_name=None)
    assert {row["speaker_id"]: row["role"] for row in result["speakers"]} == {
        "s0": "salesperson",
        "s1": "prospect",
    }


@pytest.mark.parametrize("location", ["मैं पुणे से हूँ।", "मी पुण्यात आहे."])
def test_location_alone_is_not_the_new_self_introduction_cue(location):
    source = transcript(("s0", location), ("s1", "Okay."))
    result = predict_speaker_map(source, account_holder_name=None)
    assert all(row["role"] is None for row in result["speakers"])


def test_extra_voice_is_not_assigned_prospect_by_elimination():
    source = transcript(
        ("s0", "Arun here from Fictional Tools."),
        ("s1", "Hello."),
        ("s2", "Hello."),
    )
    result = predict_speaker_map(source, account_holder_name=None)
    roles = {row["speaker_id"]: row["role"] for row in result["speakers"]}
    assert roles == {"s0": "salesperson", "s1": None, "s2": None}
