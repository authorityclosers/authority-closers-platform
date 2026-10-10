"""Separate post-C5 extraction bounds; synthetic broker, no external requests."""

import json
from decimal import Decimal
from unittest.mock import AsyncMock

import pytest

from ac_platform.conversation_intelligence.prospect_fact_contract import TextFactValue
from ac_platform.conversation_intelligence.prospect_profile import (
    ProfileExtractionError,
    ProfilePolicy,
    ProfileResponse,
    extract_prospect_profile,
    parse_profile_response,
    profile_request,
)
from tests.unit.conversation_intelligence.test_report_access import _report
from tests.unit.conversation_intelligence.test_reports import _transcript


class _Registry:
    """Protocol test adapter. Production uses PR #414's registry unchanged."""

    def field_registry(self, *, for_extractor=False):
        assert for_extractor
        return [{"key": "name", "person_only": False}]

    def validate_fields(self, values, *, detected=False):
        assert detected
        assert set(values) == {"name"}
        TextFactValue(values["name"]["text"])
        return values

    def validate_evidence(self, value):
        assert set(value) == {"segment_id", "quote", "start_ms", "end_ms"}
        return value


def _response(request):
    segment = request["segments"][0]
    return {
        "version": request["version"],
        "source_sha256": request["source_sha256"],
        "transcript_revision": request["transcript_revision"],
        "fields": {
            "name": {
                "value": {"kind": "text", "text": segment["text"]},
                "evidence": {
                    "segment_id": segment["id"],
                    "quote": segment["text"],
                    "start_ms": segment["start_ms"],
                    "end_ms": segment["end_ms"],
                },
            }
        },
    }


def _case():
    report, transcript, registry = _report(), _transcript(), _Registry()
    request = profile_request(
        report, transcript, registry, prospect_speaker_ids=frozenset({"speaker_1"})
    )
    broker = AsyncMock()
    broker.quote.return_value = Decimal("0.01")
    broker.extract.return_value = ProfileResponse(json.dumps(_response(request)), Decimal("0.005"))
    return dict(
        policy=ProfilePolicy(True, Decimal("0.02")),
        report=report,
        transcript=transcript,
        customer_call=True,
        broker=broker,
        registry=registry,
        write_detected=AsyncMock(),
        prospect_speaker_ids=frozenset({"speaker_1"}),
    )


@pytest.mark.asyncio
async def test_disabled_does_not_load_dependency_dispatch_or_write():
    case = _case()
    case.update(policy=ProfilePolicy(), registry=None, transcript={})
    assert (await extract_prospect_profile(**case)).state == "disabled"
    case["broker"].quote.assert_not_called()
    case["write_detected"].assert_not_called()


@pytest.mark.asyncio
async def test_non_customer_call_does_not_extract_or_create_a_prospect():
    case = _case()
    case["customer_call"] = False
    assert (await extract_prospect_profile(**case)).state == "not_applicable"
    case["broker"].quote.assert_not_called()
    case["write_detected"].assert_not_called()


@pytest.mark.asyncio
async def test_c5_source_mismatch_fails_before_dispatch():
    case = _case()
    case["report"] = case["report"].model_copy(update={"source_sha256": "b" * 64})
    with pytest.raises(ProfileExtractionError, match="profile_c5_source_mismatch"):
        await extract_prospect_profile(**case)
    case["broker"].quote.assert_not_called()


@pytest.mark.asyncio
async def test_cost_cap_stops_before_the_provider_and_writer():
    case = _case()
    case["policy"] = ProfilePolicy(True, Decimal("0.001"))
    assert (await extract_prospect_profile(**case)).state == "cost_cap"
    case["broker"].extract.assert_not_called()
    case["write_detected"].assert_not_called()


@pytest.mark.asyncio
async def test_one_bounded_request_writes_validated_evidence_with_version_without_mutating_c5():
    case = _case()
    before = case["report"].model_dump_json()
    result = await extract_prospect_profile(**case)
    assert result.state == "done" and result.field_count == 1
    case["broker"].extract.assert_awaited_once()
    assert case["broker"].extract.call_args.kwargs == {"maximum_cost_usd": Decimal("0.01")}
    case["write_detected"].assert_awaited_once()
    written = case["write_detected"].call_args.kwargs
    assert written["extractor_revision"] == "prospect-profile/1"
    assert written["evidence"]["name"]["quote"] == _transcript()["segments"][0]["text"]
    assert case["report"].model_dump_json() == before


@pytest.mark.asyncio
async def test_over_cap_receipt_fails_without_persisting():
    case = _case()
    request = profile_request(
        case["report"],
        case["transcript"],
        case["registry"],
        prospect_speaker_ids=case["prospect_speaker_ids"],
    )
    case["broker"].extract.return_value = ProfileResponse(
        json.dumps(_response(request)), Decimal("0.011")
    )
    with pytest.raises(ProfileExtractionError, match="profile_cost_cap_exceeded"):
        await extract_prospect_profile(**case)
    case["write_detected"].assert_not_called()


@pytest.mark.parametrize("key", ["phone", "email", "invented_field"])
def test_forbidden_fields_never_enter_detected_values(key):
    case = _case()
    request = profile_request(
        case["report"],
        case["transcript"],
        case["registry"],
        prospect_speaker_ids=case["prospect_speaker_ids"],
    )
    payload = _response(request)
    payload["fields"][key] = payload["fields"].pop("name")
    with pytest.raises(ProfileExtractionError, match="profile_field_forbidden"):
        parse_profile_response(json.dumps(payload), request, case["registry"])


@pytest.mark.parametrize(
    "change", [{"quote": "invented words"}, {"start_ms": 10}, {"segment_id": "missing"}]
)
def test_invented_quotes_or_times_fail_closed(change):
    case = _case()
    request = profile_request(
        case["report"],
        case["transcript"],
        case["registry"],
        prospect_speaker_ids=case["prospect_speaker_ids"],
    )
    payload = _response(request)
    payload["fields"]["name"]["evidence"].update(change)
    with pytest.raises(ProfileExtractionError, match="profile_source_invalid"):
        parse_profile_response(json.dumps(payload), request, case["registry"])


def test_duplicate_response_keys_and_oversize_payloads_are_rejected():
    case = _case()
    request = profile_request(
        case["report"],
        case["transcript"],
        case["registry"],
        prospect_speaker_ids=case["prospect_speaker_ids"],
    )
    for raw, reason in [
        ('{"fields": {}, "fields": {}}', "profile_duplicate_key"),
        ("x" * 32001, "profile_output_limit"),
    ]:
        with pytest.raises(ProfileExtractionError, match=reason):
            parse_profile_response(raw, request, case["registry"])


@pytest.mark.parametrize("cap", [Decimal("NaN"), Decimal("Infinity"), Decimal("-1")])
def test_invalid_cost_policy(cap):
    with pytest.raises(ProfileExtractionError, match="profile_cost_cap_invalid"):
        ProfilePolicy(True, cap)


def test_text_value_requires_the_heard_words_not_just_a_valid_quote():
    case = _case()
    request = profile_request(
        case["report"],
        case["transcript"],
        case["registry"],
        prospect_speaker_ids=case["prospect_speaker_ids"],
    )
    payload = _response(request)
    payload["fields"]["name"]["value"]["text"] = "An invented candidate"
    with pytest.raises(ProfileExtractionError, match="profile_source_invalid"):
        parse_profile_response(json.dumps(payload), request, case["registry"])


@pytest.mark.asyncio
async def test_unknown_prospect_role_does_not_guess_a_person_or_dispatch():
    case = _case()
    case["prospect_speaker_ids"] = None
    assert (await extract_prospect_profile(**case)).state == "not_enough_evidence"
    case["broker"].quote.assert_not_called()


def test_a_seller_quote_cannot_become_a_prospect_field():
    case = _case()
    request = profile_request(
        case["report"],
        case["transcript"],
        case["registry"],
        prospect_speaker_ids=case["prospect_speaker_ids"],
    )
    payload = _response(request)
    seller = request["segments"][1]
    payload["fields"]["name"] = {
        "value": {"kind": "text", "text": seller["text"]},
        "evidence": {
            "segment_id": seller["id"],
            "quote": seller["text"],
            "start_ms": seller["start_ms"],
            "end_ms": seller["end_ms"],
        },
    }
    with pytest.raises(ProfileExtractionError, match="profile_source_invalid"):
        parse_profile_response(json.dumps(payload), request, case["registry"])
