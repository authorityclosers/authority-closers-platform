"""Typed values for call objects: one JSON shape per value kind, checked strictly.

Pure: no I/O. Numbers reuse the prospect fact contract's ``NumericFactValue`` so a
call object and a prospect field revision hold the same numeric statement.
"""

from __future__ import annotations

import re
from dataclasses import asdict
from decimal import Decimal
from typing import Any

from ac_platform.call_data.taxonomy import OBJECTION_KINDS, ObjectType
from ac_platform.conversation_intelligence.prospect_fact_contract import (
    NumericFactValue,
    ProspectFactValidationError,
)

MAX_TEXT = 400
_DATE = re.compile(r"\d{4}-\d{2}-\d{2}\Z")
_TIME = re.compile(r"([01]\d|2[0-3]):[0-5]\d\Z")


class CallValueError(ValueError):
    """A value that does not fit its type; ``code`` is stable and content-free."""

    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(code)


def _text(value: object, code: str, *, required: bool = True) -> str | None:
    if value is None and not required:
        return None
    if not isinstance(value, str) or "\x00" in value:
        raise CallValueError(code)
    text = " ".join(value.split())
    if not text:
        if required:
            raise CallValueError(code)
        return None
    if len(text) > MAX_TEXT:
        raise CallValueError(f"{code}_too_long")
    return text


def _keys(value: dict[str, Any], allowed: set[str], required: set[str]) -> None:
    if not required <= set(value) <= allowed:
        raise CallValueError("value_keys")


def _when(value: object) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise CallValueError("when_shape")
    _keys(value, {"text", "date", "time", "purpose"}, {"text"})
    result: dict[str, Any] = {"text": _text(value["text"], "when_text")}
    date = value.get("date")
    if date is not None:
        if not isinstance(date, str) or not _DATE.match(date):
            raise CallValueError("when_date")
        result["date"] = date
    time = value.get("time")
    if time is not None:
        if not isinstance(time, str) or not _TIME.match(time) or date is None:
            raise CallValueError("when_time")
        result["time"] = time
    purpose = _text(value.get("purpose"), "when_purpose", required=False)
    if purpose:
        result["purpose"] = purpose
    return result


def _numeric(value: dict[str, Any]) -> dict[str, Any]:
    said = _text(value.get("text"), "numeric_text")
    fields = {key: item for key, item in value.items() if key not in ("kind", "text")}
    try:
        numeric = NumericFactValue(**fields)
    except (TypeError, ProspectFactValidationError) as error:
        raise CallValueError("numeric_value") from error
    encoded = {
        key: str(item) if isinstance(item, Decimal) else item
        for key, item in asdict(numeric).items()
        if item is not None
    }
    return {"text": said, **encoded}


def validate_value(kind_type: ObjectType, value: object) -> dict[str, Any]:
    """Return the canonical stored value for ``kind_type`` or raise ``CallValueError``."""
    if not isinstance(value, dict):
        raise CallValueError("value_shape")
    kind = kind_type.kind
    if kind == "text":
        _keys(value, {"text"}, {"text"})
        return {"text": _text(value["text"], "text")}
    if kind == "numeric":
        return _numeric(value)
    if kind == "when":
        return _when(value)
    if kind == "enum":
        _keys(value, {"enum"}, {"enum"})
        if value["enum"] not in kind_type.enum_values:
            raise CallValueError("enum_value")
        return {"enum": value["enum"]}
    if kind == "person":
        _keys(value, {"name", "role", "relation"}, set())
        person = {
            key: text
            for key in ("name", "role", "relation")
            if (text := _text(value.get(key), f"person_{key}", required=False))
        }
        if not person:
            raise CallValueError("person_empty")
        return person
    if kind == "commitment":
        _keys(value, {"text", "due"}, {"text"})
        commitment: dict[str, Any] = {"text": _text(value["text"], "commitment_text")}
        if value.get("due") is not None:
            commitment["due"] = _when(value["due"])
        return commitment
    if kind == "objection":
        _keys(value, {"text", "kind", "resolved"}, {"text", "kind", "resolved"})
        if value["kind"] not in OBJECTION_KINDS or not isinstance(value["resolved"], bool):
            raise CallValueError("objection_fields")
        return {
            "text": _text(value["text"], "objection_text"),
            "kind": value["kind"],
            "resolved": value["resolved"],
        }
    if kind == "question":
        _keys(value, {"text", "answered"}, {"text", "answered"})
        if not isinstance(value["answered"], bool):
            raise CallValueError("question_answered")
        return {"text": _text(value["text"], "question_text"), "answered": value["answered"]}
    if kind == "ratio":
        _keys(value, {"parts"}, {"parts"})
        parts = value["parts"]
        if (
            not isinstance(parts, dict)
            or not parts
            or any(
                not isinstance(k, str) or isinstance(v, bool) or not isinstance(v, (int, float))
                for k, v in parts.items()
            )
            or any(not 0 <= v <= 1 for v in parts.values())
            or abs(sum(parts.values()) - 1) > 0.02
        ):
            raise CallValueError("ratio_parts")
        return {"parts": {k: round(float(v), 4) for k, v in parts.items()}}
    raise CallValueError("value_kind")


ALLOWED_KEYS: dict[str, frozenset[str]] = {
    "text": frozenset({"text"}),
    "numeric": frozenset(
        {
            "text",
            "interval_shape",
            "approximation",
            "lower",
            "upper",
            "lower_inclusive",
            "upper_inclusive",
            "currency_code",
            "unit",
            "period",
        }
    ),
    "when": frozenset({"text", "date", "time", "purpose"}),
    "enum": frozenset({"enum"}),
    "person": frozenset({"name", "role", "relation"}),
    "commitment": frozenset({"text", "due"}),
    "objection": frozenset({"text", "kind", "resolved"}),
    "question": frozenset({"text", "answered"}),
    "ratio": frozenset({"parts"}),
}


def _present(value: Any) -> bool:
    return value is not None and not (isinstance(value, str) and not value.strip())


def _number_text(value: Any) -> Any:
    """A JSON number from a model becomes the exact decimal string the contract wants."""
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return value
    return format(Decimal(str(value)).normalize(), "f")


def from_model(kind_type: ObjectType, raw: object) -> dict[str, Any]:
    """A model's value made tidy, then checked strictly like any other value.

    Empty and unknown keys are dropped (a model fills every property of the
    schema it was given); numbers become exact decimal strings; a numeric
    statement's missing flags take the only values its shape allows.
    """
    if not isinstance(raw, dict):
        raise CallValueError("value_shape")
    allowed = ALLOWED_KEYS[kind_type.kind]
    value = {k: v for k, v in raw.items() if k in allowed and _present(v)}
    if kind_type.kind == "commitment" and isinstance(value.get("due"), dict):
        due = {k: v for k, v in value["due"].items() if k in ALLOWED_KEYS["when"] and _present(v)}
        if "text" in due:
            value["due"] = due
        else:
            value.pop("due")
    elif kind_type.kind == "commitment":
        value.pop("due", None)
    if kind_type.kind == "numeric":
        for key in ("lower", "upper"):
            if key in value:
                value[key] = _number_text(value[key])
        shape = value.get("interval_shape")
        if shape is None and "lower" in value:
            shape = "point" if value.get("upper", value["lower"]) == value["lower"] else "range"
            value["interval_shape"] = shape
        if shape == "point" and "lower" in value:
            value.setdefault("upper", value["lower"])
        value.setdefault("approximation", "exact" if shape == "point" else "approximate")
        if shape in ("point", "range"):
            value.setdefault("lower_inclusive", True)
            value.setdefault("upper_inclusive", True)
        elif shape == "lower_bound":
            value.setdefault("lower_inclusive", True)
            value.pop("upper_inclusive", None)
        elif shape == "upper_bound":
            value.setdefault("upper_inclusive", True)
            value.pop("lower_inclusive", None)
        if "currency_code" in value and "unit" in value:
            value.pop("unit")
        if "text" not in value and "lower" in value:
            upper = value.get("upper", value["lower"])
            said = value["lower"] if upper == value["lower"] else f"{value['lower']}-{upper}"
            prefix = "Rs " if value.get("currency_code") == "INR" else ""
            suffix = f" {value['unit']}" if "unit" in value else ""
            period = f" a {value['period']}" if value.get("period") in ("month", "year") else ""
            value["text"] = f"{prefix}{said}{suffix}{period}"
    return validate_value(kind_type, value)


_ENUM_WORDS = {
    "decided_yes": "Said yes",
    "decided_no": "Said no",
    "pending": "Not decided yet",
    "not_discussed": "Not discussed",
    "low": "Low",
    "medium": "Medium",
    "high": "High",
    "deal_closed": "Deal closed",
    "follow_up_agreed": "Follow-up agreed",
    "meeting_scheduled": "Meeting scheduled",
    "no_sale": "No sale",
    "not_a_fit": "Not a fit",
    "callback_requested": "Asked for a call back",
    "no_conversation": "No real conversation",
    "en": "English",
    "hi": "Hindi",
    "mr": "Marathi",
    "gu": "Gujarati",
    "other": "Other",
}


def display(kind_type: ObjectType, value: dict[str, Any]) -> str:
    """One short line a person reads."""
    kind = kind_type.kind
    if kind in ("text", "numeric"):
        return str(value["text"])
    if kind == "when":
        purpose = value.get("purpose")
        return f"{value['text']} · {purpose}" if purpose else str(value["text"])
    if kind == "enum":
        return _ENUM_WORDS.get(value["enum"], str(value["enum"]).replace("_", " ").capitalize())
    if kind == "person":
        name = value.get("name") or value.get("relation") or "Someone"
        role = value.get("role") or (value.get("relation") if value.get("name") else None)
        return f"{name} ({role})" if role else str(name)
    if kind == "commitment":
        due = value.get("due")
        return f"{value['text']} · by {due['text']}" if due else str(value["text"])
    if kind == "objection":
        return f"{value['text']} · {'resolved' if value['resolved'] else 'open'}"
    if kind == "question":
        return f"{value['text']} · {'answered' if value['answered'] else 'not answered'}"
    if kind == "ratio":
        return " · ".join(f"{k} {round(v * 100)}%" for k, v in value["parts"].items())
    return ""
