"""Versioned C5 wording with byte-stable legacy requests."""

from __future__ import annotations

import hashlib
import json
from types import SimpleNamespace
from typing import cast
from uuid import uuid4

import pytest

from ac_platform.conversation_intelligence.application import ConversationDenied
from ac_platform.conversation_intelligence.checkpoints import (
    Checkpoint,
    SourceBinding,
    build_checkpoint,
    canonical,
    content_hash,
)
from ac_platform.conversation_intelligence.inference_tasks import (
    PreparedTaskInput,
    prepare_coaching_input,
)
from ac_platform.conversation_intelligence.processing_plan import (
    NEW_PLAN_COACHING_PROMPT_REVISION,
    PlanManifest,
    manifest_for,
    require_derived_input,
)
from ac_platform.conversation_intelligence.report_overview import stage_completion_limit
from ac_platform.conversation_intelligence.reporting_pipeline import (
    COACHING_RECIPE,
    FACT_RECIPE,
    ReportingPipeline,
    StagePlan,
    StageRequest,
)
from ac_platform.conversation_intelligence.reports import (
    COACHING_PROMPT_LEGACY,
    COACHING_PROMPT_REFINED,
    COACHING_PROMPT_REFINED_MARKER,
    COACHING_PROMPT_V3,
    COACHING_PROMPT_V3_MARKER,
    FactPacket,
    parse_fact_packet,
)
from tests.unit.conversation_intelligence.test_processing_plan import saved_plan
from tests.unit.conversation_intelligence.test_reports import _transcript


def _packet() -> tuple[dict[str, object], FactPacket]:
    transcript = _transcript(count=1)
    packet = parse_fact_packet(
        {"overview": "One source fact.", "observations": [], "uncertainties": []},
        transcript,
    )
    return transcript, packet


def test_legacy_c5_request_and_payload_remain_byte_stable() -> None:
    transcript, packet = _packet()
    implicit = prepare_coaching_input(
        transcript, [packet], provider="gemini", model="gemini-3.8-flash"
    )
    explicit = prepare_coaching_input(
        transcript,
        [packet],
        provider="gemini",
        model="gemini-3.8-flash",
        coaching_prompt_revision=COACHING_PROMPT_LEGACY,
    )

    assert implicit.payload == explicit.payload
    assert implicit.input_sha256 == explicit.input_sha256
    assert hashlib.sha256(implicit.payload).hexdigest() == (
        "64af8836fd25fa7d1300b3dbdbac648cfe38ea874b323059837624c88d29b461"
    )
    request = StageRequest(
        stage="C5",
        transcript_checkpoint_id=uuid4(),
        fact_checkpoint_ids=(uuid4(),),
    )
    assert "coaching_prompt_revision" not in request.model_dump(mode="json")
    assert StageRequest.model_validate(request.model_dump(mode="json")) == request


def test_refined_c5_prompt_changes_only_the_versioned_coaching_input() -> None:
    transcript, packet = _packet()
    legacy = prepare_coaching_input(
        transcript, [packet], provider="gemini", model="gemini-3.8-flash"
    )
    refined = prepare_coaching_input(
        transcript,
        [packet],
        provider="gemini",
        model="gemini-3.8-flash",
        coaching_prompt_revision=COACHING_PROMPT_REFINED,
    )

    assert legacy.input_sha256 != refined.input_sha256
    assert COACHING_PROMPT_REFINED_MARKER not in legacy.payload.decode()
    assert COACHING_PROMPT_REFINED_MARKER in refined.payload.decode()
    assert "Say declined or refused only for an explicit source-recorded rejection." in (
        refined.payload.decode()
    )
    assert hashlib.sha256(refined.payload).hexdigest() == (
        "e372f0681ac1c584b50c72713a260f05969d386c89c7f0653516c23336a83526"
    )
    assert refined.transcript_revision == legacy.transcript_revision
    assert refined.source_sha256 == legacy.source_sha256


def test_source_bound_v3_prompt_uses_safe_evidence_and_supported_phrase_guidance() -> None:
    transcript, packet = _packet()
    legacy = prepare_coaching_input(
        transcript, [packet], provider="gemini", model="gemini-3.8-flash"
    )
    refined = prepare_coaching_input(
        transcript,
        [packet],
        provider="gemini",
        model="gemini-3.8-flash",
        coaching_prompt_revision=COACHING_PROMPT_REFINED,
    )
    v3 = prepare_coaching_input(
        transcript,
        [packet],
        provider="gemini",
        model="gemini-3.8-flash",
        coaching_prompt_revision=COACHING_PROMPT_V3,
    )
    prompt = v3.payload.decode()

    assert len({legacy.input_sha256, refined.input_sha256, v3.input_sha256}) == 3
    assert COACHING_PROMPT_V3_MARKER in prompt
    assert COACHING_PROMPT_REFINED_MARKER in prompt
    assert "prefer evidence {segment_id} alone" in prompt
    assert "zero-based Python Unicode code-point indices" in prompt
    assert "with an exclusive end" in prompt
    assert "never milliseconds or audio timestamps" in prompt
    assert "server resolves the exact quote and native timestamps" in prompt
    assert "do not invent or assume seller product terms, prices, schedules, features" in prompt
    assert "ask a neutral question" in prompt


def test_legacy_c5_checkpoint_identity_has_no_revision_key_and_v2_does() -> None:
    binding = SourceBinding("tenant", "recording", "a" * 64, "1")
    root = Checkpoint(binding, "C0", "source-v1", "{}", (), "b" * 64)
    c1 = build_checkpoint(binding, "C1", "measurement-v1", {}, (root,), "c" * 64)
    c2 = build_checkpoint(binding, "C2", "transcript-v1", {}, (root,), "d" * 64)
    c3 = build_checkpoint(binding, "C3", "alignment-v1", {}, (c1, c2), "e" * 64)
    parent = build_checkpoint(
        binding,
        "C4",
        "source-facts-complete-v1",
        {"chunk_manifests": ["b" * 64]},
        (c2, c3),
        "f" * 64,
    )
    base_config = {
        "input_sha256": "e" * 64,
        "provider": "gemini",
        "model": "gemini-3.8-flash",
        "profile_sha256": "f" * 64,
    }
    legacy = build_checkpoint(binding, "C5", COACHING_RECIPE, base_config, (parent,), "0" * 64)
    legacy_replay = build_checkpoint(
        binding, "C5", COACHING_RECIPE, dict(base_config), (parent,), "0" * 64
    )
    refined = build_checkpoint(
        binding,
        "C5",
        COACHING_RECIPE,
        {**base_config, "coaching_prompt_revision": COACHING_PROMPT_REFINED},
        (parent,),
        "0" * 64,
    )

    assert legacy.config_json == legacy_replay.config_json
    assert legacy.cache_key == legacy_replay.cache_key
    assert "coaching_prompt_revision" not in canonical(base_config).decode()
    assert refined.cache_key != legacy.cache_key


def test_manifest_and_derived_request_pin_the_refined_revision() -> None:
    legacy = manifest_for(saved_plan())
    assert NEW_PLAN_COACHING_PROMPT_REVISION == COACHING_PROMPT_V3
    assert legacy.coaching_prompt_revision == COACHING_PROMPT_LEGACY
    assert "coaching_prompt_revision" not in legacy.as_dict()
    for recorded_revision in (COACHING_PROMPT_LEGACY, COACHING_PROMPT_REFINED):
        recorded = legacy.as_dict()
        if recorded_revision != COACHING_PROMPT_LEGACY:
            recorded["coaching_prompt_revision"] = recorded_revision
        assert (
            PlanManifest.model_validate_json(canonical(recorded)).coaching_prompt_revision
            == recorded_revision
        )
    refined_manifest = legacy.model_copy(
        update={"coaching_prompt_revision": NEW_PLAN_COACHING_PROMPT_REVISION}
    )
    encoded = refined_manifest.as_dict()
    assert encoded["coaching_prompt_revision"] == COACHING_PROMPT_V3
    assert (
        PlanManifest.model_validate_json(canonical(encoded)).coaching_prompt_revision
        == COACHING_PROMPT_V3
    )

    approval = refined_manifest.stages[2]
    request = StageRequest(
        stage="C5",
        transcript_checkpoint_id=uuid4(),
        fact_checkpoint_ids=(uuid4(),),
        provider=approval.provider_id,
        model=approval.model_id,
        max_input_chars=refined_manifest.max_input_chars,
        max_completion_tokens=stage_completion_limit(
            "C5",
            approval.max_completion_tokens,
            provider=approval.provider_id,
            model=approval.model_id,
        ),
        coaching_prompt_revision=COACHING_PROMPT_V3,
        profile=refined_manifest.profile,
    )
    reconstructed = StageRequest.model_validate(request.model_dump(mode="json"))
    assert reconstructed.coaching_prompt_revision == COACHING_PROMPT_V3
    checkpoint = Checkpoint(
        SourceBinding("tenant", "recording", "a" * 64, "1"),
        "C5",
        COACHING_RECIPE,
        canonical({"input_sha256": "a" * 64}).decode(),
        (("C4", "b" * 64),),
        "c" * 64,
    )
    plan = StagePlan(
        cast(PreparedTaskInput, SimpleNamespace()),
        checkpoint,
        1_000,
        reconstructed,
        {},
        {},
        refined_manifest.profile,
    )
    require_derived_input(refined_manifest, plan)
    with pytest.raises(ConversationDenied, match="derived request"):
        require_derived_input(
            refined_manifest,
            plan.__class__(
                plan.prepared,
                plan.checkpoint,
                plan.duration_ms,
                reconstructed.model_copy(
                    update={"coaching_prompt_revision": COACHING_PROMPT_LEGACY}
                ),
                plan.transcript,
                plan.native_transcript,
                plan.profile,
            ),
        )


def test_c4_cannot_select_a_coaching_prompt_revision() -> None:
    with pytest.raises(ValueError, match="coaching prompt revision"):
        StageRequest(
            stage="C4",
            transcript_checkpoint_id=uuid4(),
            coaching_prompt_revision=COACHING_PROMPT_REFINED,
        )


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "revision", [COACHING_PROMPT_LEGACY, COACHING_PROMPT_REFINED, COACHING_PROMPT_V3]
)
async def test_reporting_pipeline_pins_legacy_or_refined_c5_checkpoint_config(
    revision: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    from ac_platform.conversation_intelligence import alignment

    transcript, packet = _packet()
    binding = SourceBinding("tenant", "recording", "a" * 64, "1")
    c0 = Checkpoint(binding, "C0", "source-v1", "{}", (), "b" * 64)
    c1 = build_checkpoint(binding, "C1", "measurement-v1", {}, (c0,), "c" * 64)
    c2 = build_checkpoint(binding, "C2", "transcript-v1", {}, (c0,), "d" * 64)
    c3 = build_checkpoint(binding, "C3", "source-clock-support-v1", {}, (c1, c2), content_hash({}))
    c4 = build_checkpoint(
        binding,
        "C4",
        FACT_RECIPE,
        {"chunk_index": 1},
        (c2, c3),
        content_hash(packet.model_dump(mode="json")),
    )
    c1_row = SimpleNamespace(payload={"media_duration_ms": 1_000})
    c2_row = SimpleNamespace(payload=transcript)
    c4_row = SimpleNamespace(id=uuid4(), payload=packet.model_dump(mode="json"))
    source = SimpleNamespace(signal_id=uuid4(), checkpoint=c2, duration_ms=1_000)
    recording = SimpleNamespace(
        id="recording",
        tenant_id="tenant",
        source_sha256="a" * 64,
        source_revision=1,
    )

    async def plan_transcription(_recording: object) -> object:
        return source

    service = SimpleNamespace(database=object(), plan_transcription=plan_transcription)
    pipeline = ReportingPipeline(service)

    async def checkpoint(_recording: object, _identifier: object, stage: str):
        if stage == "C1":
            return c1_row, c1
        if stage == "C2":
            return c2_row, c2
        return c4_row, c4

    async def provider_task(_recording: object, row: object):
        if row is c2_row:
            return None, {"response_sha256": transcript["revision"]}
        return None, {}

    async def save(*_args: object, **_kwargs: object) -> None:
        return None

    monkeypatch.setattr(alignment, "build_alignment", lambda *_args, **_kwargs: {})
    monkeypatch.setattr(
        alignment,
        "project_transcript_for_playback",
        lambda native, **_kwargs: native,
    )
    pipeline.checkpoint = checkpoint  # type: ignore[method-assign]
    pipeline.provider_task = provider_task  # type: ignore[method-assign]
    pipeline.save = save  # type: ignore[method-assign]
    request = StageRequest(
        stage="C5",
        transcript_checkpoint_id=uuid4(),
        fact_checkpoint_ids=(uuid4(),),
        coaching_prompt_revision=revision,  # type: ignore[arg-type]
    )

    plan = await pipeline.plan(recording, request)
    config = json.loads(plan.checkpoint.config_json)
    assert config["input_sha256"] == plan.prepared.input_sha256
    if revision == COACHING_PROMPT_LEGACY:
        assert set(config) == {"input_sha256", "model", "profile_sha256", "provider"}
    else:
        assert config["coaching_prompt_revision"] == revision
