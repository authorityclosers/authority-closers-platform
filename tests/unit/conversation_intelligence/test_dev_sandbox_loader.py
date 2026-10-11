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
    data["transcript"]["participants"][0]["person_id"] = "syn-fixture-R1"
    line = data["transcript"]["lines"][0]
    line.update(person_id="syn-fixture-R1", speaker="rep")
    data["transcript"]["timing_source"] = "estimated"
    evidence = {"line_ids": [line["line_id"]], "quote": line["text"]}
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
        current_focus={"label": "Agree a date"},
        diagnosis={"playable_moments": [evidence]},
        teaching={"text_lesson": {"quick_idea": "Ask which date works."}},
    )
    data["answer_key"]["report"] = {k: v for k, v in data["report"].items() if k != "call_id"}
    data["answer_key"]["per_call_coaching"] = {
        k: v for k, v in data["coaching"].items() if k != "call_id"
    }
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
