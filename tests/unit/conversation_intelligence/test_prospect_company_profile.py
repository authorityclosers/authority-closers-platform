"""Fictional company candidates; no provider, storage or identity side effects."""

import copy
import json

import pytest

from ac_platform.conversation_intelligence.call_map import parse_call_map
from ac_platform.conversation_intelligence.prospect_company_profile import (
    MAX_OUTPUT_BYTES,
    CompanyProfileError,
    company_profile_request,
    parse_company_candidate,
)
from tests.unit.conversation_intelligence.test_call_map import _call_map
from tests.unit.conversation_intelligence.test_report_access import _report
from tests.unit.conversation_intelligence.test_reports import _transcript


def case():
    transcript = _transcript(count=2)
    transcript["segments"][0].update(
        speaker_id="speaker_0", text="Is this a good time to discuss LumaBoard?"
    )
    transcript["segments"][1].update(
        speaker_id="speaker_1",
        text="Example works is a manufacturing business in Pune with about 10–12 workers.",
    )
    report = _report().model_copy(update={"call_map": parse_call_map(_call_map())})
    request = company_profile_request(report, transcript)
    assert request is not None
    source = request["segments"][1]
    evidence = {key: source[key] for key in ("start_ms", "end_ms")}
    evidence.update(segment_id=source["id"], quote=source["text"])
    payload = {key: request[key] for key in ("version", "source_sha256", "transcript_revision")}
    payload["fields"] = {
        key: {"value": {"kind": "text", "text": text}, "evidence": copy.deepcopy(evidence)}
        for key, text in (
            ("name", "Example works"),
            ("industry", "manufacturing"),
            ("city", "Pune"),
            ("size", "about 10–12 workers"),
        )
    }
    return report, transcript, request, payload


def test_explicit_business_phrases_keep_native_quotes_and_literal_size_without_mutating_c5():
    report, _, request, payload = case()
    before = report.model_dump_json()
    result = parse_company_candidate(json.dumps(payload), request)
    assert result is not None
    assert result.fields["size"]["value"] == {"kind": "text", "text": "about 10–12 workers"}
    assert result.fields["city"]["evidence"]["start_ms"] == 1000
    assert result.source_sha256 == report.source_sha256
    assert report.model_dump_json() == before
    assert request["field_registry"] == ["name", "industry", "city", "size"]
    assert "never the person" in request["instructions"]


def test_missing_attributes_stay_absent_instead_of_using_person_profile_fields():
    _, _, request, payload = case()
    payload["fields"] = {"name": payload["fields"]["name"]}
    result = parse_company_candidate(json.dumps(payload), request)
    assert result is not None and set(result.fields) == {"name"}
    payload["fields"] = {}
    assert parse_company_candidate(json.dumps(payload), request) is None


def test_legacy_or_unknown_call_purpose_yields_no_automatic_company_candidate_request():
    report, transcript, _, _ = case()
    assert company_profile_request(_report(), transcript) is None
    call_map = _call_map()
    call_map["call_purpose"] = {"kind": "unclear", "evidence": []}
    report = report.model_copy(update={"call_map": parse_call_map(call_map)})
    assert company_profile_request(report, transcript) is None


@pytest.mark.parametrize("key", ["source_sha256", "transcript_revision"])
def test_company_request_rejects_a_different_canonical_source(key):
    report, transcript, _, _ = case()
    report = report.model_copy(update={key: "b" * 64})
    with pytest.raises(CompanyProfileError, match="company_c5_source_mismatch"):
        company_profile_request(report, transcript)


def test_customer_call_purpose_must_resolve_to_the_retained_source():
    report, transcript, _, _ = case()
    transcript["segments"][0]["text"] = "Unrelated words"
    with pytest.raises(CompanyProfileError, match="company_call_purpose_source_invalid"):
        company_profile_request(report, transcript)


@pytest.mark.parametrize("field", ["phone", "email", "team_size", "person_id", "company_id"])
def test_contacts_person_attributes_and_identity_matching_keys_are_rejected(field):
    _, _, request, payload = case()
    payload["fields"][field] = payload["fields"]["name"]
    with pytest.raises(CompanyProfileError, match="company_response_invalid"):
        parse_company_candidate(json.dumps(payload), request)


@pytest.mark.parametrize("field", ["version", "source_sha256", "transcript_revision"])
def test_result_must_belong_to_the_exact_company_request(field):
    _, _, request, payload = case()
    payload[field] = "another-source"
    with pytest.raises(CompanyProfileError, match="company_response_invalid"):
        parse_company_candidate(json.dumps(payload), request)


@pytest.mark.parametrize(
    "field,value",
    [("start_ms", 1), ("end_ms", 1), ("segment_id", "missing"), ("quote", "Invented quote")],
)
def test_native_field_sources_cannot_be_changed(field, value):
    _, _, request, payload = case()
    payload["fields"]["city"]["evidence"][field] = value
    with pytest.raises(CompanyProfileError):
        parse_company_candidate(json.dumps(payload), request)


def test_seller_company_context_cannot_be_used_as_customer_company_evidence():
    _, _, request, payload = case()
    request["segments"][1]["speaker_id"] = "speaker_0"
    with pytest.raises(CompanyProfileError, match="company_field_source_invalid"):
        parse_company_candidate(json.dumps(payload), request)


def test_a_person_city_without_the_explicit_business_subject_is_rejected():
    _, _, request, payload = case()
    request["segments"][1]["text"] += " I live in Mumbai."
    payload["fields"]["city"]["value"]["text"] = "Mumbai"
    payload["fields"]["city"]["evidence"]["quote"] = "I live in Mumbai."
    with pytest.raises(CompanyProfileError, match="company_subject_source_invalid"):
        parse_company_candidate(json.dumps(payload), request)


def test_unsupported_field_values_numeric_conversion_and_duplicate_json_are_rejected():
    _, _, request, payload = case()
    payload["fields"]["size"]["value"] = {"kind": "numeric", "lower": 10, "upper": 12}
    with pytest.raises(CompanyProfileError, match="company_field_invalid"):
        parse_company_candidate(json.dumps(payload), request)
    payload["fields"]["size"]["value"] = {"kind": "text", "text": "12 full-time employees"}
    with pytest.raises(CompanyProfileError, match="company_field_source_invalid"):
        parse_company_candidate(json.dumps(payload), request)
    with pytest.raises(CompanyProfileError, match="company_duplicate_key"):
        parse_company_candidate('{"fields": {}, "fields": {}}', request)
    with pytest.raises(CompanyProfileError, match="company_output_limit"):
        parse_company_candidate("x" * (MAX_OUTPUT_BYTES + 1), request)
