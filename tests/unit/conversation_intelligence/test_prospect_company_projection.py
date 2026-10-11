"""Source-backed fictional business facts and human locks, without I/O."""

import copy
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

import pytest

from ac_platform.conversation_intelligence.prospect_company_profile import CompanyCandidate
from ac_platform.conversation_intelligence.prospect_company_projection import (
    CompanyFactRevision,
    company_candidate_digest,
    project_company_fields,
    supported_company_fields,
)
from ac_platform.conversation_intelligence.sensitive_segments import grams, withheld_plan
from tests.unit.conversation_intelligence.test_prospect_company_profile import case


def candidate_case():
    report, transcript, _, payload = case()
    candidate = CompanyCandidate(
        payload["source_sha256"], payload["transcript_revision"], payload["fields"]
    )
    return report, transcript, candidate


def visible(report, transcript, candidate, **overrides):
    return supported_company_fields(
        candidate,
        expected_digest=overrides.pop("expected_digest", company_candidate_digest(candidate)),
        report=report,
        transcript=transcript,
        **overrides,
    )


def test_literal_business_values_have_original_source_and_whole_candidate_digest():
    report, transcript, candidate = candidate_case()
    before = copy.deepcopy(candidate.fields)
    fields = visible(report, transcript, candidate)
    assert set(fields) == {"name", "industry", "city", "size"}
    assert fields["size"]["value"]["text"] == "about 10–12 workers"
    assert fields["city"]["evidence"] == before["city"]["evidence"]
    assert candidate.fields == before
    assert visible(report, transcript, candidate, expected_digest="b" * 64) == {}


@pytest.mark.parametrize("mutation", ["value", "subject", "time", "role", "revision", "source"])
def test_rehashed_forgery_cannot_reuse_a_valid_quote_for_a_different_fact(mutation):
    report, transcript, candidate = candidate_case()
    if mutation == "value":
        candidate.fields["city"]["value"]["text"] = "Mumbai"
    elif mutation == "subject":
        transcript["segments"][1]["text"] += " I live in Pune."
        candidate.fields["city"]["evidence"]["quote"] = "I live in Pune."
    elif mutation == "time":
        candidate.fields["city"]["evidence"]["start_ms"] += 1
    elif mutation == "role":
        transcript["segments"][1]["speaker_id"] = "speaker_0"
    elif mutation == "revision":
        candidate = replace(candidate, transcript_revision="different-native-revision")
    elif mutation == "source":
        candidate = replace(candidate, source_sha256="b" * 64)
    assert visible(report, transcript, candidate) == {}


def test_missing_c5_roles_purpose_or_native_source_hides_heard_facts():
    report, transcript, candidate = candidate_case()
    assert visible(report.model_copy(update={"call_map": None}), transcript, candidate) == {}
    transcript["segments"] = []
    assert visible(report, transcript, candidate) == {}


@pytest.mark.parametrize("marked", ["s1", "s2"])
def test_private_call_purpose_or_business_name_withholds_candidate(marked):
    report, transcript, candidate = candidate_case()
    plan = withheld_plan([], [marked], [])
    assert visible(report, transcript, candidate, plan=plan) == {}


def test_private_attribute_is_hidden_without_removing_readable_name_and_other_fields():
    report, transcript, candidate = candidate_case()
    attribute = copy.deepcopy(transcript["segments"][1])
    attribute.update(id="s3", start_ms=2000, end_ms=2900, text="Example works is based in Pune.")
    transcript["segments"].append(attribute)
    transcript["duration_ms"] = 3000
    candidate.fields["city"]["evidence"] = {
        "segment_id": "s3",
        "quote": attribute["text"],
        "start_ms": attribute["start_ms"],
        "end_ms": attribute["end_ms"],
    }
    assert set(visible(report, transcript, candidate)) == {"name", "industry", "city", "size"}
    plan = withheld_plan([], ["s3"], [])
    assert set(visible(report, transcript, candidate, plan=plan)) == {"name", "industry", "size"}
    # Same words marked on a prior revision or duplicate upload still disappear.
    cross_upload = withheld_plan(
        [(item["id"], item["text"]) for item in transcript["segments"]],
        [],
        grams(attribute["text"]),
    )
    assert "city" not in visible(report, transcript, candidate, plan=cross_upload)


def revision(key="city", text="Pune", number=1, **overrides):
    return CompanyFactRevision(
        **{
            "id": uuid4(),
            "field_key": key,
            "revision": number,
            "value": {"kind": "text", "text": text},
            "basis": "heard_in_call",
            "created_at": datetime(2026, 10, 11, tzinfo=UTC) + timedelta(seconds=number),
            "submission_id": UUID("10000000-0000-4000-8000-000000000001"),
            "evidence": {
                "segment_id": "s1",
                "quote": "Fictional quote",
                "start_ms": 0,
                "end_ms": 900,
            },
            **overrides,
        }
    )


def test_human_edit_wins_out_of_order_and_only_later_heard_values_disagree():
    owner = uuid4()
    old = revision()
    human = revision(text="Jaipur", number=2, basis="person", created_by_person_id=owner)
    later = revision(text="Mumbai", number=3)
    fields = project_company_fields([old, later, human], detected=True)
    city = fields["city"]
    assert city["value"]["text"] == "Jaipur" and city["locked"]
    assert city["set_by"] == str(owner)
    assert "evidence" not in city and "changed_from" not in city
    assert len(city["heard_differently"]) == 1
    assert city["heard_differently"][0]["value"]["text"] == "Mumbai"
    assert fields["industry"] == {"state": "unknown", "reason": "not_mentioned"}


def test_human_unknown_is_locked_and_never_exposes_old_or_later_values():
    owner = uuid4()
    human = revision(
        number=2,
        basis="person",
        created_by_person_id=owner,
        value={"kind": "unknown", "reason": "not_asked"},
    )
    city = project_company_fields(
        [revision(), revision(text="Mumbai", number=3), human], detected=True
    )["city"]
    assert city == {
        "state": "unknown",
        "reason": "not_asked",
        "basis": "person",
        "locked": True,
        "set_by": str(owner),
        "set_at": human.created_at.isoformat(),
    }
    assert "Pune" not in str(city) and "Mumbai" not in str(city) and "quote" not in str(city)


def test_changed_requires_the_exact_visible_same_field_predecessor():
    before = revision()
    after = revision(text="Mumbai", number=2, supersedes_id=before.id)
    city = project_company_fields([after, before], detected=True)["city"]
    assert not city["locked"] and city["value"]["text"] == "Mumbai"
    assert city["changed_from"]["value"]["text"] == "Pune"
    assert "changed_from" not in project_company_fields([after], detected=True)["city"]
    wrong_field = replace(before, field_key="industry")
    assert "changed_from" not in project_company_fields([after, wrong_field], detected=True)["city"]
    same_time = replace(before, created_at=after.created_at)
    assert "changed_from" not in project_company_fields([after, same_time], detected=True)["city"]


def test_disagreements_are_bounded_and_cannot_turn_identical_values_into_contradictions():
    human = revision(number=1, basis="person", created_by_person_id=uuid4())
    later = [revision(text=f"Fictional city {i}", number=i) for i in range(2, 10)]
    same = revision(number=10)
    city = project_company_fields([*later, human, same], detected=False)["city"]
    assert len(city["heard_differently"]) == 5
    assert city["heard_differently"][0]["value"]["text"] == "Fictional city 9"
    assert project_company_fields([], detected=False)["city"] == {
        "state": "unknown",
        "reason": "not_asked",
    }
