"""Speaker reads retain revision fences and expose only the declared projection."""

from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest

from ac_platform.conversation_intelligence.application import (
    ConversationConflict,
    ConversationDenied,
    ConversationError,
    ConversationNotFound,
)
from ac_platform.conversation_intelligence.speaker_map_service import read_speaker_map
from ac_platform.conversation_intelligence.speaker_map_store import normalize_speaker_decisions

TRANSCRIPT = {
    "revision": "fictional-c2",
    "segments": [
        {
            "id": "s0",
            "speaker_id": "speaker_0",
            "start_ms": 0,
            "end_ms": 1000,
            "text": "This is Zoya from Example Company.",
        },
        {
            "id": "s1",
            "speaker_id": "speaker_1",
            "start_ms": 1000,
            "end_ms": 2000,
            "text": "Hello, my name is Ravi.",
        },
    ],
}


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "state", ["predicted", "confirmed", "stale", "unavailable", "denied", "conflict", "no_actor"]
)
async def test_read_default_profile_revision_and_error_boundaries(monkeypatch, state):
    revision = (
        None
        if state == "predicted"
        else {
            "revision": 7,
            "transcript_revision": "old" if state == "stale" else "fictional-c2",
            "speakers": [
                {"speaker_id": "speaker_0", "role": "you", "display_name": None},
                {"speaker_id": "speaker_1", "role": "prospect", "display_name": None},
            ],
        }
    )
    latest = AsyncMock(return_value=revision)
    if state == "denied":
        latest.side_effect = ConversationDenied("Private call")
    monkeypatch.setattr(
        "ac_platform.conversation_intelligence.speaker_map_service.read_speaker_map_revision",
        latest,
    )
    render = AsyncMock(return_value=TRANSCRIPT)
    if state in ("unavailable", "conflict"):
        render.side_effect = (
            ConversationNotFound if state == "unavailable" else ConversationConflict
        )("No C2")
    reports = SimpleNamespace(
        recording=AsyncMock(
            return_value=(
                SimpleNamespace(usage_id=uuid4(), tenant_id=uuid4(), submission_id=uuid4()),
                object(),
            )
        ),
        render_transcript=render,
        render_report=AsyncMock(side_effect=ConversationNotFound("No report")),
    )
    monkeypatch.setattr(
        "ac_platform.conversation_intelligence.speaker_map_service.AcquisitionReports",
        lambda _: reports,
    )
    database = SimpleNamespace(
        scalar=AsyncMock(
            return_value=SimpleNamespace(display_name="Zoya Patel", first_name="Wrong")
        )
    )
    ownership = SimpleNamespace(database=database)
    arguments = dict(actor=SimpleNamespace(person_id=uuid4()), shared_identity_locks=True)
    if state == "no_actor":
        arguments["actor"] = None
    if state in ("denied", "conflict", "no_actor"):
        with pytest.raises(ConversationError):
            await read_speaker_map(ownership, uuid4(), **arguments)
        if state == "denied":
            reports.recording.assert_not_awaited()
        if state == "no_actor":
            database.scalar.assert_not_awaited()
        return
    result = await read_speaker_map(ownership, uuid4(), **arguments)
    assert set(result) == {
        "schema",
        "submission_id",
        "status",
        "unavailable_reason",
        "transcript_revision",
        "map_revision",
        "user_revision",
        "speakers",
        "report_basis",
    }
    assert result["user_revision"] == (0 if revision is None else 7)
    assert result["report_basis"] is None
    if state == "unavailable":
        assert result["status"] == "unavailable" and result["speakers"] == []
        assert result["map_revision"] is result["transcript_revision"] is None
    else:
        assert result["status"] == ("confirmed" if state == "confirmed" else "predicted")
        assert result["speakers"][0]["display_name"] == "Zoya Patel"
        assert result["speakers"][0]["role"] == "you"
        assert all(row["confidence"] is None for row in result["speakers"])


@pytest.mark.parametrize(
    "role,name", [("you", None), ("salesperson", None), ("prospect", None), ("other", "Ravi")]
)
def test_unattributed_cannot_take_a_name_or_the_only_you_slot(role, name):
    transcript = {"segments": [{"speaker_id": "unattributed"}]}
    with pytest.raises(ConversationError, match="Unattributed"):
        normalize_speaker_decisions(
            [{"speaker_id": "unattributed", "role": role, "display_name": name}], transcript
        )
    assert (
        normalize_speaker_decisions(
            [{"speaker_id": "unattributed", "role": "other", "display_name": None}], transcript
        )[0]["role"]
        == "other"
    )
