"""Company commands are closed, literal human facts, separate from person fields."""

import pytest

from ac_platform.conversation_intelligence.prospect_company_fields import (
    company_field_registry,
    validate_company_fields,
)
from ac_platform.conversation_intelligence.prospect_fact_contract import ProspectFactValidationError


def test_human_company_values_preserve_literal_ranges_units_and_devanagari() -> None:
    values = {
        "name": {"kind": "text", "text": "काल्पनिक व्यवसाय"},
        "industry": {"kind": "text", "text": "Person-entered description"},
        "city": {"kind": "text", "text": "पुणे"},
        "size": {"kind": "text", "text": "about 25–50 people, two sites"},
    }
    assert validate_company_fields(values) == values
    assert values["size"]["text"] == "about 25–50 people, two sites"


@pytest.mark.parametrize("key", ["industry", "city", "size"])
@pytest.mark.parametrize("reason", ["not_asked", "not_mentioned"])
def test_unknown_is_explicit_and_not_a_value_guess(key: str, reason: str) -> None:
    assert validate_company_fields({key: {"kind": "unknown", "reason": reason}}) == {
        key: {"kind": "unknown", "reason": reason}
    }


@pytest.mark.parametrize(
    "values",
    [
        None,
        [],
        {},
        {"phone": {"kind": "text", "text": "+15555550123"}},
        {"email": {"kind": "text", "text": "fictional@example.test"}},
        {"role": {"kind": "text", "text": "Founder"}},
        {"team_size": {"kind": "text", "text": "50"}},
        {"business": {"kind": "text", "text": "Name"}},
        {"tenant_id": {"kind": "text", "text": "Workspace"}},
        {"name": {"kind": "unknown", "reason": "not_asked"}},
        {"city": {"kind": "unknown", "reason": "inferred"}},
        {"city": {"kind": "unknown", "reason": "speaker_uncertain"}},
        {"city": {"kind": "unknown", "reason": None}},
        {"city": {"kind": "text", "text": ""}},
        {"city": {"kind": "text", "text": " "}},
        {"city": {"kind": "text", "text": 42}},
        {"city": {"kind": "text", "text": True}},
        {"city": {"kind": "text", "text": "Fictional", "locked": True}},
        {"city": {"kind": "text", "text": "Fictional", "evidence": {}}},
        {"city": {"kind": "text", "text": "Fictional", "created_by": "person"}},
        {"size": {"kind": "numeric", "min_value": "25", "unit": "people"}},
        {"size": {"kind": "text", "text": "Fictional", "company_id": "new"}},
        {"name": {"kind": "text", "text": "x" * 161}},
        {"industry": {"kind": "text", "text": "x" * 2049}},
    ],
)
def test_rejects_contacts_person_aliases_coercion_and_untrusted_authority(values: object) -> None:
    with pytest.raises(ProspectFactValidationError):
        validate_company_fields(values)


def test_registry_is_distinct_closed_and_returns_detached_descriptors() -> None:
    first = company_field_registry()
    assert [field["key"] for field in first] == ["name", "industry", "city", "size"]
    assert all(field["numeric"] is False for field in first)
    first[0]["label"] = "Changed external copy"
    assert company_field_registry()[0]["label"] == "Company name"
