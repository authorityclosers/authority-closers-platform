"""Synthetic reproduction of ambiguous nested evidence object/list instructions."""

import json
import re
from copy import deepcopy
from typing import Any

import pytest
from pydantic import ValidationError

from ac_platform.conversation_intelligence import reports
from ac_platform.conversation_intelligence.inference_tasks import (
    prepare_coaching_input,
    prepare_fact_inputs,
    prepare_scribe_input,
)
from ac_platform.conversation_intelligence.report_overview import (
    OVERVIEW_FORMAT,
    DetailedOverview,
)
from tests.conversation_overview_fixtures import overview_for
from tests.unit.conversation_intelligence.test_reports import _evidence, _payload, _transcript

EVIDENCE_PATHS = (
    ("diagnosis",),
    ("outcome",),
    ("improvement_details", 0, "what_happened"),
    ("missed_details", 0, "prospect_signal"),
    ("missed_details", 0, "closer_response"),
    ("prospect_interpretations", 0, "source"),
    ("rewatch", 0),
    ("conversation_change", "before"),
    ("conversation_change", "change"),
    ("conversation_change", "after"),
    ("ethics_notes", 0),
)


def full_overview_case() -> tuple[dict[str, Any], dict[str, Any]]:
    transcript = _transcript()
    draft = _payload(transcript)
    overview = overview_for(draft)

    def note(index: int = 0) -> dict[str, Any]:
        return {"text": "A synthetic source moment.", "evidence": [_evidence(transcript, index)]}

    overview.update(
        diagnosis=note(),
        outcome={"kind": "unclear", **note()},
        missed_details=[
            {
                "finding_index": 0,
                "prospect_signal": note(),
                "closer_response": note(1),
                "follow_up": "Ask a follow-up question.",
                "potential_impact": "This may clarify the stated problem.",
            }
        ],
        prospect_interpretations=[
            {
                "source": note(),
                "possible_concern": "A possible concern.",
                "interpretation_kind": "inference",
            }
        ],
        rewatch=[{"purpose": "watch", **note()}],
        conversation_change={
            "before": note(),
            "change": note(1),
            "after": note(2),
            "possible_effect": "This may have changed the next question.",
            "interpretation_kind": "inference",
        },
        ethics_notes=[note()],
    )
    draft["overview"] = overview
    return transcript, draft


def test_all_eleven_nested_paths_have_an_explicit_array_in_the_prompt() -> None:
    shape = json.dumps(OVERVIEW_FORMAT)
    assert len(re.findall(r"\bevidence:\[span\]", shape)) == len(EVIDENCE_PATHS)
    assert len(re.findall(r"\bevidence\b", shape)) == len(EVIDENCE_PATHS)
    transcript, draft = full_overview_case()
    original = deepcopy(draft)
    parsed = reports.parse_report_draft(draft, transcript)
    assert parsed.overview is not None
    assert parsed.overview.model_dump(mode="json") == draft["overview"]
    assert draft == original


@pytest.mark.parametrize("path", EVIDENCE_PATHS)
def test_schema_requires_array_at_each_nested_evidence_path(path: tuple[str | int, ...]) -> None:
    _, draft = full_overview_case()
    note = draft["overview"]
    for key in path:
        note = note[key]
    note["evidence"] = note["evidence"][0]
    with pytest.raises(ValidationError) as exc:
        DetailedOverview.model_validate(draft["overview"])
    assert [(error["loc"], error["type"]) for error in exc.value.errors()] == [
        ((*path, "evidence"), "list_type")
    ]


@pytest.mark.parametrize(
    ("provider", "model"),
    [("gemini", "gemini-3.8-flash"), ("groq", "openai/gpt-oss-120b")],
)
def test_array_contract_binds_only_new_c5_and_keeps_native_provider_shape(
    monkeypatch: pytest.MonkeyPatch, provider: str, model: str
) -> None:
    transcript = _transcript()
    c2 = prepare_scribe_input(transcript["source_sha256"], 1000)
    c4 = prepare_fact_inputs(transcript, provider=provider, model=model)
    packet = reports.parse_fact_packet(
        {"overview": "A synthetic call.", "observations": [], "uncertainties": []}, transcript
    )
    with monkeypatch.context() as old:
        old.setattr(reports, "OVERVIEW_INSTRUCTION", "")
        old.setattr(
            reports,
            "OVERVIEW_FORMAT",
            {
                k: v.replace("evidence:[span]", "evidence") if isinstance(v, str) else v
                for k, v in OVERVIEW_FORMAT.items()
            },
        )
        previous = prepare_coaching_input(transcript, [packet], provider=provider, model=model)
    current = prepare_coaching_input(transcript, [packet], provider=provider, model=model)
    assert type(current).from_dict(current.as_dict(), payload=current.payload) == current
    assert previous.input_sha256 != current.input_sha256
    assert current.max_completion_tokens == previous.max_completion_tokens
    assert current.profile_revision == previous.profile_revision
    assert current.transcript_revision == previous.transcript_revision
    body = current.as_provider_body()
    system = (
        body["systemInstruction"]["parts"][0]["text"]
        if provider == "gemini"
        else body["messages"][0]["content"]
    )
    assert "EVIDENCE_ARRAYS: v1" in system
    assert "nonempty JSON array of span objects, even for one" in system
    assert "span={segment_id,quote,start_ms,end_ms}" in system
    assert json.loads(system.rsplit("Profile:\n", 1)[1]) == reports._prompt_profile(
        reports.load_report_profile()
    )
    assert prepare_scribe_input(transcript["source_sha256"], 1000) == c2
    assert prepare_fact_inputs(transcript, provider=provider, model=model) == c4
