"""Provider-free, append-only value contract for source-supported prospect facts.

This module deliberately defines data fidelity mechanics only. It does not
extract facts, authorize an owner, establish retention, persist records, or
define prospect/business semantics.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation


class ProspectFactValidationError(ValueError):
    """Validation failure with a stable, content-free code."""

    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(code)


_NUMERIC_SHAPES = frozenset({"point", "range", "lower_bound", "upper_bound", "unknown"})
_APPROXIMATION_STATES = frozenset({"exact", "approximate", "unknown"})
_CURRENCY_CODE = re.compile(r"[A-Z]{3}\Z")


def _nonempty_string(value: object, code: str) -> str:
    if not isinstance(value, str) or not value or not value.strip() or "\x00" in value:
        raise ProspectFactValidationError(code)
    return value


def _decimal(value: Decimal | int | str | None, code: str) -> Decimal | None:
    if value is None:
        return None
    if isinstance(value, (bool, float)):
        raise ProspectFactValidationError(code)
    if isinstance(value, Decimal):
        result = value
    elif isinstance(value, (int, str)):
        try:
            result = Decimal(value)
        except (InvalidOperation, ValueError):
            raise ProspectFactValidationError(code) from None
    else:
        raise ProspectFactValidationError(code)
    if not result.is_finite():
        raise ProspectFactValidationError(code)

    # Match NUMERIC(20, 4) without rounding.  The stated value is never
    # silently quantized or converted.
    _, digits, exponent = result.as_tuple()
    if not isinstance(exponent, int):
        raise ProspectFactValidationError(code)
    fractional_digits = max(-exponent, 0)
    integer_digits = max(len(digits) + exponent, 0)
    if fractional_digits > 4 or integer_digits > 16:
        raise ProspectFactValidationError(code)
    return result


@dataclass(frozen=True, slots=True)
class TextFactValue:
    """Text exactly as supplied by a caller; no trimming or truncation occurs."""

    text: str

    def __post_init__(self) -> None:
        _nonempty_string(self.text, "invalid_text_value")


@dataclass(frozen=True, slots=True)
class NumericFactValue:
    """A typed numeric statement retaining its original distinctions.

    ``period``, ``unit``, ``scale_as_stated``, ``component``, ``cadence`` and
    ``tax_treatment`` are caller-defined tokens/text.  This module does not
    normalize them into a closed business taxonomy or perform conversions.
    """

    interval_shape: str
    approximation: str
    lower: Decimal | None = None
    upper: Decimal | None = None
    lower_inclusive: bool | None = None
    upper_inclusive: bool | None = None
    currency_code: str | None = None
    unit: str | None = None
    scale_as_stated: str | None = None
    period: str | None = None
    period_reference: str | None = None
    component: str | None = None
    cadence: str | None = None
    tax_treatment: str | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.interval_shape, str) or self.interval_shape not in _NUMERIC_SHAPES:
            raise ProspectFactValidationError("invalid_interval_shape")
        if (
            not isinstance(self.approximation, str)
            or self.approximation not in _APPROXIMATION_STATES
        ):
            raise ProspectFactValidationError("invalid_approximation")

        lower = _decimal(self.lower, "invalid_numeric_bound")
        upper = _decimal(self.upper, "invalid_numeric_bound")
        object.__setattr__(self, "lower", lower)
        object.__setattr__(self, "upper", upper)

        if self.currency_code is not None and (
            not isinstance(self.currency_code, str)
            or not _CURRENCY_CODE.fullmatch(self.currency_code)
        ):
            raise ProspectFactValidationError("invalid_currency_code")
        if self.unit is not None:
            _nonempty_string(self.unit, "invalid_unit")
        if self.currency_code is not None and self.unit is not None:
            raise ProspectFactValidationError("currency_and_unit_are_exclusive")

        for name in (
            "scale_as_stated",
            "period",
            "period_reference",
            "component",
            "cadence",
            "tax_treatment",
        ):
            value = getattr(self, name)
            if value is not None:
                _nonempty_string(value, f"invalid_{name}")

        shape = self.interval_shape
        if shape == "point":
            valid = (
                lower is not None
                and upper is not None
                and lower == upper
                and self.lower_inclusive is True
                and self.upper_inclusive is True
            )
        elif shape == "range":
            valid = (
                lower is not None
                and upper is not None
                and lower < upper
                and isinstance(self.lower_inclusive, bool)
                and isinstance(self.upper_inclusive, bool)
            )
        elif shape == "lower_bound":
            valid = (
                lower is not None
                and upper is None
                and isinstance(self.lower_inclusive, bool)
                and self.upper_inclusive is None
            )
        elif shape == "upper_bound":
            valid = (
                lower is None
                and upper is not None
                and self.lower_inclusive is None
                and isinstance(self.upper_inclusive, bool)
            )
        else:
            valid = (
                lower is None
                and upper is None
                and self.lower_inclusive is None
                and self.upper_inclusive is None
            )
        if not valid:
            raise ProspectFactValidationError("interval_shape_bounds_mismatch")


@dataclass(frozen=True, slots=True)
class UnknownFactValue:
    """An explicit unknown, distinct from a missing/unrecorded fact."""

    reason_code: str | None = None

    def __post_init__(self) -> None:
        if self.reason_code is not None:
            _nonempty_string(self.reason_code, "invalid_unknown_reason")


type FactValue = TextFactValue | NumericFactValue | UnknownFactValue


@dataclass(frozen=True, slots=True)
class SourceSupport:
    """One independent support tied to a specific source lifecycle revision.

    Reference fields do not prove owner authorization or source availability.
    ``raw_wording`` is retained exactly; persistence/erasure rules belong to a
    separately approved storage contract.
    """

    support_id: str
    source_lifecycle_id: str
    source_revision_id: str
    source_revision: int
    source_kind: str
    raw_wording: str

    def __post_init__(self) -> None:
        for name in (
            "support_id",
            "source_lifecycle_id",
            "source_revision_id",
            "source_kind",
            "raw_wording",
        ):
            _nonempty_string(getattr(self, name), f"invalid_{name}")
        if (
            isinstance(self.source_revision, bool)
            or not isinstance(self.source_revision, int)
            or self.source_revision < 1
        ):
            raise ProspectFactValidationError("invalid_source_revision")


@dataclass(frozen=True, slots=True)
class FactRevision:
    """One immutable revision in a caller-owned fact history."""

    fact_id: str
    revision_id: str
    revision: int
    field_key: str
    value: FactValue
    supports: tuple[SourceSupport, ...]
    supersedes_revision_id: str | None = None

    def __post_init__(self) -> None:
        for name in ("fact_id", "revision_id", "field_key"):
            _nonempty_string(getattr(self, name), f"invalid_{name}")
        if (
            isinstance(self.revision, bool)
            or not isinstance(self.revision, int)
            or self.revision < 1
        ):
            raise ProspectFactValidationError("invalid_fact_revision")
        if not isinstance(self.value, (TextFactValue, NumericFactValue, UnknownFactValue)):
            raise ProspectFactValidationError("invalid_fact_value")
        if not isinstance(self.supports, tuple):
            try:
                immutable_supports = tuple(self.supports)
            except TypeError:
                raise ProspectFactValidationError("invalid_supports") from None
            object.__setattr__(self, "supports", immutable_supports)
        if not self.supports or any(not isinstance(item, SourceSupport) for item in self.supports):
            raise ProspectFactValidationError("supports_required")
        support_ids = tuple(item.support_id for item in self.supports)
        if len(set(support_ids)) != len(support_ids):
            raise ProspectFactValidationError("duplicate_support_id")
        if self.revision == 1:
            if self.supersedes_revision_id is not None:
                raise ProspectFactValidationError("initial_revision_cannot_supersede")
        else:
            if self.supersedes_revision_id is None:
                raise ProspectFactValidationError("successor_requires_superseded_revision")
            _nonempty_string(self.supersedes_revision_id, "invalid_superseded_revision")


def normalize_numeric_fact_value(
    *,
    interval_shape: str,
    approximation: str,
    lower: Decimal | int | str | None = None,
    upper: Decimal | int | str | None = None,
    lower_inclusive: bool | None = None,
    upper_inclusive: bool | None = None,
    currency_code: str | None = None,
    unit: str | None = None,
    scale_as_stated: str | None = None,
    period: str | None = None,
    period_reference: str | None = None,
    component: str | None = None,
    cadence: str | None = None,
    tax_treatment: str | None = None,
) -> NumericFactValue:
    """Validate caller-normalized numeric fields without conversion or guessing."""

    return NumericFactValue(
        interval_shape=interval_shape,
        approximation=approximation,
        lower=_decimal(lower, "invalid_numeric_bound"),
        upper=_decimal(upper, "invalid_numeric_bound"),
        lower_inclusive=lower_inclusive,
        upper_inclusive=upper_inclusive,
        currency_code=currency_code,
        unit=unit,
        scale_as_stated=scale_as_stated,
        period=period,
        period_reference=period_reference,
        component=component,
        cadence=cadence,
        tax_treatment=tax_treatment,
    )


def validate_append_only_successor(previous: FactRevision, candidate: FactRevision) -> None:
    """Require a new revision to point to, never replace, the prior revision."""

    if candidate.fact_id != previous.fact_id:
        raise ProspectFactValidationError("successor_fact_mismatch")
    if candidate.field_key != previous.field_key:
        raise ProspectFactValidationError("successor_field_mismatch")
    if candidate.revision_id == previous.revision_id:
        raise ProspectFactValidationError("revision_id_reused")
    if candidate.revision != previous.revision + 1:
        raise ProspectFactValidationError("nonconsecutive_fact_revision")
    if candidate.supersedes_revision_id != previous.revision_id:
        raise ProspectFactValidationError("successor_link_mismatch")
