"""Human-authored literal Company fields; no extraction or identity matching."""

from dataclasses import asdict
from types import MappingProxyType
from typing import Any

from ac_platform.conversation_intelligence.prospect_fact_contract import (
    ProspectFactValidationError,
    TextFactValue,
    UnknownFactValue,
)
from ac_platform.conversation_intelligence.prospect_fields import ProspectField

COMPANY_FIELD_REGISTRY = MappingProxyType(
    {
        field.key: field
        for field in (
            ProspectField("name", "Company name", max_length=160),
            ProspectField("industry", "Industry"),
            ProspectField("city", "City"),
            ProspectField("size", "Business size"),
        )
    }
)


def company_field_registry() -> list[dict[str, Any]]:
    return [asdict(field) for field in COMPANY_FIELD_REGISTRY.values()]


def validate_company_fields(values: object) -> dict[str, dict[str, str]]:
    """Validate person commands without interpreting size or assigning a company.

    Candidate extraction has its own source/role/subject-bound validator. This
    command port never accepts evidence, contacts, numeric coercion or actor data.
    """
    if not isinstance(values, dict) or not 1 <= len(values) <= len(COMPANY_FIELD_REGISTRY):
        raise ProspectFactValidationError("invalid_company_fields")
    result: dict[str, dict[str, str]] = {}
    for key, value in values.items():
        field = COMPANY_FIELD_REGISTRY.get(key)
        if field is None or not isinstance(value, dict):
            raise ProspectFactValidationError("invalid_company_field")
        if value.get("kind") == "text" and set(value) == {"kind", "text"}:
            text = TextFactValue(value["text"]).text
            if len(text) > field.max_length:
                raise ProspectFactValidationError("company_field_too_long")
            result[key] = {"kind": "text", "text": text}
        elif value.get("kind") == "unknown" and set(value) == {"kind", "reason"}:
            UnknownFactValue(value["reason"])
            reason = value["reason"]
            if key == "name" or reason not in {"not_asked", "not_mentioned"}:
                raise ProspectFactValidationError("invalid_company_unknown")
            result[key] = {"kind": "unknown", "reason": reason}
        else:
            raise ProspectFactValidationError("invalid_company_field_value")
    return result
