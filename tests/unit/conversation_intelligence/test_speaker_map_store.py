"""Speaker choices reject malformed fields and stale source/revision writes."""

from dataclasses import replace
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from ac_platform.conversation_intelligence.application import (
    ConversationConflict,
    ConversationDenied,
    ConversationError,
    ConversationNotFound,
)
from ac_platform.conversation_intelligence.speaker_map_store import (
    normalize_speaker_decisions,
    read_speaker_map_revision,
    update_speaker_map,
)
from tests.unit.conversation_intelligence.test_submission_labels import _actor, _ownership, _scope

TRANSCRIPT = {"revision": "fictional-c2", "segments": [{"speaker_id": "s0"}, {"speaker_id": "s1"}]}
CHOICES = [
    {"speaker_id": "s0", "role": "you", "display_name": "  ज़ोया जी  "},
    {"speaker_id": "s1", "role": "prospect", "display_name": None},
]


def test_names_keep_unicode_honorifics_and_default_null() -> None:
    result = normalize_speaker_decisions(list(reversed(CHOICES)), TRANSCRIPT)
    assert result[0]["display_name"] == "ज़ोया जी"
    assert result[1]["display_name"] is None
    assert (
        normalize_speaker_decisions(
            [{**CHOICES[0], "display_name": "x" * 80}, CHOICES[1]], TRANSCRIPT
        )[0]["display_name"]
        == "x" * 80
    )


def test_32_speakers_and_128_character_label_are_accepted() -> None:
    ids = ["s" * 128, *(f"s{index}" for index in range(31))]
    transcript = {"segments": [{"speaker_id": key} for key in ids] + [{"speaker_id": None}]}
    speakers = [{"speaker_id": key, "role": "other"} for key in ids]
    assert len(normalize_speaker_decisions(speakers, transcript)) == 32


def test_optional_icons_are_preserved_or_explicitly_cleared() -> None:
    choices = [{**CHOICES[0], "icon": None}, {**CHOICES[1], "icon": "carpentry"}]
    normalized = normalize_speaker_decisions(choices, TRANSCRIPT)
    assert normalized[0]["icon"] is None
    assert normalized[1]["icon"] == "carpentry"
    assert "icon" not in normalize_speaker_decisions(CHOICES, TRANSCRIPT)[0]
    assert (
        normalize_speaker_decisions([{**CHOICES[0], "icon": "x" * 64}, CHOICES[1]], TRANSCRIPT)[0][
            "icon"
        ]
        == "x" * 64
    )
    with pytest.raises(ConversationError):
        normalize_speaker_decisions(
            [{"speaker_id": "unattributed", "role": "other", "icon": "person"}],
            {"segments": [{"speaker_id": "unattributed"}]},
        )


@pytest.mark.parametrize(
    "invalid",
    [
        None,
        {},
        [],
        CHOICES * 17,
        CHOICES[:1],
        [CHOICES[0]] * 2,
        *[
            [{**CHOICES[0], "speaker_id": value}, CHOICES[1]]
            for value in (None, [], "x" * 129, "unknown")
        ],
        *[[{**CHOICES[0], "role": value}, CHOICES[1]] for value in (None, [], "seller")],
        *[
            [{**CHOICES[0], "display_name": value}, CHOICES[1]]
            for value in ("", " ", "x" * 81, "x\n", "x\u202e", "\ud800", "\u200b", 3)
        ],
        [CHOICES[0], {**CHOICES[1], "role": "you"}],
        [{**CHOICES[0], "confidence": "high"}, CHOICES[1]],
        *[
            [{**CHOICES[0], "icon": value}, CHOICES[1]]
            for value in ("", "../person", "Person", "x" * 65, "person\n", "person.svg", 3, [])
        ],
    ],
)
def test_invalid_choices_fail_without_names_in_error(invalid) -> None:
    with pytest.raises(ConversationError) as error:
        normalize_speaker_decisions(invalid, TRANSCRIPT)
    assert "ज़ोया" not in str(error.value)


@pytest.mark.asyncio
async def test_legacy_client_retry_preserves_saved_icon_without_a_new_revision(monkeypatch) -> None:
    scope = _scope()
    speakers = normalize_speaker_decisions(CHOICES, TRANSCRIPT)
    speakers[1]["icon"] = "carpentry"
    latest = SimpleNamespace(revision=1, transcript_revision="fictional-c2", speakers=speakers)
    ownership = _ownership(scope, scalar_values=[object(), latest])
    monkeypatch.setattr(
        "ac_platform.conversation_intelligence.speaker_map_store.AcquisitionReports",
        lambda _: SimpleNamespace(render_transcript=AsyncMock(return_value=TRANSCRIPT)),
    )
    result = await update_speaker_map(
        ownership,
        scope.submission_id,
        actor=_actor(tenant_id=scope.tenant_id),
        expected_revision=0,
        transcript_revision="fictional-c2",
        speakers=CHOICES,
    )
    assert result["revision"] == 1 and result["speakers"][1]["icon"] == "carpentry"
    ownership.database.add.assert_not_called()
    ownership.database.flush.assert_not_awaited()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "failure",
    ["anonymous", "unclaimed", "tenant", "erased", "binding", "transcript", "revision", "limit"],
)
async def test_fences_reject_without_write(monkeypatch, failure: str) -> None:
    scope = _scope(claimed_account=failure != "unclaimed")
    actor = None if failure == "anonymous" else _actor(tenant_id=scope.tenant_id)
    latest = SimpleNamespace(
        revision=50 if failure == "limit" else 2, transcript_revision="fictional-c2", speakers=[]
    )
    ownership = _ownership(scope, scalar_values=[None if failure == "erased" else object(), latest])
    if failure == "tenant":
        ownership.tenant_id = _scope().tenant_id
    if failure == "binding":
        ownership.require_submission_owner.side_effect = [
            scope,
            replace(scope, source_sha256="b" * 64),
        ]
    monkeypatch.setattr(
        "ac_platform.conversation_intelligence.speaker_map_store.AcquisitionReports",
        lambda _: SimpleNamespace(render_transcript=AsyncMock(return_value=TRANSCRIPT)),
    )
    expected = (
        ConversationDenied
        if failure in ("anonymous", "unclaimed", "tenant")
        else (ConversationNotFound if failure in ("erased", "binding") else ConversationConflict)
    )
    with pytest.raises(expected):
        await update_speaker_map(
            ownership,
            scope.submission_id,
            actor=actor,
            expected_revision=50 if failure == "limit" else 0,
            transcript_revision="old-c2" if failure == "transcript" else "fictional-c2",
            speakers=CHOICES,
        )
    ownership.database.add.assert_not_called()
    ownership.database.flush.assert_not_awaited()
    if failure in ("anonymous", "unclaimed", "tenant"):
        with pytest.raises(ConversationDenied):
            await read_speaker_map_revision(ownership, scope.submission_id, actor=actor)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "revision,transcript",
    [
        (-1, "fictional-c2"),
        (51, "fictional-c2"),
        (True, "fictional-c2"),
        (0, None),
        (0, ""),
        (0, "x" * 257),
    ],
)
async def test_invalid_revision_rejected_before_database_access(revision, transcript) -> None:
    scope = _scope()
    ownership = _ownership(scope, scalar_values=[])
    with pytest.raises(ConversationError):
        await update_speaker_map(
            ownership,
            scope.submission_id,
            actor=_actor(tenant_id=scope.tenant_id),
            expected_revision=revision,
            transcript_revision=transcript,
            speakers=CHOICES,
        )
    ownership.database.scalar.assert_not_awaited()
