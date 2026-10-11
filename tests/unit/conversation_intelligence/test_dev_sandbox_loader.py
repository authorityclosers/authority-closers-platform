"""Dev boundary and source-citation checks without real call data or credentials."""

import importlib.util
from copy import deepcopy
from pathlib import Path

import pytest

from ac_platform.conversation_intelligence.reports import load_report_profile
from ac_platform.conversation_intelligence.synthetic_import_contracts import SyntheticCallBundle
from tests.unit.conversation_intelligence.test_synthetic_import_contracts import bundle


def loader():
    source = Path(__file__).parents[3] / "scripts/dev/load-sales-xray-sandbox.py"
    spec = importlib.util.spec_from_file_location("dev_sandbox_loader", source)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def authored_bundle():
    data = bundle()
    data["metadata"]["rep_id"] = "syn-fixture-R1"
    data["transcript"]["rep_id"] = "syn-fixture-R1"
    data["answer_key"]["rep_id"] = "syn-fixture-R1"
    data["transcript"]["participants"][0].update(
        person_id="syn-fixture-R1", name="Synthetic Rep 1", speaker="rep"
    )
    line = data["transcript"]["lines"][0]
    line.update(person_id="syn-fixture-R1", speaker="rep")
    data["transcript"]["timing_source"] = "estimated"
    evidence = {
        "line_ids": [line["line_id"]],
        "quote": line["text"],
        "start_ms": line["start_ms"],
        "end_ms": line["end_ms"],
        "playable": False,
        "timing_source": "estimated",
    }
    positive = {
        "action": "Asked for context",
        "why_it_helped": "The buyer gave context.",
        "evidence": evidence,
    }
    data["report"].update(
        the_big_picture={
            "executive_summary": ["A fictional discovery call."],
            "call_outcome": "No Clear Next Step",
            "biggest_influence": "No date agreed",
            "strongest_part": positive,
        },
        how_the_call_played_out={
            "timeline": [{"phase": "Opening", "start_ms": 0, "line_id": line["line_id"]}],
        },
        moments_that_mattered=[
            {
                "category": "Turning Point",
                "title": "The buyer gave context",
                "evidence": evidence,
                "why_it_mattered": "The need became clearer.",
            },
        ],
        where_the_deal_stands={
            "prospects_position": "No follow-up was agreed.",
            "commitment_quality": "Unclear",
            "what_still_needs_to_become_clear": ["Decision date"],
            "recommended_deal_action": "Ask which date works.",
        },
        what_worked_and_what_didnt={"what_worked": [positive], "what_didnt": []},
        your_skills_on_this_call=[
            {
                "skill_id": f"skill-{i}",
                "name": row["label"],
                "state": "Observed",
                "observation": "An authored observation.",
                "evidence": evidence,
            }
            for i, row in enumerate(load_report_profile()["dimensions"], 1)
        ],
    )
    data["coaching"].update(
        current_focus={"label": "Agree a date", "skill_id": "skill-7"},
        diagnosis={"playable_moments": [evidence]},
        teaching={
            "text_lesson": {
                "quick_idea": "Ask which date works.",
                "own_call_example": evidence,
            }
        },
        action={
            "mission": {
                "behaviour": "Ask which date works.",
                "done_when": "The buyer confirms a date.",
            },
            "practice": {"exercise": "Rehearse asking for a date."},
        },
    )
    data["answer_key"]["report"] = {k: v for k, v in data["report"].items() if k != "call_id"}
    data["answer_key"]["per_call_coaching"] = {
        k: v for k, v in data["coaching"].items() if k != "call_id"
    }
    return SyntheticCallBundle.model_validate(data)


def dated_bundle():
    data = authored_bundle().model_dump(by_alias=True)
    call = data["metadata"]["call_id"]
    data["metadata"]["duration_ms"] = 3000
    data["transcript"]["duration_ms"] = 3000
    data["transcript"]["lines"].extend(
        [
            {
                "synthetic": True,
                "line_id": call + ":L002",
                "person_id": "syn-fixture-R1",
                "speaker": "rep",
                "start_ms": 1000,
                "end_ms": 2000,
                "playable": False,
                "text": "Let's review on 05 January 2027 at 10:00 AM, India time.",
                "annotations": ["next_step"],
            },
            {
                "synthetic": True,
                "line_id": call + ":L003",
                "person_id": data["metadata"]["prospect_id"],
                "speaker": "prospect",
                "start_ms": 2000,
                "end_ms": 3000,
                "playable": False,
                "text": "Yes, that date works. It is a review, not order approval.",
                "annotations": ["commitment"],
            },
        ]
    )
    event = {"agreed": True, "type": "Decision review", "at": "2027-01-05T10:00:00+05:30"}
    data["report"]["the_big_picture"].update(
        call_outcome="Follow-up Set",
        next_agreed_step=event,
    )
    data["report"]["where_the_deal_stands"].update(
        prospects_position="A review was agreed; an order remains undecided.",
        next_event=event,
        commitment_quality="Clear",
    )
    data["answer_key"]["report"] = {k: v for k, v in data["report"].items() if k != "call_id"}
    return SyntheticCallBundle.model_validate(data)


@pytest.mark.parametrize(
    "url,environment",
    [
        ("postgresql://172.27.0.12/ac_platform", "production"),
        ("postgresql://172.27.0.12:55433/ac_platform", "development"),
        ("postgresql://172.27.0.12/ac_platform?host=remote", "development"),
        ("postgresql://localhost/ac_dev_live", "production"),
        ("postgresql://localhost/ac_staging", "development"),
        ("postgresql://localhost/ac_platform", "development"),
        ("postgresql://remote/ac_dev_live", "development"),
        ("postgresql://localhost/ac_dev_live?host=remote", "development"),
        ("postgresql://localhost/ac_dev_live?options=-csearch_path=foreign", "development"),
    ],
)
def test_refuses_nondev_or_rerouted_database(monkeypatch, url, environment):
    monkeypatch.setenv("AC_ENVIRONMENT", environment)
    with pytest.raises(ValueError):
        loader().dev_database_url(url)


def test_accepts_only_the_current_dedicated_dev_destination(monkeypatch):
    monkeypatch.setenv("AC_ENVIRONMENT", "development")
    assert loader().dev_database_url("postgresql://172.27.0.12/ac_platform") == (
        "postgresql+psycopg://172.27.0.12/ac_platform"
    )


def test_adapter_preserves_source_and_quoted_coaching():
    module = loader()
    source = authored_bundle()
    before = deepcopy(source.model_dump(by_alias=True))
    report, transcript, receipt, digest = module.adapted_report(source)
    assert source.model_dump(by_alias=True) == before
    assert report["summary"].startswith("Synthetic test call.")
    assert report["improvements"][0]["title"] == "Agree a date"
    assert (
        report["improvements"][0]["evidence"][0]["quote"] == source.transcript["lines"][0]["text"]
    )
    assert receipt["new_provider_calls"] == 0
    assert transcript["normalized"]["source_sha256"] == digest
    assert "fixture_truth" not in report


def test_adapter_refuses_missing_published_citation():
    source = authored_bundle().model_dump(by_alias=True)
    source["report"]["what_worked_and_what_didnt"]["what_worked"][0]["evidence"]["line_ids"] = [
        "syn-fixture-call-1:L999"
    ]
    with pytest.raises(ValueError, match="missing transcript line"):
        loader().adapted_report(SyntheticCallBundle.model_construct(**source))


def test_adapter_keeps_authored_needs_attention_state():
    source = authored_bundle().model_dump(by_alias=True)
    source["report"]["your_skills_on_this_call"][0]["state"] = "Needs Attention"
    report, _, _, _ = loader().adapted_report(SyntheticCallBundle.model_construct(**source))
    assert report["dimensions"][0]["call_state"] == "needs_attention"
    assert report["dimensions"][0]["evidence"]


def test_adapter_carries_pillars_without_changing_legacy_report_or_source(monkeypatch):
    module = loader()
    source = dated_bundle()
    before = deepcopy(source.model_dump(by_alias=True))
    report, transcript, receipt, _ = module.adapted_report(source)
    pillars = report["pillars"]
    assert source.model_dump(by_alias=True) == before
    assert pillars["summary"] == "A fictional discovery call."
    assert pillars["outcome"]["status"] == "Follow-up Set"
    assert pillars["outcome"]["evidence"][0]["segment_id"].endswith(":L003")
    assert pillars["next_step"] == pillars["deal"]["next_event"]
    assert pillars["next_step"]["when"] == "05 January 2027 at 10:00 AM, India time"
    assert pillars["strongest_part"]["short"] == "Asked for context"
    assert pillars["timeline"][0]["label"] == "Opening"
    assert pillars["timeline"][0]["start_ms"] == 0
    assert pillars["moments"][pillars["most_important_moment"]]["kind"] == "Turning Point"
    assert pillars["key_change"] is None and pillars["deeper"] is None
    assert pillars["biggest_influence"] is None
    assert pillars["deal"]["position"] is None
    assert pillars["deal"]["prospect_commitments"] == []
    assert receipt["new_provider_calls"] == 0
    segments = {s["id"]: s for s in transcript["normalized"]["segments"]}

    def check_refs(value):
        if isinstance(value, dict):
            for ref in value.get("evidence", []):
                segment = segments[ref["segment_id"]]
                assert ref["quote"] in segment["text"]
                assert (ref["start_ms"], ref["end_ms"]) == (
                    segment["start_ms"],
                    segment["end_ms"],
                )
            for child in value.values():
                check_refs(child)
        elif isinstance(value, list):
            for child in value:
                check_refs(child)

    check_refs(pillars)
    monkeypatch.setattr(module, "authored_pillars", lambda *_args: None)
    legacy, _, _, _ = module.adapted_report(source)
    assert {k: v for k, v in report.items() if k != "pillars"} == legacy


@pytest.mark.parametrize("status", ["Won", "Lost"])
def test_adapter_does_not_promote_synthetic_won_lost_to_report_outcome(status):
    source = dated_bundle().model_dump(by_alias=True)
    source["report"]["the_big_picture"]["call_outcome"] = status
    report, _, _, _ = loader().adapted_report(SyntheticCallBundle.model_construct(**source))
    assert report["pillars"]["outcome"] is None


@pytest.mark.parametrize(
    "at",
    ["2027-01-06T10:00:00+05:30", "2027-01-05T11:00:00+05:30", "2027-01-05T10:00:00+00:00"],
)
def test_adapter_requires_spoken_date_and_time_before_showing_clear_agreement(at):
    source = dated_bundle().model_dump(by_alias=True)
    source["report"]["where_the_deal_stands"]["next_event"]["at"] = at
    report, _, _, _ = loader().adapted_report(SyntheticCallBundle.model_construct(**source))
    assert report["pillars"]["deal"] is None
    assert report["pillars"]["next_step"] is None


def test_adapter_omits_unexplained_important_miss_but_keeps_authored_concern():
    source = dated_bundle().model_dump(by_alias=True)
    moment = deepcopy(source["report"]["moments_that_mattered"][0])
    moment["category"] = "Important Miss"
    source["report"]["moments_that_mattered"].insert(0, moment)
    positive = source["report"]["what_worked_and_what_didnt"]["what_worked"][0]
    concern = {
        "what_happened": "No other signer was named.",
        "what_it_affected": "Decision roles remained unclear",
        "evidence": positive["evidence"],
    }
    source["report"]["what_worked_and_what_didnt"]["what_didnt"] = [concern]
    source["report"]["the_big_picture"]["biggest_concern"] = concern
    report, _, _, _ = loader().adapted_report(SyntheticCallBundle.model_construct(**source))
    assert report["pillars"]["didnt"][0]["what"] == concern["what_happened"]
    assert report["pillars"]["biggest_concern"]["text"] == concern["what_happened"]
    assert [m["kind"] for m in report["pillars"]["moments"]] == ["Turning Point"]


@pytest.mark.parametrize(
    "failure", ["missing_optional_citation", "duplicate_opening", "unsupported_optional_shape"]
)
def test_invalid_optional_pillars_leave_legacy_report_readable(failure):
    source = dated_bundle().model_dump(by_alias=True)
    if failure == "missing_optional_citation":
        source["report"]["how_the_call_played_out"]["timeline"][0]["line_id"] = "missing"
    elif failure == "unsupported_optional_shape":
        source["report"]["how_the_call_played_out"] = []
    else:
        source["report"]["the_big_picture"]["executive_summary"] = [
            source["report"]["where_the_deal_stands"]["prospects_position"],
        ]
    report, _, _, _ = loader().adapted_report(SyntheticCallBundle.model_construct(**source))
    assert "pillars" not in report
    assert report["summary"].startswith("Synthetic test call.")
    assert report["improvements"][0]["title"] == "Agree a date"


def test_optional_codec_rejection_keeps_import_usable(monkeypatch):
    module = loader()
    parse = module.parse_report_draft

    def unavailable(payload, *args, **kwargs):
        if "pillars" in payload:
            raise ValueError("Optional presentation unavailable")
        return parse(payload, *args, **kwargs)

    monkeypatch.setattr(module, "parse_report_draft", unavailable)
    report, _, _, _ = module.adapted_report(dated_bundle())
    assert "pillars" not in report
    assert report["improvements"][0]["title"] == "Agree a date"


def test_pillars_bound_titles_labels_lists_and_timeline_without_rewriting_source():
    source = dated_bundle().model_dump(by_alias=True)
    positive = source["report"]["what_worked_and_what_didnt"]["what_worked"][0]
    positive["action"] = " ".join(["Authored"] * 12)
    positive["why_it_helped"] = "The buyer gave context. " * 10
    source["report"]["the_big_picture"]["strongest_part"] = deepcopy(positive)
    source["report"]["what_worked_and_what_didnt"]["what_worked"] = [positive] * 5
    source["report"]["moments_that_mattered"] *= 7
    source["report"]["how_the_call_played_out"]["timeline"] *= 3
    before = deepcopy(source)
    report, _, _, _ = loader().adapted_report(SyntheticCallBundle.model_construct(**source))
    assert source == before
    pillars = report["pillars"]
    assert len(pillars["worked"]) == 3 and len(pillars["moments"]) == 5
    assert len(pillars["timeline"]) == 1
    assert len(pillars["worked"][0]["title"]) <= 48
    assert len(pillars["worked"][0]["what"]) <= 150
    assert len(pillars["worked"][0]["why_it_helped"]) <= 150
    assert len(pillars["strongest_part"]["short"].split()) <= 8
    assert len(pillars["strongest_part"]["short"]) <= 48


def test_next_event_keeps_published_ordinal_spoken_date():
    source = dated_bundle().model_dump(by_alias=True)
    source["transcript"]["lines"][1]["text"] = "I will send the review for 5th January at 10:00 am."
    report, _, _, _ = loader().adapted_report(SyntheticCallBundle.model_construct(**source))
    assert report["pillars"]["next_step"]["when"] == "5th January at 10:00 am"
