"""Fictional explicit C5 company names; no prose extraction or field aliasing."""

from ac_platform.conversation_intelligence.call_map import parse_call_map
from ac_platform.conversation_intelligence.prospect_company_detection import c5_company_candidate
from ac_platform.conversation_intelligence.sensitive_segments import withheld_plan
from tests.unit.conversation_intelligence.test_prospect_company_profile import case


def company_case(facts=None):
    report, transcript, _, payload = case()
    call_map = report.call_map.model_dump(mode="json")
    call_map["prospect_facts"] = facts or [
        {
            "key": "company",
            "text": "Example works",
            "evidence": [
                {"segment_id": "s2", "quote": payload["fields"]["name"]["evidence"]["quote"]}
            ],
        }
    ]
    return report.model_copy(update={"call_map": parse_call_map(call_map)}), transcript


def test_c5_explicit_name_retains_literal_native_source_and_no_person_attribute_aliases():
    report, transcript = company_case()
    call_map = report.call_map.model_dump(mode="json")
    call_map["prospect_facts"].extend(
        [
            {"key": key, "text": value, "evidence": call_map["prospect_facts"][0]["evidence"]}
            for key, value in (("industry", "manufacturing"), ("team_size", "10–12"))
        ]
    )
    report = report.model_copy(update={"call_map": parse_call_map(call_map)})
    before = report.model_dump_json()
    candidate = c5_company_candidate(report, transcript)
    assert candidate is not None and set(candidate.fields) == {"name"}
    assert candidate.fields["name"]["value"]["text"] == "Example works"
    assert candidate.fields["name"]["evidence"]["start_ms"] == 1000
    assert report.model_dump_json() == before


def test_old_report_and_narrative_business_mentions_do_not_invent_a_company():
    report, transcript = company_case()
    assert c5_company_candidate(report.model_copy(update={"call_map": None}), transcript) is None
    call_map = report.call_map.model_dump(mode="json")
    call_map["prospect_facts"] = []
    report = report.model_copy(
        update={"call_map": parse_call_map(call_map), "summary": "Example works in Pune."}
    )
    assert c5_company_candidate(report, transcript) is None


def test_conflicting_explicit_company_names_require_human_resolution():
    report, transcript = company_case()
    transcript["segments"][1]["text"] += " I also run Another works."
    facts = report.call_map.model_dump(mode="json")["prospect_facts"]
    facts.append(
        {
            "key": "company",
            "text": "Another works",
            "evidence": [{"segment_id": "s2", "quote": "I also run Another works."}],
        }
    )
    report, _ = company_case(facts)
    assert c5_company_candidate(report, transcript) is None


def test_repeated_same_explicit_name_is_one_candidate_not_an_identity_merge():
    report, transcript = company_case()
    call_map = report.call_map.model_dump(mode="json")
    call_map["prospect_facts"].append(call_map["prospect_facts"][0])
    report = report.model_copy(update={"call_map": parse_call_map(call_map)})
    assert c5_company_candidate(report, transcript) is not None


def test_private_alternative_does_not_resolve_identity_ambiguity():
    report, transcript = company_case()
    segment = {
        **transcript["segments"][1],
        "id": "s3",
        "start_ms": 2000,
        "end_ms": 2900,
        "text": "I also run Another works.",
    }
    transcript["segments"].append(segment)
    transcript["duration_ms"] = 3000
    call_map = report.call_map.model_dump(mode="json")
    call_map["prospect_facts"].append(
        {
            "key": "company",
            "text": "Another works",
            "evidence": [{"segment_id": "s3", "quote": segment["text"]}],
        }
    )
    report = report.model_copy(update={"call_map": parse_call_map(call_map)})
    assert c5_company_candidate(report, transcript, plan=withheld_plan([], ["s3"], [])) is None


def test_seller_claim_unsupported_name_or_missing_native_quote_does_not_detect():
    report, transcript = company_case()
    transcript["segments"][1]["speaker_id"] = "speaker_0"
    assert c5_company_candidate(report, transcript) is None
    report, transcript = company_case(
        [
            {
                "key": "company",
                "text": "Invented works",
                "evidence": [{"segment_id": "s2", "quote": transcript["segments"][1]["text"]}],
            }
        ]
    )
    assert c5_company_candidate(report, transcript) is None
    transcript["segments"][1]["text"] = "Unrelated native words"
    assert c5_company_candidate(report, transcript) is None


def test_private_name_or_call_purpose_and_stale_source_cannot_detect():
    report, transcript = company_case()
    for segment in ("s1", "s2"):
        assert (
            c5_company_candidate(report, transcript, plan=withheld_plan([], [segment], [])) is None
        )
    transcript["revision"] = "another-transcript"
    assert c5_company_candidate(report, transcript) is None
