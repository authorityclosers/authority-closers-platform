from __future__ import annotations

from dataclasses import FrozenInstanceError
from decimal import Decimal

import pytest

from ac_platform.conversation_intelligence.prospect_fact_contract import (
    FactRevision,
    NumericFactValue,
    ProspectFactValidationError,
    SourceSupport,
    TextFactValue,
    UnknownFactValue,
    normalize_numeric_fact_value,
    validate_append_only_successor,
)


def _support(
    support_id: str = "support-1",
    *,
    source_id: str = "source-lifecycle-1",
    revision_id: str = "source-revision-1",
    revision: int = 1,
    wording: str = "₹15–20 lakh per year",
) -> SourceSupport:
    return SourceSupport(
        support_id=support_id,
        source_lifecycle_id=source_id,
        source_revision_id=revision_id,
        source_revision=revision,
        source_kind="call_transcript",
        raw_wording=wording,
    )


def _fact(
    *,
    revision_id: str = "fact-revision-1",
    revision: int = 1,
    supports: tuple[SourceSupport, ...] | None = None,
    value: TextFactValue | NumericFactValue | UnknownFactValue | None = None,
    supersedes_revision_id: str | None = None,
) -> FactRevision:
    return FactRevision(
        fact_id="fact-1",
        revision_id=revision_id,
        revision=revision,
        field_key="caller-defined.finance.annual_revenue",
        value=value if value is not None else UnknownFactValue("source_unclear"),
        supports=supports if supports is not None else (_support(),),
        supersedes_revision_id=supersedes_revision_id,
    )


def test_numeric_range_preserves_amount_scale_period_and_approximation() -> None:
    value = normalize_numeric_fact_value(
        interval_shape="range",
        approximation="approximate",
        lower="15",
        upper="20",
        lower_inclusive=True,
        upper_inclusive=True,
        currency_code="INR",
        scale_as_stated="lakh",
        period="per_year",
        period_reference="as stated: last financial year",
    )

    assert value == NumericFactValue(
        interval_shape="range",
        approximation="approximate",
        lower=Decimal("15"),
        upper=Decimal("20"),
        lower_inclusive=True,
        upper_inclusive=True,
        currency_code="INR",
        scale_as_stated="lakh",
        period="per_year",
        period_reference="as stated: last financial year",
    )
    assert value.lower == Decimal("15")
    assert value.upper == Decimal("20")
    assert value.scale_as_stated == "lakh"
    assert value.period_reference == "as stated: last financial year"


def test_open_and_closed_bounds_remain_distinct() -> None:
    strict = normalize_numeric_fact_value(
        interval_shape="upper_bound",
        approximation="exact",
        upper="50000",
        upper_inclusive=False,
        currency_code="USD",
    )
    inclusive = normalize_numeric_fact_value(
        interval_shape="upper_bound",
        approximation="exact",
        upper="50000",
        upper_inclusive=True,
        currency_code="USD",
    )

    assert strict.upper == inclusive.upper == Decimal("50000")
    assert strict.upper_inclusive is False
    assert inclusive.upper_inclusive is True


@pytest.mark.parametrize(
    ("kwargs", "code"),
    [
        (
            {
                "interval_shape": "range",
                "approximation": "exact",
                "lower": "20",
                "upper": "15",
                "lower_inclusive": True,
                "upper_inclusive": True,
            },
            "interval_shape_bounds_mismatch",
        ),
        (
            {
                "interval_shape": "point",
                "approximation": "exact",
                "lower": "50000",
                "upper": "50000",
                "lower_inclusive": True,
                "upper_inclusive": False,
            },
            "interval_shape_bounds_mismatch",
        ),
        (
            {
                "interval_shape": "upper_bound",
                "approximation": "exact",
                "upper": "50000",
                "upper_inclusive": None,
            },
            "interval_shape_bounds_mismatch",
        ),
        (
            {
                "interval_shape": "point",
                "approximation": "exact",
                "lower": "1.00001",
                "upper": "1.00001",
                "lower_inclusive": True,
                "upper_inclusive": True,
            },
            "invalid_numeric_bound",
        ),
        (
            {
                "interval_shape": "point",
                "approximation": "exact",
                "lower": 1.25,
                "upper": 1.25,
                "lower_inclusive": True,
                "upper_inclusive": True,
            },
            "invalid_numeric_bound",
        ),
    ],
)
def test_invalid_numeric_shapes_and_precision_are_rejected(kwargs, code) -> None:
    with pytest.raises(ProspectFactValidationError) as error:
        normalize_numeric_fact_value(**kwargs)
    assert error.value.code == code


def test_numeric_currency_unit_and_cadence_are_separate_and_not_converted() -> None:
    value = normalize_numeric_fact_value(
        interval_shape="point",
        approximation="exact",
        lower=Decimal("2"),
        upper=Decimal("2"),
        lower_inclusive=True,
        upper_inclusive=True,
        unit="sessions",
        cadence="per week",
        component="setup fee",
        tax_treatment="not stated",
        period="per_month",
    )
    assert value.unit == "sessions"
    assert value.currency_code is None
    assert value.cadence == "per week"
    assert value.component == "setup fee"
    assert value.tax_treatment == "not stated"
    assert value.period == "per_month"

    with pytest.raises(ProspectFactValidationError) as error:
        normalize_numeric_fact_value(
            interval_shape="point",
            approximation="exact",
            lower=1,
            upper=1,
            lower_inclusive=True,
            upper_inclusive=True,
            currency_code="USD",
            unit="sessions",
        )
    assert error.value.code == "currency_and_unit_are_exclusive"


def test_explicit_unknown_period_stays_distinct_from_unrecorded_period() -> None:
    unrecorded = normalize_numeric_fact_value(
        interval_shape="point",
        approximation="unknown",
        lower="0",
        upper="0",
        lower_inclusive=True,
        upper_inclusive=True,
    )
    explicit_unknown = normalize_numeric_fact_value(
        interval_shape="point",
        approximation="unknown",
        lower="0",
        upper="0",
        lower_inclusive=True,
        upper_inclusive=True,
        period="unknown",
        period_reference="unknown as stated",
    )

    assert unrecorded.period is None
    assert explicit_unknown.period == "unknown"
    assert explicit_unknown.period_reference == "unknown as stated"


def test_unknown_is_explicit_and_different_from_missing_value() -> None:
    unknown = _fact(value=UnknownFactValue("speaker_uncertain"))
    assert isinstance(unknown.value, UnknownFactValue)
    with pytest.raises(ProspectFactValidationError) as error:
        FactRevision(
            fact_id="fact-1",
            revision_id="fact-revision-missing",
            revision=1,
            field_key="caller-defined.unknown",
            value=None,  # type: ignore[arg-type]
            supports=(_support(),),
        )
    assert error.value.code == "invalid_fact_value"


def test_fact_can_have_multiple_independent_source_supports() -> None:
    first = _support("support-1")
    second = _support(
        "support-2",
        source_id="source-lifecycle-2",
        revision_id="source-revision-7",
        revision=7,
        wording="It is around twenty lakhs annually.",
    )
    fact = _fact(supports=(first, second), value=UnknownFactValue("needs_review"))

    assert fact.supports == (first, second)
    assert fact.supports[0].source_lifecycle_id != fact.supports[1].source_lifecycle_id
    assert fact.supports[1].source_revision == 7


def test_source_support_requires_lifecycle_identity_and_revision() -> None:
    with pytest.raises(ProspectFactValidationError) as error:
        SourceSupport(
            support_id="support-1",
            source_lifecycle_id="",
            source_revision_id="source-revision-1",
            source_revision=1,
            source_kind="transcript",
            raw_wording="A fictional source phrase.",
        )
    assert error.value.code == "invalid_source_lifecycle_id"


def test_long_unicode_text_is_preserved_without_silent_truncation() -> None:
    original = "  Prospect said: " + ("₹😀 café " * 200) + "  "
    text_value = TextFactValue(original)
    source = _support(wording=original)

    assert text_value.text == original
    assert source.raw_wording == original
    assert len(text_value.text) > 500


def test_revision_successor_is_append_only_and_must_link_previous_revision() -> None:
    original = _fact(
        value=TextFactValue("The caller described a fictional range."),
    )
    successor = _fact(
        revision_id="fact-revision-2",
        revision=2,
        value=TextFactValue("The caller later corrected the fictional range."),
        supersedes_revision_id=original.revision_id,
    )

    validate_append_only_successor(original, successor)
    assert original.value.text == "The caller described a fictional range."
    assert successor.value.text == "The caller later corrected the fictional range."
    with pytest.raises(FrozenInstanceError):
        original.revision = 2  # type: ignore[misc]

    wrong_link = _fact(
        revision_id="fact-revision-3",
        revision=3,
        value=UnknownFactValue("uncertain"),
        supersedes_revision_id="unrelated-revision",
    )
    with pytest.raises(ProspectFactValidationError) as error:
        validate_append_only_successor(successor, wrong_link)
    assert error.value.code == "successor_link_mismatch"

    wrong_field = FactRevision(
        fact_id=successor.fact_id,
        revision_id="fact-revision-3",
        revision=3,
        field_key="caller-defined.different_field",
        value=UnknownFactValue("uncertain"),
        supports=(_support("support-3"),),
        supersedes_revision_id=successor.revision_id,
    )
    with pytest.raises(ProspectFactValidationError) as error:
        validate_append_only_successor(successor, wrong_field)
    assert error.value.code == "successor_field_mismatch"


def test_validation_errors_never_echo_raw_text() -> None:
    synthetic_phrase = "fictional phrase that must not appear in errors"
    with pytest.raises(ProspectFactValidationError) as error:
        TextFactValue(synthetic_phrase + "\x00invalid")
    assert synthetic_phrase not in str(error.value)
    assert error.value.code == "invalid_text_value"
