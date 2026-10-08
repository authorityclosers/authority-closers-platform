"""Field fidelity and private-contact exclusion at the registry boundary."""

import pytest

from ac_platform.conversation_intelligence.prospect_fact_contract import ProspectFactValidationError
from ac_platform.conversation_intelligence.prospect_fields import (
    FIELD_REGISTRY,
    field_registry,
    public_profile_fields,
    validate_fields,
)


def test_registry_keeps_person_contacts_out_of_extraction_and_context() -> None:
    assert len(FIELD_REGISTRY) == 14
    assert len(field_registry(for_extractor=True)) == 12
    assert not {"phone", "email"} & {field["key"] for field in field_registry(for_extractor=True)}
    fields = {
        "business": {"kind": "text", "text": "Fictional Ltd"},
        "phone": {"kind": "text", "text": "+15555550123"},
        "email": {"kind": "text", "text": "fictional@example.test"},
    }
    assert validate_fields(fields) == fields
    assert public_profile_fields(fields) == {"business": fields["business"]}
    for key in ("phone", "email"):
        with pytest.raises(ProspectFactValidationError):
            validate_fields({key: fields[key]}, detected=True)


def test_numeric_and_text_values_preserve_stated_distinctions() -> None:
    numeric = {
        "kind": "numeric",
        "interval_shape": "range",
        "approximation": "approximate",
        "lower": "20.0000",
        "upper": "30",
        "lower_inclusive": True,
        "upper_inclusive": False,
        "currency_code": "INR",
        "scale_as_stated": "lakh",
        "period": "year",
    }
    assert validate_fields({"turnover": numeric}) == {"turnover": numeric}
    assert (
        validate_fields({"business": {"kind": "text", "text": "  Fictional  "}})["business"]["text"]
        == "  Fictional  "
    )
    for invalid in (
        {},
        {"made_up": {"kind": "text", "text": "x"}},
        {"city": None},
        {"city": {"kind": "text", "text": " "}},
        {"city": numeric},
        {"budget": {**numeric, "lower": 1.5}},
        {"budget": {**numeric, "currency_code": "inr"}},
        {"business": {"kind": "unknown", "reason": "guessed"}},
    ):
        with pytest.raises(ProspectFactValidationError):
            validate_fields(invalid)
    assert (
        validate_fields({"city": {"kind": "unknown", "reason": "not_asked"}})["city"]["reason"]
        == "not_asked"
    )
