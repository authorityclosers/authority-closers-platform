"""Real fictional prompt reconstruction; report text and live names never supply basis."""

from copy import deepcopy
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest

from ac_platform.conversation_intelligence import reports, speaker_report_basis
from ac_platform.conversation_intelligence.application import (
    ConversationConflict,
    ConversationNotFound,
)
from ac_platform.conversation_intelligence.checkpoints import content_hash
from ac_platform.conversation_intelligence.inference_tasks import prepare_coaching_input
from ac_platform.conversation_intelligence.reporting_pipeline import ReportingPipeline, StageRequest
from ac_platform.conversation_intelligence.speaker_report_basis import (
    project_report_basis,
    read_report_basis,
)
from tests.unit.conversation_intelligence.test_coaching_source_context import source_and_facts
from tests.unit.conversation_intelligence.test_speaker_roles_report_input import snapshot


def current_map(source="predicted"):
    return {
        "transcript_revision": snapshot()["transcript_revision"],
        "map_revision": "b" * 64,
        "speakers": [
            {
                "speaker_id": "speaker_1",
                "role": "you",
                "role_source": source,
                "display_name": "Renamed",
            }
        ],
    }


@pytest.mark.parametrize("origin,status", list(speaker_report_basis._STATUS.items()))
def test_basis_retains_used_revision_and_roles_ignore_live_names(origin, status):
    roles = snapshot(origin)
    current = current_map()
    before = deepcopy((roles, current))
    assert project_report_basis(roles, current) == {
        "status": status,
        "map_revision": "a" * 64,
        "you_speaker_id": "speaker_1",
        "matches_current": True,
    }
    assert (roles, current) == before


@pytest.mark.parametrize("change", ["confirmed", "channel", "swap", "role", "stale", "extra"])
def test_confirmation_reconciles_only_matching_bound_roles(change):
    roles = snapshot("text_predicted_roles")
    current = current_map(change if change in {"confirmed", "channel"} else "predicted")
    if change == "swap":
        current["speakers"][0]["speaker_id"] = "speaker_2"
    elif change == "role":
        current["speakers"][0]["role"] = "salesperson"
    elif change == "stale":
        current["transcript_revision"] = "later-c2"
    elif change == "extra":
        current["speakers"].append(
            {"speaker_id": "speaker_2", "role": "prospect", "role_source": "confirmed"}
        )
    result = project_report_basis(roles, current)
    assert result["matches_current"] is (change in {"confirmed", "channel"})
    assert result["status"] == (change if change in {"confirmed", "channel"} else "predicted")
    assert result["you_speaker_id"] == "speaker_1"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "provider,model",
    [("groq", "openai/gpt-oss-120b"), ("gemini", "gemini-3.8-flash"), ("openai", "gpt-6-luna")],
)
@pytest.mark.parametrize(
    "case",
    [
        "valid",
        "legacy",
        "drifted_template",
        "fallback",
        "no_report",
        "bad_intent",
        "bad_input",
        "stale_report",
        "missing_c1",
        "undeclared",
    ],
)
async def test_basis_uses_exact_saved_provider_input_or_content_free_null(
    monkeypatch, caplog, provider, model, case
):
    monkeypatch.setattr(reports, "SPEAKER_ROLE_PROMPT_REVISIONS", frozenset({"coaching-v3"}))
    transcript, packet = source_and_facts()
    roles = snapshot("text_predicted_roles")
    request = StageRequest(
        stage="C5",
        transcript_checkpoint_id=uuid4(),
        fact_checkpoint_ids=(uuid4(),),
        provider=provider,
        model=model,
        profile=reports.load_report_profile(),
        coaching_prompt_revision="coaching-v3",
        speaker_roles=None if case == "fallback" else roles,
    )
    prepared = prepare_coaching_input(
        transcript,
        [packet],
        provider=provider,
        model=model,
        profile=request.profile,
        coaching_prompt_revision="coaching-v3",
        speaker_roles=request.speaker_roles,
        max_completion_tokens=request.max_completion_tokens,
    )
    intent = {"request": request.model_dump(mode="json"), "input": prepared.as_dict()}
    if case == "legacy":
        intent["input"].pop("prompt_provenance")
    elif case == "drifted_template":
        intent["input"]["prompt_provenance"]["template_sha256"] = "0" * 64
    task = SimpleNamespace(
        intent=intent, intent_sha256=content_hash(intent), input_sha256=prepared.input_sha256
    )
    if case == "bad_intent":
        task.intent_sha256 = "0" * 64
    if case == "bad_input":
        task.input_sha256 = "0" * 64
    if case == "undeclared":
        monkeypatch.setattr(reports, "SPEAKER_ROLE_PROMPT_REVISIONS", frozenset())
    database = SimpleNamespace(scalar=AsyncMock(return_value=task))
    envelope = {
        "run_id": str(uuid4()),
        "transcript_revision": "older-c2" if case == "stale_report" else transcript["revision"],
    }
    reader = SimpleNamespace(
        database=database,
        application=SimpleNamespace(database=database),
        render_report=AsyncMock(return_value=envelope),
    )
    if case == "no_report":
        reader.render_report.side_effect = ConversationNotFound("No report")
    checkpoint = AsyncMock(
        side_effect=lambda _, __, stage: (
            SimpleNamespace(
                payload=transcript if stage == "C2" else packet.model_dump(mode="json")
            ),
            object(),
        )
    )
    parent = AsyncMock(
        return_value=(
            SimpleNamespace(payload={"media_duration_ms": transcript["duration_ms"]}),
            object(),
        )
    )
    if case == "missing_c1":
        parent.side_effect = ConversationConflict("Private contents")
    monkeypatch.setattr(ReportingPipeline, "checkpoint", checkpoint)
    monkeypatch.setattr(ReportingPipeline, "parent", parent)
    recording = SimpleNamespace(id=uuid4(), tenant_id=uuid4(), person_id=uuid4(), generation=1)
    before = deepcopy((intent, transcript, packet))
    result = await read_report_basis(reader, recording, uuid4(), current_map())
    if case in {"valid", "legacy"}:
        assert result == project_report_basis(roles, current_map())
        assert caplog.messages == []
    else:
        assert result is None
        assert caplog.messages == (
            [] if case in {"fallback", "no_report"} else ["speaker_report_basis_unavailable"]
        )
    if case in {"fallback", "no_report"}:
        checkpoint.assert_not_awaited()
    assert (intent, transcript, packet) == before
    assert "Private contents" not in caplog.text
