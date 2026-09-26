"""Candidate pack integrity; these do not measure generated-report accuracy."""

import json
from pathlib import Path

import pytest
from pydantic import ValidationError

from ac_platform.conversation_intelligence.qualitative_pack import (
    QualitativePack,
    load_qualitative_pack,
    qualitative_pack_manifest,
    report_language_instruction,
)


def test_published_identity_is_frozen_and_matches_captured_sources() -> None:
    pack = load_qualitative_pack()
    # Updating this requires a new pack ID, not silently editing accepted plans.
    assert pack.sha256 == "e5f831477b715833d7163dfb49370751a348fb2498565d95ff83ea57838ee4ca"
    root = Path(__file__).resolve().parents[3]
    intake = json.loads((root / "docs/plans/sales-xray-v02/source-intake.json").read_text())
    sources = {source["id"]: source for source in intake["sources"]}
    for source in pack.sources:
        assert source.drive_id == sources[source.id]["drive_id"]
        assert source.captured_text_sha256 == sources[source.id]["captured_text_sha256"]
    assert len(pack.compile()) < 6_000
    assert pack.compile() == load_qualitative_pack().compile()


@pytest.mark.parametrize("corruption", ["duplicate_rule", "unknown_source", "scoring", "extra"])
def test_malformed_pack_cannot_compile(corruption: str) -> None:
    data = load_qualitative_pack().model_dump(mode="json")
    if corruption == "duplicate_rule":
        data["rules"][1]["id"] = data["rules"][0]["id"]
    elif corruption == "unknown_source":
        data["rules"][0]["sources"][0]["source_id"] = "missing"
    elif corruption == "scoring":
        data["numeric_evaluation"] = True
    else:
        data["activation_approved"] = True
    with pytest.raises(ValidationError):
        QualitativePack.model_validate_json(json.dumps(data))


def test_manifest_does_not_mutate_pack_or_later_plan() -> None:
    pack = load_qualitative_pack()
    manifest = qualitative_pack_manifest(pack)
    original = qualitative_pack_manifest(pack)
    assert isinstance(manifest["sources"], list)
    manifest["sources"][0]["drive_id"] = "changed"
    assert qualitative_pack_manifest(pack) == original
    with pytest.raises(ValidationError):
        pack.rules[0].instruction = "changed"


def test_unknown_pack_and_language_are_rejected_without_fallback() -> None:
    with pytest.raises(ValueError, match="qualitative_pack_unknown"):
        load_qualitative_pack("latest-from-drive")
    with pytest.raises(ValueError, match="report_language_invalid"):
        report_language_instruction("hi")  # type: ignore[arg-type]


@pytest.mark.parametrize("language", ["en", "hi-Deva+en", "mr-Deva+en"])
def test_language_preserves_wire_contract_and_source_evidence(language: str) -> None:
    instruction = report_language_instruction(language)  # type: ignore[arg-type]
    assert f"REPORT_LANGUAGE: {language}." in instruction
    assert "Never translate, transliterate or rewrite source evidence" in instruction
    assert "JSON keys, identifiers, enums and provenance unchanged" in instruction
    if language != "en":
        assert "Devanagari" in instruction
        assert "English sales terms in English script" in instruction
