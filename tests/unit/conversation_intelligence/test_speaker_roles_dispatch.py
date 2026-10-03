"""Fictional C5 request replay and attribution binding; no provider calls."""

import asyncio
from copy import deepcopy
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock
from uuid import uuid4

import pytest

from ac_platform.conversation_intelligence import inference_worker, reporting_pipeline, reports
from ac_platform.conversation_intelligence.checkpoints import (
    build_checkpoint,
    canonical,
    content_hash,
)
from ac_platform.conversation_intelligence.inference import binding_for
from ac_platform.conversation_intelligence.inference_tasks import (
    InferenceTaskError,
    PreparedTaskInput,
    _validated_text_input,
    prepare_coaching_input,
    validate_coaching_result,
)
from ac_platform.conversation_intelligence.qualitative_pack import (
    load_qualitative_pack_for_revision,
)
from ac_platform.conversation_intelligence.reporting_pipeline import (
    ALIGNMENT_RECIPE,
    FACT_RECIPE,
    ReportingPipeline,
    StageRequest,
)
from tests.unit.conversation_intelligence.test_coaching_source_context import source_and_facts
from tests.unit.conversation_intelligence.test_speaker_roles_report_input import snapshot


@pytest.mark.parametrize("revision", [f"coaching-v{n}" for n in range(1, 7)])
def test_legacy_intents_and_prepared_bytes_omit_roles(revision):
    transcript, packet = source_and_facts()
    options = {
        "coaching_prompt_revision": revision,
        "provider": "gemini",
        "model": "gemini-3.8-flash",
    }
    if revision in {"coaching-v4", "coaching-v5", "coaching-v6"}:
        options.update(
            report_language="en",
            qualitative_pack_sha256=load_qualitative_pack_for_revision(revision).sha256,
        )
    request = StageRequest(
        stage="C5", transcript_checkpoint_id=uuid4(), fact_checkpoint_ids=(uuid4(),), **options
    )
    assert "speaker_roles" not in request.model_dump(mode="json")
    baseline = prepare_coaching_input(transcript, [packet], **options)
    assert (
        prepare_coaching_input(transcript, [packet], speaker_roles=snapshot(), **options)
        == baseline
    )
    with pytest.raises(ValueError, match="speaker_roles_revision_undeclared"):
        StageRequest(**request.model_dump(), speaker_roles=snapshot())
    with pytest.raises(ValueError, match="speaker_roles_revision_undeclared"):
        StageRequest(stage="C4", transcript_checkpoint_id=uuid4(), speaker_roles=snapshot())


@pytest.mark.parametrize(
    "provider,model",
    [("groq", "openai/gpt-oss-120b"), ("gemini", "gemini-3.8-flash"), ("openai", "gpt-6-luna")],
)
def test_prepared_roles_bind_to_declared_revision_and_exact_snapshot(monkeypatch, provider, model):
    revision = "coaching-v3" if provider == "groq" else "coaching-v5"
    monkeypatch.setattr(reports, "SPEAKER_ROLE_PROMPT_REVISIONS", frozenset({revision}))
    transcript, packet = source_and_facts()
    roles = snapshot()
    before = deepcopy((transcript, packet, roles))
    task = prepare_coaching_input(
        transcript,
        [packet],
        provider=provider,
        model=model,
        coaching_prompt_revision=revision,
        qualitative_pack_sha256=(
            load_qualitative_pack_for_revision(revision).sha256 if provider != "groq" else None
        ),
        speaker_roles=roles,
    )
    assert PreparedTaskInput.from_dict(task.as_dict(), payload=task.payload) == task
    _validated_text_input(
        task,
        task="coaching",
        transcript=transcript,
        coaching_prompt_revision=revision,
        speaker_roles=roles,
    )
    with pytest.raises(InferenceTaskError, match="task_prompt_speaker_roles_undeclared"):
        _validated_text_input(
            task,
            task="coaching",
            transcript=transcript,
            coaching_prompt_revision="coaching-v4",
            speaker_roles=roles,
        )
    changed = deepcopy(roles)
    changed["speakers"][0].update(role="other", is_account_holder=False)
    with pytest.raises(InferenceTaskError, match="task_prompt_source_context_mismatch"):
        _validated_text_input(
            task,
            task="coaching",
            transcript=transcript,
            coaching_prompt_revision=revision,
            speaker_roles=changed,
        )
    with pytest.raises(InferenceTaskError, match="task_prompt_source_context_mismatch"):
        _validated_text_input(
            task, task="coaching", transcript=transcript, coaching_prompt_revision=revision
        )
    assert (transcript, packet, roles) == before
    if provider == "groq":
        from tests.conversation_overview_fixtures import overview_for
        from tests.unit.conversation_intelligence.test_inference_tasks import _result

        payload = {
            "summary": "A fictional qualitative draft.",
            "strengths": [],
            "missed_opportunities": [],
            "improvements": [],
            "objection_analysis": [],
            "closing_analysis": [],
            "verdict": "Source evidence is limited.",
        }
        payload["overview"] = overview_for(payload)
        result = _result(payload, provider=provider, model=model, input_sha256=task.input_sha256)
        normalized = validate_coaching_result(
            result, task, transcript, coaching_prompt_revision=revision, speaker_roles=roles
        )
        assert normalized.transcript_revision == transcript["revision"]


@pytest.mark.parametrize("invalid", [None, "stale", "name", "unknown", "budget"])
def test_pipeline_replay_preserves_c2_c4_and_invalid_roles_fall_back(monkeypatch, caplog, invalid):
    monkeypatch.setattr(reports, "SPEAKER_ROLE_PROMPT_REVISIONS", frozenset({"coaching-v3"}))
    monkeypatch.setattr(
        "ac_platform.conversation_intelligence.alignment.build_alignment", lambda *_: {}
    )
    monkeypatch.setattr(
        "ac_platform.conversation_intelligence.alignment.project_transcript_for_playback",
        lambda value, **_: value,
    )
    transcript, packet = source_and_facts()
    roles = snapshot()
    if invalid == "stale":
        roles["transcript_revision"] = "old"
    elif invalid == "name":
        roles["speakers"][0]["display_name"] = "Fictional Private Name"
    elif invalid == "unknown":
        roles["speakers"][0]["speaker_id"] = "missing"
    elif invalid == "budget":
        original_prepare = reporting_pipeline.prepare_coaching_input

        def bounded_prepare(*args, **kwargs):
            if kwargs.get("speaker_roles") is not None:
                raise InferenceTaskError("report_prompt_budget_exceeded")
            return original_prepare(*args, **kwargs)

        monkeypatch.setattr(reporting_pipeline, "prepare_coaching_input", bounded_prepare)
    recording = SimpleNamespace(
        id=uuid4(), tenant_id=uuid4(), source_sha256=transcript["source_sha256"], source_revision=1
    )
    binding = binding_for(recording)
    c0 = build_checkpoint(binding, "C0", "recording-v1", {}, (), "0" * 64)
    c1 = build_checkpoint(binding, "C1", "signals-v1", {}, (c0,), "1" * 64)
    c2 = build_checkpoint(binding, "C2", "transcript-v1", {}, (c0,), content_hash(transcript))
    c3 = build_checkpoint(binding, "C3", ALIGNMENT_RECIPE, {}, (c1, c2), content_hash({}))
    c4 = build_checkpoint(
        binding, "C4", FACT_RECIPE, {}, (c2, c3), content_hash(packet.model_dump(mode="json"))
    )
    c1_id, c2_id, c4_id = uuid4(), uuid4(), uuid4()
    rows = {
        "C1": (SimpleNamespace(payload={}), c1),
        "C2": (SimpleNamespace(payload=transcript), c2),
        "C4": (SimpleNamespace(id=c4_id, payload=packet.model_dump(mode="json")), c4),
    }
    service = SimpleNamespace(
        database=Mock(),
        plan_transcription=AsyncMock(
            return_value=SimpleNamespace(
                signal_id=c1_id, checkpoint=c2, duration_ms=transcript["duration_ms"]
            )
        ),
    )
    pipeline = ReportingPipeline(service)
    pipeline.checkpoint = AsyncMock(side_effect=lambda _, __, stage: rows[stage])
    pipeline.provider_task = AsyncMock(
        return_value=(None, {"response_sha256": transcript["revision"]})
    )
    pipeline.save = AsyncMock()
    request = StageRequest(
        stage="C5",
        transcript_checkpoint_id=c2_id,
        fact_checkpoint_ids=(c4_id,),
        coaching_prompt_revision="coaching-v3",
        speaker_roles=roles,
    )
    before = deepcopy((transcript, packet, roles))

    async def exercise():
        plan = await pipeline.plan(recording, request)
        replay = await pipeline.plan(
            recording, StageRequest.model_validate(plan.intent()["request"])
        )
        assert replay.prepared == plan.prepared and replay.checkpoint == plan.checkpoint
        assert plan.request.speaker_roles == (roles if invalid is None else None)
        if invalid is not None:
            assert caplog.messages == [
                "speaker_roles_prompt_budget_exceeded"
                if invalid == "budget"
                else "speaker_roles_snapshot_invalid"
            ]
            baseline = await pipeline.plan(
                recording, request.model_copy(update={"speaker_roles": None})
            )
            assert baseline.prepared == plan.prepared and baseline.checkpoint == plan.checkpoint
        else:
            assert (
                plan.prepared
                != (
                    await pipeline.plan(
                        recording, request.model_copy(update={"speaker_roles": None})
                    )
                ).prepared
            )
            validator = Mock(return_value="validated")
            monkeypatch.setattr(inference_worker, "validate_coaching_result", validator)
            result = object()
            scope = SimpleNamespace(task=SimpleNamespace(stage="C5"), plan=replay)
            assert (
                inference_worker.ConversationInferenceWorker._validate(scope, result) == "validated"
            )
            assert validator.call_args.kwargs["speaker_roles"] == roles
            assert validator.call_args.kwargs["coaching_prompt_revision"] == "coaching-v3"
        _validated_text_input(
            plan.prepared,
            task="coaching",
            transcript=transcript,
            coaching_prompt_revision="coaching-v3",
            speaker_roles=plan.request.speaker_roles,
        )
        # The stored request never contains a private name after fallback.
        assert b"Fictional Private Name" not in canonical(plan.intent())

    asyncio.run(exercise())
    assert (transcript, packet, roles) == before
