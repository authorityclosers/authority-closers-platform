"""Versioned provider/plan boundaries, using synthetic input and no dispatch."""

import hashlib
from dataclasses import replace
from types import SimpleNamespace
from uuid import uuid4

import pytest

from ac_platform.conversation_intelligence.analysis_settings import (
    DEFAULT_ANALYSIS_SETTINGS,
    AnalysisSettings,
)
from ac_platform.conversation_intelligence.application import ConversationConflict
from ac_platform.conversation_intelligence.checkpoints import canonical, content_hash
from ac_platform.conversation_intelligence.coaching_schema import coaching_generation_json_schema
from ac_platform.conversation_intelligence.gemini_tasks import gemini_prompt_view
from ac_platform.conversation_intelligence.inference_tasks import (
    InferenceTaskError,
    prepare_coaching_input,
    prepare_fact_inputs,
    validate_coaching_result,
    validate_fact_result,
)
from ac_platform.conversation_intelligence.qualitative_pack import (
    load_qualitative_pack_for_revision,
)
from ac_platform.conversation_intelligence.report_store import ConversationReports
from ac_platform.conversation_intelligence.reporting_pipeline import StageRequest
from ac_platform.conversation_intelligence.reports import (
    FactPacket,
    load_report_profile,
    parse_report_draft,
)
from ac_platform.conversation_intelligence.retained_c5_recovery import _coaching_prompt_options
from tests.unit.conversation_intelligence.test_gemini_tasks import (
    coaching_case,
    envelope,
    facts,
    result,
)


def successor_case():
    transcript, _, draft = coaching_case()
    fact_input = prepare_fact_inputs(transcript, provider="gemini", model="gemini-3.8-flash")[0]
    packet = FactPacket.model_validate(
        validate_fact_result(
            result(fact_input, envelope(facts(transcript))), fact_input, transcript
        ).data()
    )
    task = prepare_coaching_input(
        transcript,
        [packet],
        provider="gemini",
        model="gemini-3.8-flash",
        max_completion_tokens=3200,
        coaching_prompt_revision="coaching-v5",
        report_language="en",
        qualitative_pack_sha256=load_qualitative_pack_for_revision("coaching-v5").sha256,
    )
    draft["dimensions"] = [
        {
            "dimension_id": item["id"],
            "status": "observed",
            "observation": "The buyer asks about timing. Ask what timing means for the decision.",
            "evidence": [{"segment_id": "s1"}],
        }
        for item in load_report_profile()["dimensions"]
    ]
    return transcript, task, draft


@pytest.mark.parametrize("language", ["en", "hi-Deva+en", "mr-Deva+en"])
def test_settings_allow_explicit_successor_without_altering_default(language):
    value = AnalysisSettings.model_validate(
        {
            **DEFAULT_ANALYSIS_SETTINGS.model_dump(),
            "c5_coaching_prompt_revision": "coaching-v5",
            "report_language_default": language,
        }
    )
    assert value.c5_coaching_prompt_revision == "coaching-v5"
    assert DEFAULT_ANALYSIS_SETTINGS.c5_coaching_prompt_revision == "coaching-v3"
    assert value.c5_max_completion_tokens == DEFAULT_ANALYSIS_SETTINGS.c5_max_completion_tokens


@pytest.mark.parametrize("revision", ["coaching-v4", "coaching-v5"])
def test_stage_and_recovery_bind_each_version_to_its_own_pack(revision):
    options = {
        "coaching_prompt_revision": revision,
        "report_language": "mr-Deva+en",
        "qualitative_pack_sha256": load_qualitative_pack_for_revision(revision).sha256,
    }
    stage = dict(stage="C5", transcript_checkpoint_id=uuid4(), fact_checkpoint_ids=(uuid4(),))
    assert StageRequest(**stage, **options).coaching_prompt_revision == revision
    assert _coaching_prompt_options(options) == tuple(options.values())
    other = "coaching-v5" if revision == "coaching-v4" else "coaching-v4"
    wrong = {**options, "qualitative_pack_sha256": load_qualitative_pack_for_revision(other).sha256}
    with pytest.raises(ValueError):
        StageRequest(**stage, **wrong)
    with pytest.raises(ValueError):
        _coaching_prompt_options(wrong)


def test_v5_uses_distinct_native_schema_and_round_trips_immutable_input():
    _, task, _ = successor_case()
    body = task.as_provider_body()
    assert body["generationConfig"]["responseJsonSchema"] == coaching_generation_json_schema(
        "coaching-v5"
    )
    assert body["systemInstruction"]["parts"][0]["text"].startswith(
        "AC_TASK_ADAPTER: gemini-json-v4\n"
    )
    assert type(task).from_dict(task.as_dict(), payload=task.payload) == task
    assert body["generationConfig"]["maxOutputTokens"] == 3200
    assert gemini_prompt_view(body, model=task.model, maximum=3200, task="coaching")


@pytest.mark.parametrize(
    "mutation", ["old_schema", "old_marker", "missing_depth_marker", "legacy_without_schema"]
)
def test_v5_rejects_downgraded_contract_even_with_rehashed_payload(mutation):
    _, task, _ = successor_case()
    body = task.as_provider_body()
    if mutation == "old_schema":
        body["generationConfig"]["responseJsonSchema"] = coaching_generation_json_schema()
    else:
        part = body["systemInstruction"]["parts"][0]
        if mutation == "legacy_without_schema":
            body["generationConfig"].pop("responseJsonSchema")
            part["text"] = part["text"].replace("gemini-json-v4", "gemini-json-v1", 1)
        elif mutation == "old_marker":
            part["text"] = part["text"].replace("gemini-json-v4", "gemini-json-v3", 1)
        else:
            part["text"] = part["text"].replace(
                "COACHING_DEPTH: evidence-meaning-action-v5.", "", 1
            )
    raw = canonical(body)
    with pytest.raises(InferenceTaskError, match="task_payload_metadata_mismatch"):
        replace(task, payload=raw, input_sha256=hashlib.sha256(raw).hexdigest())


def test_v5_evidence_survives_provider_validation_and_canonical_reread():
    transcript, task, draft = successor_case()
    output = validate_coaching_result(result(task, envelope(draft)), task, transcript).data()
    assert output["dimensions"][0]["evidence"][0]["quote"] == transcript["segments"][0]["text"]
    assert output["dimensions"][0]["citations"]
    reread = parse_report_draft(output, transcript, canonical_read=True)
    assert reread.model_dump(mode="json") == output
    draft["dimensions"][0].pop("evidence")
    with pytest.raises(InferenceTaskError):
        validate_coaching_result(result(task, envelope(draft)), task, transcript)


def test_saved_v5_report_store_revalidates_skill_evidence_without_losing_it():
    transcript, _, draft = successor_case()
    transcript["revision"] = "b" * 64
    profile = load_report_profile()
    canonical_report = parse_report_draft(
        draft, transcript, coaching_prompt_revision="coaching-v5"
    ).model_dump(mode="json")
    recording = SimpleNamespace(
        id=uuid4(),
        tenant_id=uuid4(),
        person_id=uuid4(),
        source_revision=1,
        source_sha256=transcript["source_sha256"],
    )
    proof = {
        "schema_id": "ac.sales-xray.durable-draft-proof/1",
        "transcript_checkpoint_id": str(uuid4()),
        "transcription_task_id": str(uuid4()),
        "transcription_response_sha256": transcript["revision"],
        "coaching_checkpoint_id": str(uuid4()),
        "presentation_checkpoint_id": str(uuid4()),
        "coaching_response_sha256": "c" * 64,
        "accepted_quote_id": str(uuid4()),
        "profile_sha256": content_hash(profile),
        "human_approved": False,
        "numeric_publication": False,
    }
    source = {
        "normalized": transcript,
        "profile": profile,
        "native_response_ref": {
            "task_id": proof["transcription_task_id"],
            "response_sha256": transcript["revision"],
        },
    }
    stored = SimpleNamespace(
        recording_id=recording.id,
        tenant_id=recording.tenant_id,
        person_id=recording.person_id,
        source_revision=recording.source_revision,
        source_sha256=recording.source_sha256,
        erased_at=None,
        payload=canonical_report,
        report_sha256=content_hash(canonical_report),
        transcript=source,
        transcript_sha256=content_hash(source),
        evidence_receipt=proof,
        evidence_receipt_sha256=content_hash(proof),
        profile_sha256=content_hash(profile),
    )
    read, _ = ConversationReports._validated(stored, recording)
    assert read.model_dump(mode="json") == canonical_report
    stored.payload["dimensions"][0]["evidence"][0]["quote"] = "Not present in the source."
    stored.report_sha256 = content_hash(stored.payload)
    with pytest.raises(ConversationConflict, match="needs review"):
        ConversationReports._validated(stored, recording)
