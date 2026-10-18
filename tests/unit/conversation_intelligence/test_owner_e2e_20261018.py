"""Owner's end-to-end test on 18 Oct 2026: a new call says it is being scored,
and two voices get a guessed salesperson and prospect. Fictional data only."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest

from ac_platform.conversation_intelligence.pointer_review import (
    AUTOMATIC_SINCE,
    review_status,
)
from ac_platform.conversation_intelligence.report_structure import report_statistics
from ac_platform.conversation_intelligence.speaker_map import predict_speaker_map

NOW = datetime(2026, 10, 18, 10, 40, tzinfo=UTC)


def envelope() -> dict[str, Any]:
    return {"recording_id": str(uuid4()), "run_id": str(uuid4())}


@pytest.mark.parametrize(
    ("created", "status"),
    [
        (NOW - timedelta(minutes=2), "scoring"),
        (NOW - timedelta(hours=47), "scoring"),
        (NOW - timedelta(hours=49), "not_scored"),
        (AUTOMATIC_SINCE - timedelta(minutes=1), "before_scores"),
    ],
)
async def test_a_report_without_scores_says_why(created: datetime, status: str) -> None:
    database = AsyncMock()
    database.scalar.return_value = created
    result = await review_status(database, envelope(), now=NOW)
    assert result == {"status": status, "report_created_at": created.isoformat()}
    database.scalar.assert_awaited_once()


async def test_missing_report_or_ids_never_claim_scoring() -> None:
    database = AsyncMock()
    database.scalar.return_value = None
    assert (await review_status(database, envelope(), now=NOW))["status"] == "not_scored"
    assert (await review_status(database, {"run_id": "x"}, now=NOW))["status"] == "not_scored"
    # A bad id is refused before any read.
    database.scalar.assert_awaited_once()


async def test_naive_timestamps_read_as_utc() -> None:
    database = AsyncMock()
    database.scalar.return_value = (NOW - timedelta(minutes=1)).replace(tzinfo=None)
    assert (await review_status(database, envelope(), now=NOW))["status"] == "scoring"


def segment(index: int, speaker: str, text: str) -> dict[str, Any]:
    start = index * 10_000
    return {
        "id": f"s{index}",
        "speaker_id": speaker,
        "start_ms": start,
        "end_ms": start + (8_000 if speaker == "speaker_1" else 3_000),
        "text": text,
    }


# No self-introduction: the words alone name no seller. speaker_1 talks more
# and asks more questions, the way a seller leads a discovery call.
CALL = [
    segment(0, "speaker_0", "Hello?"),
    segment(1, "speaker_1", "Hi, is now a good time? How many flats are you looking at?"),
    segment(2, "speaker_0", "Two, maybe."),
    segment(3, "speaker_1", "Which area works for your family? And what budget feels right?"),
    segment(4, "speaker_0", "Near the station. Not sure yet."),
    segment(5, "speaker_1", "Shall I send three options today and call you on Friday?"),
]


def transcript(segments: list[dict[str, Any]]) -> dict[str, Any]:
    return {"revision": "r1", "segments": segments, "duration_ms": 60_000}


def test_two_voices_get_a_guessed_seller_and_prospect() -> None:
    result = predict_speaker_map(transcript(CALL), account_holder_name=None)
    roles = {row["speaker_id"]: (row["role"], row["role_source"]) for row in result["speakers"]}
    assert roles == {
        "speaker_0": ("prospect", "predicted"),
        "speaker_1": ("salesperson", "predicted"),
    }
    seller = next(row for row in result["speakers"] if row["speaker_id"] == "speaker_1")
    assert seller["role_cues"][-1] == {
        "cue": "led_talk_and_questions",
        "segment_id": "s1",
        "start_ms": 10_000,
        "end_ms": 18_000,
    }
    # The Report's talk share, questions and longest turn now have numbers.
    stats = report_statistics(transcript(CALL), result)
    assert stats["talk_share_percent"]["rep"] is not None
    assert stats["questions_asked"] == {"rep": 5, "prospect": 1}
    assert stats["longest_rep_turn"] is not None


def test_no_guess_when_talk_and_questions_disagree_or_three_voices() -> None:
    quiet_asker = [
        segment(0, "speaker_0", "What do you charge? Is it monthly?"),
        segment(1, "speaker_1", "It depends on the plan you choose and the size of your team."),
    ]
    result = predict_speaker_map(transcript(quiet_asker), account_holder_name=None)
    assert all(row["role"] is None for row in result["speakers"])
    third = [*CALL, segment(6, "speaker_2", "Sorry, who is calling?")]
    result = predict_speaker_map(transcript(third), account_holder_name=None)
    assert all(row["role"] is None for row in result["speakers"])


def test_a_stated_introduction_still_wins_over_the_guess() -> None:
    introduced = [
        segment(0, "speaker_0", "Hi, this is Ravi from Bright Homes, calling about your enquiry."),
        *CALL[1:],
    ]
    result = predict_speaker_map(transcript(introduced), account_holder_name=None)
    roles = {row["speaker_id"]: row["role"] for row in result["speakers"]}
    assert roles == {"speaker_0": "salesperson", "speaker_1": "prospect"}
