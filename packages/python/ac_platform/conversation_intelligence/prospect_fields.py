"""One value registry for person edits, profile reads and future extraction.

Numeric values retain the supplied interval, currency and units. No conversion
or business inference occurs here. Private contact keys are person-only.
"""

from dataclasses import asdict, dataclass
from decimal import Decimal
from types import MappingProxyType
from typing import Any

from ac_platform.conversation_intelligence.prospect_fact_contract import (
    NumericFactValue,
    ProspectFactValidationError,
    TextFactValue,
    UnknownFactValue,
)


@dataclass(frozen=True)
class ProspectField:
    key: str
    label: str
    numeric: bool = False
    person_only: bool = False
    max_length: int = 2048


FIELD_REGISTRY = MappingProxyType(
    {
        field.key: field
        for field in (
            ProspectField("name", "Name", max_length=160),
            ProspectField("business", "Business"),
            ProspectField("industry", "Industry"),
            ProspectField("city", "City"),
            ProspectField("role", "Role"),
            ProspectField("team_size", "Team size", numeric=True),
            ProspectField("turnover", "Turnover", numeric=True),
            ProspectField("main_pain", "Main pain"),
            ProspectField("budget", "Budget", numeric=True),
            ProspectField("timeline", "Timeline"),
            ProspectField("decision_maker", "Decision maker"),
            ProspectField("next_step", "Next step"),
            ProspectField("phone", "Phone", person_only=True, max_length=160),
            ProspectField("email", "Email", person_only=True, max_length=320),
        )
    }
)


def field_registry(*, for_extractor: bool = False) -> list[dict[str, Any]]:
    return [
        asdict(field)
        for field in FIELD_REGISTRY.values()
        if not for_extractor or not field.person_only
    ]


def validate_fields(values: object, *, detected: bool = False) -> dict[str, dict[str, Any]]:
    if not isinstance(values, dict) or not 1 <= len(values) <= len(FIELD_REGISTRY):
        raise ProspectFactValidationError("invalid_fields")
    result = {}
    for key, value in values.items():
        field = FIELD_REGISTRY.get(key)
        if field is None or (detected and field.person_only) or not isinstance(value, dict):
            raise ProspectFactValidationError("invalid_field")
        kind = value.get("kind")
        if kind == "text" and set(value) == {"kind", "text"}:
            text = TextFactValue(value["text"]).text
            if len(text) > field.max_length:
                raise ProspectFactValidationError("field_too_long")
            result[key] = {"kind": "text", "text": text}
        elif kind == "unknown" and set(value) == {"kind", "reason"}:
            UnknownFactValue(value["reason"])
            if value["reason"] not in ("not_asked", "not_mentioned") or (
                key == "name" and not detected
            ):
                raise ProspectFactValidationError("invalid_unknown_reason")
            result[key] = dict(value)
        elif kind == "numeric" and field.numeric:
            try:
                numeric = NumericFactValue(**{k: v for k, v in value.items() if k != "kind"})
            except TypeError:
                raise ProspectFactValidationError("invalid_numeric_value") from None
            encoded = {
                k: str(v) if isinstance(v, Decimal) else v
                for k, v in asdict(numeric).items()
                if v is not None
            }
            if any(isinstance(v, str) and len(v) > field.max_length for v in encoded.values()):
                raise ProspectFactValidationError("field_too_long")
            result[key] = {"kind": "numeric", **encoded}
        else:
            raise ProspectFactValidationError("invalid_field_value")
    return result


def public_profile_fields(fields: dict[str, Any]) -> dict[str, Any]:
    """Only these keys may enter an AI context or an export."""
    return {
        key: value
        for key, value in fields.items()
        if key in FIELD_REGISTRY and not FIELD_REGISTRY[key].person_only
    }


def validate_evidence(value: object) -> dict[str, Any]:
    if (
        not isinstance(value, dict)
        or set(value) != {"segment_id", "quote", "start_ms", "end_ms"}
        or any(
            not isinstance(value[k], str) or not value[k].strip() for k in ("segment_id", "quote")
        )
        or len(value["segment_id"]) > 128
        or len(value["quote"]) > 2048
        or any(type(value[k]) is not int for k in ("start_ms", "end_ms"))
        or not 0 <= value["start_ms"] < value["end_ms"]
    ):
        raise ProspectFactValidationError("invalid_field_evidence")
    return dict(value)
