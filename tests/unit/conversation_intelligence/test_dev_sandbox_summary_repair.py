"""Exact authored wording only; no source mutation, quotes or outcome inference."""

import importlib.util
from copy import deepcopy
from pathlib import Path

import pytest

from ac_platform.conversation_intelligence.checkpoints import content_hash
from ac_platform.conversation_intelligence.synthetic_import_contracts import SyntheticCallBundle
from tests.unit.conversation_intelligence.test_dev_sandbox_loader import authored_bundle


def repair():
    path = Path(__file__).parents[3] / "scripts/dev/repair-sales-xray-summary-prefixes.py"
    spec = importlib.util.spec_from_file_location("dev_summary_repair", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def summary_bundle(label="Lost"):
    data = authored_bundle().model_dump(mode="json", by_alias=True)
    position = "Buyer explicitly declines the service and requests closure"
    data["report"]["where_the_deal_stands"]["prospects_position"] = position
    data["report"]["the_big_picture"]["executive_summary"] = [
        "A fictional discovery call.",
        f"The conversation ended as {label}: {position}.",
        'The seller quoted "The conversation ended as Lost: " from a template.',
        "No future meeting was agreed in this call.",
    ]
    data["answer_key"]["report"] = {k: v for k, v in data["report"].items() if k != "call_id"}
    return SyntheticCallBundle.model_validate(data)


def fixture_plan(module, monkeypatch, sources):
    counts = {"reports": len(sources), "other_sentences": 0}
    for source in sources:
        _, changes = module.revised_summary(source)
        counts["other_sentences"] += len(
            source.report["the_big_picture"]["executive_summary"]
        ) - len(changes)
        for change in changes:
            label = change["prefix_label"]
            counts[label] = counts.get(label, 0) + 1
    monkeypatch.setattr(module, "EXPECTED_COUNTS", counts)
    monkeypatch.setattr(
        module,
        "SOURCE_SHA256",
        content_hash([content_hash(s.model_dump(mode="json", by_alias=True)) for s in sources]),
    )
    # Keep the production 827-candidate guard; exercise candidates through a small plan below.
    entries, candidates = [], []
    for source in sources:
        before, after, transcript, proof, digest, changes = module.candidate(source)
        key = source.metadata["call_id"]
        entries.append(
            {
                "call_key": key,
                "previous_report_id": str(module.loader.identifier("report", key)),
                "replacement_report_id": str(module.loader.identifier(module.POLICY, key)),
                "previous_report_sha256": content_hash(before),
                "replacement_report_sha256": content_hash(after),
                "source_sha256": digest,
                "changes": changes,
            }
        )
        candidates.append((source, before, after, transcript, proof, digest))
    proposal = {
        "policy": module.POLICY,
        "tenant_id": str(module.loader.TARGET),
        "environment": "development",
        "source_sha256": module.SOURCE_SHA256,
        "counts": counts,
        "reports": entries,
    }
    return {**proposal, "plan_sha256": content_hash(proposal)}, candidates


@pytest.mark.parametrize("label", ["Won", "Lost"])
def test_only_exact_whole_sentence_prefixes_change_and_source_is_intact(label):
    module, bundle = repair(), summary_bundle(label)
    original = deepcopy(bundle.model_dump(mode="json", by_alias=True))
    before, after, transcript, proof, source, changes = module.candidate(bundle)
    summary = bundle.report["the_big_picture"]["executive_summary"]
    assert changes == [{"sentence_index": 1, "prefix_label": label}]
    assert module.revised_summary(bundle)[0] == [
        summary[0],
        "Buyer explicitly declines the service and requests closure.",
        *summary[2:],
    ]
    assert bundle.model_dump(mode="json", by_alias=True) == original
    expected = deepcopy(before)
    expected["summary"] = after["summary"]
    expected["pillars"]["summary"] = after["pillars"]["summary"]
    assert after == expected
    assert before["pillars"]["outcome"] == after["pillars"]["outcome"]
    assert 'quoted "The conversation ended as Lost: "' in after["summary"]
    assert proof["generation_receipt_sha256"] == content_hash(bundle.report)
    assert transcript["normalized"]["source_sha256"] == source


@pytest.mark.parametrize(
    "sentence",
    [
        '"The conversation ended as Won: Buyer agreed."',
        "The conversation ended as won: Buyer agreed.",
        " The conversation ended as Lost: Buyer agreed.",
        "The conversation ended as Follow-up Set: Buyer agreed.",
    ],
)
def test_quoted_or_nonexact_sentences_remain_unchanged(sentence):
    data = authored_bundle().model_dump(mode="json", by_alias=True)
    data["report"]["the_big_picture"]["executive_summary"] = [sentence]
    before, after, *_ = repair().candidate(SyntheticCallBundle.model_construct(**data))
    assert after == before


def test_unknown_suffix_and_unreviewed_publication_are_refused(monkeypatch):
    module = repair()
    source = summary_bundle().model_dump(mode="json", by_alias=True)
    source["report"]["where_the_deal_stands"]["prospects_position"] = "Different buyer fact"
    with pytest.raises(ValueError, match="complete authored buyer fact"):
        module.candidate(SyntheticCallBundle.model_construct(**source))
    monkeypatch.setattr(module.loader, "bundles", lambda _root: iter([summary_bundle()]))
    with pytest.raises(ValueError, match="reviewed source and exact counts"):
        module.plan(Path("fictional"))
