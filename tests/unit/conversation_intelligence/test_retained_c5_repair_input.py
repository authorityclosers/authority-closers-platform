"""Retained recovery must reconstruct the exact saved repair request bytes."""

from copy import deepcopy
from uuid import UUID

import pytest
from pydantic import ValidationError

from ac_platform.conversation_intelligence.contracts import C5RepairIntent
from ac_platform.conversation_intelligence.inference_tasks import prepare_coaching_input
from ac_platform.conversation_intelligence.qualitative_pack import (
    load_qualitative_pack_for_revision,
)
from ac_platform.conversation_intelligence.reporting_pipeline import repair_coaching_input
from ac_platform.conversation_intelligence.reports import FactPacket, load_report_profile
from ac_platform.conversation_intelligence.retained_c5_recovery import _rebuild_prepared_c5_input
from tests.unit.conversation_intelligence.test_retained_c5_recovery import _coaching_transcript


def _fixture(provider: str, model: str):
    transcript = _coaching_transcript()
    facts = FactPacket.model_validate(
        {
            "schema": "ac.sales-xray.style-independent-facts/1",
            "source_sha256": transcript["source_sha256"],
            "transcript_revision": transcript["revision"],
            "timebase_id": transcript["timebase_id"],
            "chunk_index": 1,
            "chunk_count": 1,
            "covered_segment_ids": ["seg-1"],
            "overview": "The buyer asked about price and timing.",
            "observations": [],
            "uncertainties": [],
        }
    )
    request = {
        "coaching_prompt_revision": "coaching-v5",
        "report_language": "en",
        "qualitative_pack_sha256": load_qualitative_pack_for_revision("coaching-v5").sha256,
        "output_profile": "detailed",
    }
    base = prepare_coaching_input(transcript, [facts], provider=provider, model=model, **request)
    repair = C5RepairIntent(
        failure_code="conversation_report_overview_invalid",
        original_run_id=UUID("00000000-0000-0000-0000-000000000001"),
        original_response_sha256="a" * 64,
    )
    return transcript, facts, request, base, repair


@pytest.mark.parametrize(
    "provider,model",
    [("gemini", "gemini-3.8-flash"), ("groq", "openai/gpt-oss-120b")],
)
def test_retained_repair_rebuild_matches_the_dispatched_input(provider, model):
    transcript, facts, request, base, repair = _fixture(provider, model)
    dispatched = repair_coaching_input(base, repair)
    saved_request = {**request, "repair": repair.model_dump(mode="json")}
    before = deepcopy((transcript, facts, saved_request))

    rebuilt = _rebuild_prepared_c5_input(
        transcript,
        (facts,),
        profile=load_report_profile(),
        input_metadata=dispatched.as_dict(),
        request=saved_request,
    )

    assert rebuilt.payload == dispatched.payload
    assert rebuilt.input_sha256 == dispatched.input_sha256
    assert rebuilt.input_sha256 != base.input_sha256
    assert (transcript, facts, saved_request) == before


def test_retained_repair_rebuild_rejects_a_second_attempt():
    transcript, facts, request, base, repair = _fixture("gemini", "gemini-3.8-flash")
    with pytest.raises(ValidationError):
        _rebuild_prepared_c5_input(
            transcript,
            (facts,),
            profile=load_report_profile(),
            input_metadata=base.as_dict(),
            request={**request, "repair": {**repair.model_dump(mode="json"), "attempt": 2}},
        )
