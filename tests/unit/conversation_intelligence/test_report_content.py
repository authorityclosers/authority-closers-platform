"""Fictional offline Report contract, evidence failures, transport and activation hold."""

from copy import deepcopy
from typing import get_args

import pytest

from ac_platform.conversation_intelligence.coaching_schema import coaching_response_json_schema
from ac_platform.conversation_intelligence.coaching_validation_gate import (
    coaching_revision_runtime_block,
)
from ac_platform.conversation_intelligence.report_access import ReportAccess, project_report
from ac_platform.conversation_intelligence.report_content import (
    Outcome,
    bind_report_content,
)
from ac_platform.conversation_intelligence.reports import load_report_profile, parse_report_draft
from tests.unit.conversation_intelligence.test_reports import _payload, _transcript


def case():
    t = _transcript(count=6)
    for i, row in enumerate(t["segments"]):
        row["speaker_id"] = "seller" if i % 2 == 0 else "buyer"
    t["segments"][4]["text"] = "Can we meet Friday at 4 PM? I will send the agenda."
    t["segments"][5]["text"] = "Yes, Friday at 4 PM. I will bring the details."
    roles = {
        "origin": "user_confirmed_roles",
        "transcript_revision": t["revision"],
        "map_revision": "b" * 64,
        "speakers": [
            {"speaker_id": "seller", "role": "seller", "is_account_holder": True},
            {"speaker_id": "buyer", "role": "prospect", "is_account_holder": False},
        ],
    }

    def n(i, text):
        return {
            "text": text,
            "actor_id": t["segments"][i]["speaker_id"],
            "evidence": [{"segment_id": t["segments"][i]["id"]}],
        }

    sentences = [
        n(0, "The seller asked about timing."),
        n(1, "The buyer discussed the timing."),
        n(5, "Both agreed to meet Friday at 4 PM."),
    ]
    content = {
        "version": "report-content/1",
        "purpose": {**n(0, "A meeting-setting call."), "kind": "setter"},
        "outcome": {**n(5, "Both agreed to a meeting."), "status": "Meeting Booked"},
        "summary_sentences": sentences,
        "influence": n(1, "Timing came up."),
        "strongest": n(4, "The seller proposed a time."),
        "concern": None,
        "next_step": n(5, "The buyer agreed to meet."),
        "phases": [n(0, "Opening"), n(4, "Next step")],
        "turning_point": {
            "before": n(1, "Timing was discussed."),
            "turn": n(4, "The seller proposed Friday."),
            "after": n(5, "The buyer agreed."),
        },
        "worked": [
            {
                "title": "The seller proposed a time",
                "observation": n(4, "The seller proposed Friday at 4 PM."),
                "effect": None,
            }
        ],
        "didnt": [],
        "moments": [],
        "missed_chances": [],
        "position": n(5, "The buyer accepted the meeting."),
        "blocker": None,
        "prospect_commitments": [n(5, "The buyer will bring details.")],
        "seller_commitments": [n(4, "The seller will send the agenda.")],
        "next_event": {
            "observation": n(5, "A meeting was agreed."),
            "date_text": "Friday",
            "time_text": "4 PM",
            "agreement_evidence": [{"segment_id": "s5"}, {"segment_id": "s6"}],
        },
        "commitment_quality": "Clear",
        "unknowns": [],
        "action": None,
    }
    payload = _payload(t)
    payload["summary"] = " ".join(n["text"] for n in sentences)
    payload["report_content"] = content
    payload["dimensions"] = [
        {
            "dimension_id": d["id"],
            "status": "observed",
            "observation": "The seller asked about timing.",
            "call_state": "observed",
            "evidence": [{"segment_id": "s1"}],
        }
        for d in load_report_profile()["dimensions"]
    ]
    return t, roles, payload


def parse(t, roles, p):
    return parse_report_draft(p, t, coaching_prompt_revision="report-c5-v1", speaker_roles=roles)


@pytest.mark.parametrize("status", get_args(Outcome))
def test_nine_explicit_outcomes_without_call_map(status):
    t, roles, p = case()
    p["report_content"]["outcome"]["status"] = status
    report = parse(t, roles, p)
    assert report.call_map is None
    assert report.report_content.outcome.status == status
    before = report.model_dump_json()
    content = project_report(report, access=ReportAccess.ACCOUNT)["content"]["report_content"]
    assert content["next_event"]["date_text"] == "Friday"
    assert content["next_event"]["agreement_evidence"][0]["quote"] == t["segments"][4]["text"]
    assert "report_content" not in project_report(report, access=ReportAccess.GUEST)["content"]
    assert report.model_dump_json() == before
    retained = parse_report_draft(report.model_dump(mode="json"), t, canonical_read=True)
    assert retained.report_content == report.report_content


@pytest.mark.parametrize(
    "state",
    [
        "strongly_demonstrated",
        "observed",
        "needs_attention",
        "insufficient_evidence",
        "not_applicable",
    ],
)
def test_each_explicit_skill_state_preserves_evidence_sufficiency(state):
    t, roles, p = case()
    d = p["dimensions"][0]
    d["call_state"] = state
    if state in {"insufficient_evidence", "not_applicable"}:
        d.update(status=state, evidence=[])
    assert parse(t, roles, p).dimensions[0].call_state == state


@pytest.mark.parametrize("purpose", ["setter", "discovery", "closing", "client_review"])
def test_purpose_is_explicit_without_inventing_absent_stage(purpose):
    t, roles, p = case()
    p["report_content"]["purpose"]["kind"] = purpose
    assert parse(t, roles, p).report_content.purpose.kind == purpose


@pytest.mark.parametrize(
    "fault",
    [
        "wrong_actor",
        "offset",
        "order",
        "role",
        "fake_date",
        "no_agreement",
        "turn_order",
        "missing_state",
        "coaching",
        "short_summary",
        "summary_mismatch",
        "bad_quality",
    ],
)
def test_invalid_output_fails_without_partial_report(fault):
    t, roles, p = case()
    c = p["report_content"]
    if fault == "wrong_actor":
        c["strongest"]["actor_id"] = "buyer"
    elif fault == "offset":
        c["strongest"]["evidence"][0].update(quote_start=0, quote_end=4)
    elif fault == "order":
        c["phases"].reverse()
    elif fault == "role":
        c["seller_commitments"] = c["prospect_commitments"]
    elif fault == "fake_date":
        c["next_event"]["date_text"] = "Tuesday"
    elif fault == "no_agreement":
        c["next_event"]["agreement_evidence"] = [{"segment_id": "s3"}, {"segment_id": "s5"}]
    elif fault == "turn_order":
        c["turning_point"]["before"] = c["turning_point"]["after"]
    elif fault == "missing_state":
        p["dimensions"][0].pop("call_state")
    elif fault == "coaching":
        c["worked"][0]["replacement_behavior"] = "Ask better questions."
    elif fault == "short_summary":
        c["summary_sentences"].pop()
    elif fault == "summary_mismatch":
        p["summary"] = "A different summary."
    elif fault == "bad_quality":
        c["next_event"]["time_text"] = None
    with pytest.raises(ValueError):
        parse(t, roles, p)


def test_missed_chance_needs_all_three_parts_and_correct_turns():
    t, roles, p = case()
    c = p["report_content"]
    miss = {
        "title": "Timing remained unexplored",
        "opening": deepcopy(c["influence"]),
        "response_opportunity": deepcopy(c["strongest"]),
        "relevance": deepcopy(c["influence"]),
    }
    c["missed_chances"] = [miss]
    assert len(parse(t, roles, p).report_content.missed_chances) == 1
    miss.pop("relevance")
    with pytest.raises(ValueError):
        parse(t, roles, p)


def test_canonical_read_rejects_truncated_or_retimed_evidence():
    t, roles, p = case()
    bound = parse(t, roles, p).report_content.model_dump()
    bound["strongest"]["evidence"][0]["quote"] = "Can we"
    with pytest.raises(ValueError, match="complete_turn"):
        bind_report_content(bound, t, speaker_roles=None, canonical_read=True)


def test_schema_is_versioned_closed_and_runtime_stays_blocked():
    old = coaching_response_json_schema("coaching-v5")
    new = coaching_response_json_schema("report-c5-v1")
    assert "report_content" not in old["properties"]
    assert "report_content" in new["required"]
    assert "roles" not in new["properties"]["report_content"]["properties"]
    assert all("call_state" in d["required"] for d in new["$defs"]["dimension"]["anyOf"])
    for revision in ["coaching-v6", "coaching-v7", "report-c5-v1"]:
        assert "Gate 2" in coaching_revision_runtime_block(revision)
    assert coaching_revision_runtime_block("coaching-v5") is None


def test_candidate_prompt_has_complete_source_map_and_own_provider_schema():
    import json

    from ac_platform.conversation_intelligence.gemini_tasks import (
        gemini_prompt_view,
        prepare_gemini_body,
    )
    from ac_platform.conversation_intelligence.openai_tasks import _schema_for_prompt
    from ac_platform.conversation_intelligence.qualitative_pack import (
        load_qualitative_pack_for_revision,
    )
    from ac_platform.conversation_intelligence.reports import (
        build_report_groq_prompt,
        parse_fact_packet,
    )

    t, roles, _ = case()
    packet = parse_fact_packet(
        {"overview": "Fictional exchange.", "observations": [], "uncertainties": []}, t
    )
    prompt = build_report_groq_prompt(
        t,
        [packet],
        provider="gemini",
        model="gemini-3.8-flash",
        max_completion_tokens=3200,
        coaching_prompt_revision="report-c5-v1",
        speaker_roles=roles,
        qualitative_pack_sha256=load_qualitative_pack_for_revision("coaching-v5").sha256,
    )
    source = json.loads(prompt["messages"][1]["content"].split("\n", 1)[1])
    assert source["source_context"]["speaker_roles"] == roles
    system = prompt["messages"][0]["content"]
    assert "Determine call purpose first" in system
    body = prepare_gemini_body(prompt, task="coaching")
    assert "report_content" in body["generationConfig"]["responseJsonSchema"]["required"]
    restored = gemini_prompt_view(body, model="gemini-3.8-flash", task="coaching", maximum=3200)
    assert restored["messages"] == prompt["messages"]
    assert restored["max_completion_tokens"] == prompt["max_completion_tokens"]
    revision, schema = _schema_for_prompt(system)
    assert revision == "report-c5-v1" and "report_content" in schema["required"]
