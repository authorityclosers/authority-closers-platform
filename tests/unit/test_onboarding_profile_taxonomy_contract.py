"""Contract tests for the bounded onboarding/profile taxonomy proposal."""

from __future__ import annotations

import csv
import json
import re
import unicodedata
from datetime import date
from pathlib import Path
from typing import Any

import pytest

ROOT = Path(__file__).parents[2]
CONTRACTS = ROOT / "docs" / "contracts"
SCHEMA_PATH = CONTRACTS / "onboarding-profile-taxonomy-v1.schema.json"
MANIFEST_PATH = CONTRACTS / "onboarding-profile-source-manifest.json"
STATE_MATRIX_PATH = CONTRACTS / "onboarding-profile-state-matrix.csv"


def _load_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    assert isinstance(value, dict)
    return value


def _schema() -> dict[str, Any]:
    return _load_json(SCHEMA_PATH)


def _manifest() -> dict[str, Any]:
    return _load_json(MANIFEST_PATH)


def _normalize_profile(value: dict[str, Any]) -> dict[str, Any]:
    """Apply the contract's explicit input normalization before validation."""

    normalized = dict(value)
    country = normalized.get("country_code")
    if isinstance(country, str):
        normalized["country_code"] = country.strip().upper()
    for key in ("degree_name", "specialization", "sales_interest_other"):
        text = normalized.get(key)
        if isinstance(text, str):
            normalized[key] = unicodedata.normalize("NFC", text).strip()
    codes = normalized.get("sales_interest_codes")
    if isinstance(codes, list):
        normalized["sales_interest_codes"] = [
            code.strip() if isinstance(code, str) else code for code in codes
        ]
    return normalized


def _validate_profile(value: dict[str, Any]) -> list[str]:
    """Validate the schema subset used by this contract without new dependencies."""

    schema = _schema()
    errors: list[str] = []
    properties = schema["properties"]
    extras = set(value) - set(properties)
    errors.extend(f"unknown:{key}" for key in sorted(extras))

    for key, field in properties.items():
        if key not in value:
            continue
        actual = value[key]
        if actual is None:
            if "null" not in field["type"]:
                errors.append(f"null:{key}")
            continue
        field_types = field["type"]
        if "string" in field_types and not isinstance(actual, str):
            errors.append(f"type:{key}")
            continue
        if "array" in field_types and not isinstance(actual, list):
            errors.append(f"type:{key}")
            continue
        if isinstance(actual, str):
            if len(actual) < field.get("minLength", 0):
                errors.append(f"minLength:{key}")
            if len(actual) > field.get("maxLength", len(actual)):
                errors.append(f"maxLength:{key}")
            pattern = field.get("pattern")
            if pattern and re.fullmatch(pattern, actual) is None:
                errors.append(f"pattern:{key}")
            if "enum" in field and actual not in field["enum"]:
                errors.append(f"enum:{key}")
        if isinstance(actual, list):
            if len(actual) < field.get("minItems", 0):
                errors.append(f"minItems:{key}")
            if len(actual) > field.get("maxItems", len(actual)):
                errors.append(f"maxItems:{key}")
            if field.get("uniqueItems") and len(actual) != len(set(actual)):
                errors.append(f"uniqueItems:{key}")
            item_schema = field["items"]
            for item in actual:
                if not isinstance(item, str) or item not in item_schema["enum"]:
                    errors.append(f"item:{key}")

    sales_codes = value.get("sales_interest_codes")
    other = value.get("sales_interest_other")
    if (
        isinstance(sales_codes, list)
        and "other" in sales_codes
        and not (isinstance(other, str) and other.strip())
    ):
        errors.append("required:sales_interest_other")
    if other is not None and not (isinstance(sales_codes, list) and "other" in sales_codes):
        errors.append("sales_interest_other_without_other_code")
    return errors


def test_schema_is_closed_and_keeps_contact_endpoints_separate() -> None:
    schema = _schema()
    assert schema["additionalProperties"] is False
    properties = schema["properties"]
    assert "phone_number_e164" in properties
    assert "whatsapp_number_e164" in properties
    assert "phone_number_e164" != "whatsapp_number_e164"
    assert "whatsapp_consent" not in properties
    assert "marketing_consent" not in properties
    assert "score" not in properties
    assert "recommendation" not in properties
    assert properties["sales_interest_other"]["minLength"] == 1
    assert properties["sales_interest_other"]["pattern"] == r"^\S(?:[\s\S]*\S)?$"
    conditional_other = schema["allOf"][0]["then"]["properties"]["sales_interest_other"]
    assert conditional_other["type"] == "string"
    assert conditional_other["minLength"] == 1
    assert conditional_other["pattern"] == r"^\S(?:[\s\S]*\S)?$"


def test_manifest_is_contract_only_and_marks_source_metadata_as_planned() -> None:
    manifest = _manifest()
    assert manifest["status"] == "contract_only_no_vendored_dataset"
    assert manifest["manifest_generated_on"] == "2026-09-03"
    assert manifest["source_research_checked_on"] == "2026-09-03"
    assert manifest["source_provenance_status"] == "planned_not_fetched"
    assert manifest["active_country_allowlist"] == []
    assert manifest["vendored_datasets"] == []
    assert manifest["proposed_country"]["country_code"] == "IN"
    assert manifest["proposed_country"]["status"] == "proposed_not_active"
    assert manifest["proposed_country"]["is_inference"] is True
    assert manifest["proposed_country"]["requires_user_confirmation_before_activation"] is True
    assert manifest["generation_path"]["runtime_fetch"] is False
    assert manifest["generation_path"]["status"] == "planned_release_step_not_implemented"

    sources = manifest["sources"]
    assert len(sources) >= 8
    for source in sources:
        assert source["source_id"]
        assert source["url"].startswith("https://")
        assert date.fromisoformat(source["research_checked_on"]) == date(2026, 9, 3)
        provenance = source["provenance"]
        assert provenance["status"] == "planned"
        assert provenance["retrieved_on"] is None
        assert provenance["source_revision_or_date"] is None
        assert provenance["sha256"] is None
        assert provenance["license_or_provenance"].startswith("Planned capture:")
        assert provenance["reuse_decision"].startswith("planned_")
    urls = {source["url"] for source in sources}
    assert "https://www.iso.org/iso-3166-country-codes.html" in urls
    assert "https://www.itu.int/rec/T-REC-E.164-202602-I/en" in urls
    assert "https://www.uis.unesco.org/en/methods-and-tools/isced" in urls
    assert "https://www.ugc.gov.in/Home/faq" in urls


def test_state_matrix_has_onboarding_settings_and_safe_routing_rows() -> None:
    with STATE_MATRIX_PATH.open(encoding="utf-8", newline="") as handle:
        rows = list(csv.DictReader(handle))
    assert rows
    assert {row["surface"] for row in rows} >= {"onboarding", "settings", "routing"}
    assert {row["state_id"] for row in rows} >= {
        "ONB-TAX-007",
        "ONB-TAX-009",
        "SET-TAX-001",
        "ROUTE-TAX-001",
    }
    assert all(row["privacy_boundary"] for row in rows)
    assert all(row["accessibility"] for row in rows)
    assert all(row["recovery"] for row in rows)


def test_valid_profile_uses_canonical_phone_values_and_explicit_taxonomy_codes() -> None:
    payload = {
        "country_code": None,
        "phone_number_e164": "+919876543210",
        "whatsapp_number_e164": "+919876543211",
        "education_level_code": "ISCED_2011_6",
        "degree_name": "B.Com",
        "education_field_code": "ISCED_F_04",
        "specialization": "Marketing",
        "sales_interest_codes": ["discovery_calls", "other"],
        "sales_interest_other": "Practice a calmer follow-up conversation",
    }
    assert _validate_profile(payload) == []


@pytest.mark.parametrize("blank_other", ["", " ", "\t", "\n", " \t \n "])
def test_other_interest_rejects_blank_or_whitespace_only_text(blank_other: str) -> None:
    payload = {
        "sales_interest_codes": ["other"],
        "sales_interest_other": blank_other,
    }
    assert _validate_profile(payload)


def test_proposed_country_is_not_active_and_normalizes_before_validation() -> None:
    manifest = _manifest()
    assert manifest["active_country_allowlist"] == []
    assert manifest["proposed_country"]["country_code"] == "IN"
    assert manifest["proposed_country"]["country_code"] not in manifest["active_country_allowlist"]

    normalized = _normalize_profile(
        {
            "country_code": " in ",
            "sales_interest_codes": [" other "],
            "sales_interest_other": "  Practice a calmer follow-up conversation  ",
        }
    )
    assert normalized["country_code"] == "IN"
    assert normalized["sales_interest_codes"] == ["other"]
    assert normalized["sales_interest_other"] == "Practice a calmer follow-up conversation"
    assert _validate_profile(normalized) == []


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("phone_number_e164", "09876543210"),
        ("whatsapp_number_e164", "+91 9876543210"),
        ("education_level_code", "BACHELOR"),
        ("education_field_code", "COMMERCE"),
        ("sales_interest_codes", ["discovery_calls", "discovery_calls"]),
        (
            "sales_interest_codes",
            [
                "handle_objections",
                "discovery_calls",
                "close_more_consistently",
                "other",
            ],
        ),
    ],
)
def test_invalid_profile_values_are_rejected(field: str, value: Any) -> None:
    payload = {field: value}
    assert _validate_profile(payload)


def test_other_interest_requires_text_and_text_requires_other_code() -> None:
    missing_text = {"sales_interest_codes": ["other"]}
    orphan_text = {"sales_interest_other": "A different interest"}
    assert "required:sales_interest_other" in _validate_profile(missing_text)
    assert "sales_interest_other_without_other_code" in _validate_profile(orphan_text)


def test_unknown_fields_cannot_smuggle_provider_or_scoring_semantics() -> None:
    payload = {
        "phone_number_e164": "+919876543210",
        "whatsapp_verified": True,
        "score": 90,
        "recommended_program": "some-program",
    }
    errors = _validate_profile(payload)
    assert "unknown:whatsapp_verified" in errors
    assert "unknown:score" in errors
    assert "unknown:recommended_program" in errors
