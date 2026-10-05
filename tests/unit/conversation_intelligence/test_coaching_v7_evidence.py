"""Offline claim evidence, repair and legacy hash contracts; fictional C2 only."""

from copy import deepcopy

import pytest

from ac_platform.conversation_intelligence.checkpoints import content_hash
from ac_platform.conversation_intelligence.coaching_schema import (
    coaching_generation_json_schema,
    coaching_response_json_schema,
)
from ac_platform.conversation_intelligence.inference_tasks import InferenceTaskError
from ac_platform.conversation_intelligence.qualitative_pack import (
    load_qualitative_pack_for_revision,
)
from ac_platform.conversation_intelligence.reports import (
    build_report_groq_prompt,
    parse_report_draft,
)
from tests.unit.conversation_intelligence.test_coaching_v6_integration import (
    _dimension_complete_draft,
    _fixture,
)
from tests.unit.conversation_intelligence.test_coaching_v7_output import (
    case as case,
)
from tests.unit.conversation_intelligence.test_coaching_v7_output import (
    stored,
    validated,
)
from tests.unit.conversation_intelligence.test_coaching_v7_output import (
    test_failure_codes_are_public_and_allow_exactly_one_automatic_repair as assert_one_repair,
)
from tests.unit.conversation_intelligence.test_coaching_v7_prompt import (
    v7_response,
    validate_schema,
)

FIELDS = ("summary_evidence", "verdict_evidence", "final_assessment")


def target(payload, field):
    return (
        (payload["overview"]["final_assessment"], "evidence")
        if field == "final_assessment"
        else (payload, field)
    )


@pytest.mark.parametrize("count", [1, 2, 3])
def test_claim_evidence_round_trips_through_real_stored_draft_validation(case, count):
    before = deepcopy(case[2])
    refs = [{"segment_id": row["id"]} for row in case[0]["segments"][:count]]
    for field in FIELDS:
        parent, key = target(case[2], field)
        parent[key] = deepcopy(refs)
    provider_payload = deepcopy(case[2])
    payload = stored(case)
    for field in FIELDS:
        parent, key = target(payload, field)
        assert parent[key] == [
            {
                "segment_id": row["id"],
                "quote": row["text"],
                "start_ms": row["start_ms"],
                "end_ms": row["end_ms"],
            }
            for row in case[0]["segments"][:count]
        ]
        assert field not in payload.get("provider_extras", {})
    assert case[2] == provider_payload
    assert content_hash(payload) != content_hash(before)


@pytest.mark.parametrize("field", FIELDS)
@pytest.mark.parametrize("bad", ["missing", "empty", "four", "null", "object", "unknown", "quote"])
def test_invalid_claim_evidence_fails_and_allows_only_one_automatic_repair(case, field, bad):
    parent, key = target(case[2], field)
    code = (
        "report_overview_invalid" if field == "final_assessment" else "report_payload_missing_field"
    )
    if bad == "missing":
        parent.pop(key)
    elif bad == "empty":
        parent[key] = []
    elif bad == "four":
        parent[key] = [{"segment_id": "s1"}] * 4
    elif bad == "null":
        parent[key] = None
    elif bad == "object":
        parent[key] = {"segment_id": "s1"}
    elif bad == "unknown":
        parent[key] = [{"segment_id": "missing"}]
        code = "report_evidence_segment_invalid"
    else:
        row = case[0]["segments"][0]
        parent[key] = [
            {
                "segment_id": row["id"],
                "quote": "Invented fictional quote.",
                "start_ms": row["start_ms"],
                "end_ms": row["end_ms"],
            }
        ]
        code = "report_evidence_quote_mismatch"
    with pytest.raises(InferenceTaskError, match=f"^{code}$"):
        validated(case)
    assert_one_repair(code)


@pytest.mark.parametrize("field", FIELDS)
@pytest.mark.parametrize("count", [0, 1, 3, 4])
def test_v7_generation_schema_requires_bounded_claim_evidence(field, count):
    response = v7_response()
    parent, key = target(response, field)
    parent[key] = [{"segment_id": "s1"}] * count
    schema = coaching_response_json_schema("coaching-v7")
    if count in {0, 4}:
        with pytest.raises(AssertionError):
            validate_schema(response, schema)
    else:
        validate_schema(response, schema)
        validate_schema(response, coaching_generation_json_schema("coaching-v7"))
    parent.pop(key)
    with pytest.raises(AssertionError):
        validate_schema(response, schema)


@pytest.mark.parametrize("revision", ["coaching-v5", "coaching-v6"])
def test_legacy_stored_bytes_and_hash_match_pre_change_pin(revision):
    transcript, _ = _fixture()
    draft = parse_report_draft(
        _dimension_complete_draft(transcript), transcript, coaching_prompt_revision=revision
    ).model_dump(mode="json")
    assert content_hash(draft) == "2a2056a560191a13280483c05434315820e2cff1e7095ebfacefd67b3082b77e"
    assert "summary_evidence" not in draft and "verdict_evidence" not in draft
    assert "evidence" not in draft["overview"]["final_assessment"]
    checked = parse_report_draft(draft, transcript, canonical_read=True).model_dump(mode="json")
    assert checked == draft


def test_v7_prompt_identity_changes_from_pre_change_pin():
    transcript, packet = _fixture()
    prompt = build_report_groq_prompt(
        transcript,
        [packet],
        provider="gemini",
        model="gemini-3.8-flash",
        max_completion_tokens=8000,
        coaching_prompt_revision="coaching-v7",
        qualitative_pack_sha256=load_qualitative_pack_for_revision("coaching-v7").sha256,
    )
    assert (
        content_hash(prompt) != "57ba9c5f5d078cdefd751db926defb8118d9d28ef483b7bb568ca06af5076776"
    )
