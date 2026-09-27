"""Dormant coaching-v6 selection and source-bound adapter integration checks."""

from __future__ import annotations

import hashlib
from copy import deepcopy
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest

from ac_platform.conversation_intelligence.analysis_settings import (
    DEFAULT_ANALYSIS_SETTINGS,
    AnalysisSettings,
)
from ac_platform.conversation_intelligence.application import ConversationDenied
from ac_platform.conversation_intelligence.checkpoints import canonical
from ac_platform.conversation_intelligence.coaching_schema import (
    coaching_generation_json_schema,
    coaching_response_json_schema,
)
from ac_platform.conversation_intelligence.gemini_tasks import gemini_prompt_view
from ac_platform.conversation_intelligence.inference import ConversationInference
from ac_platform.conversation_intelligence.inference_tasks import (
    InferenceTaskError,
    prepare_coaching_input,
    prepare_fact_inputs,
    validate_coaching_result,
    validate_fact_result,
)
from ac_platform.conversation_intelligence.openai_tasks import (
    openai_prompt_view,
)
from ac_platform.conversation_intelligence.qualitative_pack import (
    load_qualitative_pack_for_revision,
)
from ac_platform.conversation_intelligence.reporting_pipeline import StageRequest
from ac_platform.conversation_intelligence.reports import (
    COACHING_PROMPT_V6,
    COACHING_PROMPT_V6_MARKER,
    FactPacket,
    ReportError,
    build_report_groq_prompt,
    load_report_profile,
    parse_fact_packet,
    parse_report_draft,
    plan_transcript_chunks,
)
from ac_platform.conversation_intelligence.retained_c5_recovery import (
    _coaching_prompt_options,
)
from tests.conversation_overview_fixtures import overview_for
from tests.unit.conversation_intelligence.test_gemini_tasks import (
    coaching_case,
    envelope,
    facts,
    result,
)


def _v6_task(transcript: dict[str, Any], packet: FactPacket, *, provider: str, model: str):
    pack = load_qualitative_pack_for_revision(COACHING_PROMPT_V6)
    return prepare_coaching_input(
        transcript,
        [packet],
        provider=provider,
        model=model,
        max_completion_tokens=3_200,
        coaching_prompt_revision=COACHING_PROMPT_V6,
        report_language="mr-Deva+en",
        qualitative_pack_sha256=pack.sha256,
    )


@pytest.mark.asyncio
async def test_runtime_request_stage_blocks_v6_before_quote_or_allowance_work() -> None:
    application = SimpleNamespace(
        admit=AsyncMock(return_value=None),
        get=AsyncMock(),
    )
    authority = SimpleNamespace(require_execution_enabled=AsyncMock())
    service = object.__new__(ConversationInference)
    service.application = application
    service.authority = authority
    request = StageRequest(
        stage="C5",
        transcript_checkpoint_id=uuid4(),
        fact_checkpoint_ids=(uuid4(),),
        provider="openai",
        model="gpt-6-luna",
        max_completion_tokens=512,
        coaching_prompt_revision=COACHING_PROMPT_V6,
        report_language="en",
        qualitative_pack_sha256=load_qualitative_pack_for_revision(COACHING_PROMPT_V6).sha256,
    )

    with pytest.raises(ConversationDenied, match="AC-SVAL-01 Gate 2"):
        await service.request_stage(
            SimpleNamespace(),
            uuid4(),
            uuid4(),
            key="blocked-v6-runtime-stage",
            request=request,
        )

    authority.require_execution_enabled.assert_awaited_once_with(application)
    application.get.assert_not_awaited()


def _dimension_complete_draft(transcript: dict[str, Any]) -> dict[str, Any]:
    _, _, draft = coaching_case()
    draft["dimensions"] = [
        {
            "dimension_id": item["id"],
            "status": "observed",
            "observation": (
                "The source supports this observation; the useful action is limited to this call."
            ),
            "evidence": [{"segment_id": "s1"}],
        }
        for item in load_report_profile()["dimensions"]
    ]
    draft["overview"] = overview_for(deepcopy(draft))
    return draft


def _fixture():
    transcript, _, _ = coaching_case()
    fact_task = prepare_fact_inputs(transcript, provider="gemini", model="gemini-3.8-flash")[0]
    packet = FactPacket.model_validate(
        validate_fact_result(
            result(fact_task, envelope(facts(transcript))), fact_task, transcript
        ).data()
    )
    return transcript, packet


@pytest.mark.parametrize("language", ["en", "hi-Deva+en", "mr-Deva+en"])
def test_v6_requires_explicit_selection_and_keeps_default_and_budget(language: str) -> None:
    selected = AnalysisSettings.model_validate(
        {
            **DEFAULT_ANALYSIS_SETTINGS.model_dump(),
            "c5_coaching_prompt_revision": "coaching-v6",
            "report_language_default": language,
        }
    )
    assert selected.c5_coaching_prompt_revision == "coaching-v6"
    assert DEFAULT_ANALYSIS_SETTINGS.c5_coaching_prompt_revision == "coaching-v3"
    assert selected.c5_max_completion_tokens == DEFAULT_ANALYSIS_SETTINGS.c5_max_completion_tokens


def test_v6_prompt_is_pack_pinned_source_language_safe_and_not_a_scoring_prompt() -> None:
    transcript = {
        "source_sha256": "a" * 64,
        "revision": "scribe-response-r1",
        "timebase_id": "elevenlabs-scribe-native-seconds",
        "duration_ms": 2_000,
        "segments": [
            {
                "id": "s1",
                "speaker_id": "speaker_1",
                "start_ms": 0,
                "end_ms": 900,
                "text": "I can check with my co-owner.",
            },
            {
                "id": "s2",
                "speaker_id": "unattributed",
                "start_ms": 1_000,
                "end_ms": 1_900,
                "text": "I do not have a date yet.",
            },
        ],
    }
    chunks = plan_transcript_chunks(transcript, max_input_chars=900)
    packets = [
        parse_fact_packet(
            {
                "overview": "An unscheduled co-owner discussion is mentioned.",
                "observations": [],
                "uncertainties": [],
            },
            transcript,
            chunk=chunk,
        )
        for chunk in chunks
    ]
    pack = load_qualitative_pack_for_revision(COACHING_PROMPT_V6)
    prompt = build_report_groq_prompt(
        transcript,
        packets,
        provider="gemini",
        model="gemini-3.8-flash",
        max_completion_tokens=3_200,
        coaching_prompt_revision=COACHING_PROMPT_V6,
        report_language="hi-Deva+en",
        qualitative_pack_sha256=pack.sha256,
    )
    system = prompt["messages"][0]["content"]
    assert pack.id == "sx-qualitative-v6-r1"
    assert COACHING_PROMPT_V6_MARKER in system
    assert "COACHING_DEPTH: evidence-meaning-action-v5." not in system
    assert "REPORT_LANGUAGE: hi-Deva+en." in system
    assert "seller scores" in system
    assert "no numerical evaluation" in system
    assert "2-4 sentences" not in system
    assert "Each supported improvement: useful action+sample phrase" in system
    assert "strengths and unsupported findings do not require one" in system
    with pytest.raises(ReportError, match="report_qualitative_pack_mismatch"):
        build_report_groq_prompt(
            transcript,
            packets,
            provider="gemini",
            model="gemini-3.8-flash",
            max_completion_tokens=3_200,
            coaching_prompt_revision=COACHING_PROMPT_V6,
            report_language="hi-Deva+en",
            qualitative_pack_sha256="0" * 64,
        )
    with pytest.raises(ReportError, match="report_v6_route_unsupported"):
        build_report_groq_prompt(
            transcript,
            packets,
            coaching_prompt_revision=COACHING_PROMPT_V6,
            report_language="hi-Deva+en",
            qualitative_pack_sha256=pack.sha256,
        )


def test_v6_roundtrips_gemini_and_openai_contracts_and_source_bound_report() -> None:
    transcript, packet = _fixture()
    pack = load_qualitative_pack_for_revision(COACHING_PROMPT_V6)

    request = StageRequest(
        stage="C5",
        transcript_checkpoint_id=uuid4(),
        fact_checkpoint_ids=(uuid4(),),
        provider="gemini",
        model="gemini-3.8-flash",
        max_completion_tokens=3_200,
        coaching_prompt_revision=COACHING_PROMPT_V6,
        report_language="mr-Deva+en",
        qualitative_pack_sha256=pack.sha256,
    )
    assert request.coaching_prompt_revision == COACHING_PROMPT_V6
    assert _coaching_prompt_options(
        {
            "coaching_prompt_revision": COACHING_PROMPT_V6,
            "report_language": "mr-Deva+en",
            "qualitative_pack_sha256": pack.sha256,
        }
    ) == (COACHING_PROMPT_V6, "mr-Deva+en", pack.sha256)

    gemini = _v6_task(transcript, packet, provider="gemini", model="gemini-3.8-flash")
    body = gemini.as_provider_body()
    assert body["generationConfig"]["responseJsonSchema"] == coaching_generation_json_schema(
        COACHING_PROMPT_V6
    )
    assert body["systemInstruction"]["parts"][0]["text"].startswith(
        "AC_TASK_ADAPTER: gemini-json-v5\n"
    )
    assert type(gemini).from_dict(gemini.as_dict(), payload=gemini.payload) == gemini
    assert gemini_prompt_view(body, model=gemini.model, maximum=3_200, task="coaching")

    openai = _v6_task(transcript, packet, provider="openai", model="gpt-6-luna")
    openai_body = openai.as_provider_body()
    assert openai_body["text"]["format"]["name"] == "sales_xray_coaching_v6"
    openai_dimension = openai_body["text"]["format"]["schema"]["$defs"]["dimension"]
    assert "evidence" in openai_dimension["anyOf"][0]["properties"]
    assert openai_prompt_view(openai_body, model="gpt-6-luna", maximum=3_200, task="coaching")

    draft = _dimension_complete_draft(transcript)
    output = validate_coaching_result(result(gemini, envelope(draft)), gemini, transcript).data()
    assert len(output["dimensions"]) == 8
    assert output["dimensions"][0]["evidence"][0]["quote"]
    canonical_read = parse_report_draft(output, transcript, canonical_read=True)
    assert canonical_read.model_dump(mode="json") == output


@pytest.mark.parametrize("mutation", ["old_adapter_marker", "missing_v6_marker"])
def test_v6_gemini_rejects_downgraded_revision_metadata(mutation: str) -> None:
    transcript, packet = _fixture()
    task = _v6_task(transcript, packet, provider="gemini", model="gemini-3.8-flash")
    body = task.as_provider_body()
    if mutation == "old_adapter_marker":
        prefix = body["systemInstruction"]["parts"][0]
        prefix["text"] = prefix["text"].replace("gemini-json-v5", "gemini-json-v4", 1)
    else:
        prefix = body["systemInstruction"]["parts"][0]
        prefix["text"] = prefix["text"].replace(COACHING_PROMPT_V6_MARKER, "", 1)
    raw = canonical(body)
    payload_sha256 = hashlib.sha256(raw).hexdigest()
    forged_metadata = task.as_dict()
    forged_metadata["input_sha256"] = payload_sha256
    forged_metadata["payload_sha256"] = payload_sha256
    with pytest.raises(InferenceTaskError, match="task_payload_metadata_mismatch"):
        type(task).from_dict(forged_metadata, payload=raw)


def test_v6_response_schema_adds_evidence_only_as_a_versioned_shape() -> None:
    v5 = coaching_response_json_schema("coaching-v5")
    v6 = coaching_response_json_schema("coaching-v6")
    assert v6 == v5
    assert coaching_generation_json_schema("coaching-v6") == coaching_generation_json_schema(
        "coaching-v5"
    )
