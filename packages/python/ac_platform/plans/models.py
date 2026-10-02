"""Plans catalogue: one row per commercial plan (ADR 0046, Plans C1).

The catalogue is a foundation only. Every seeded row is ``coming_soon`` and no
route reads it until C2. NULL means an unset commercial or limit field; the
model never invents a value. Prices are minor units (paise, cents). Feature keys
and top-up packs are JSON lists checked in Python, because neither SQLite nor
PostgreSQL checks JSON shape; the scalar rules are database CHECK constraints
too, so a raw write cannot bypass them.
"""

from __future__ import annotations

import re
from datetime import UTC, datetime
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import (
    JSON,
    BigInteger,
    Boolean,
    CheckConstraint,
    DateTime,
    Integer,
    String,
    UniqueConstraint,
    Uuid,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column, validates

from ac_platform.db.base import Base

PLAN_KEY_PATTERN = re.compile(r"^[a-z][a-z0-9_]{1,39}$")
PLAN_STATUSES = ("draft", "coming_soon", "active", "retired")
TOP_UP_VALIDITY_RULE = "billing_year_end"
TOP_UP_PACK_FIELDS = frozenset({"key", "minutes", "validity_rule", "price_paise", "price_cents"})


class PlanValidationError(ValueError):
    """A plan field breaks the catalogue contract."""


def _utc_now() -> datetime:
    return datetime.now(UTC)


def validate_plan_key(key: object) -> str:
    if not isinstance(key, str) or PLAN_KEY_PATTERN.fullmatch(key) is None:
        raise PlanValidationError("plan key must match ^[a-z][a-z0-9_]{1,39}$")
    return key


def validate_feature_keys(value: object) -> list[str]:
    if not isinstance(value, list) or any(not isinstance(item, str) for item in value):
        raise PlanValidationError("feature_keys must be a list of strings")
    return list(value)


def _minor_units(pack: dict[str, Any], field: str) -> int | None:
    value = pack.get(field)
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise PlanValidationError(f"top-up pack {field} must be a non-negative integer or null")
    return value


def validate_top_up_packs(value: object) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        raise PlanValidationError("top_up_packs must be a list")
    packs: list[dict[str, Any]] = []
    seen: set[str] = set()
    for pack in value:
        if not isinstance(pack, dict) or set(pack) != TOP_UP_PACK_FIELDS:
            raise PlanValidationError(
                "top-up pack fields must be exactly key, minutes, validity_rule, "
                "price_paise, price_cents"
            )
        key = validate_plan_key(pack["key"])
        if key in seen:
            raise PlanValidationError(f"top-up pack key {key!r} is repeated")
        seen.add(key)
        minutes = pack["minutes"]
        if isinstance(minutes, bool) or not isinstance(minutes, int) or minutes <= 0:
            raise PlanValidationError("top-up pack minutes must be a positive integer")
        if pack["validity_rule"] != TOP_UP_VALIDITY_RULE:
            raise PlanValidationError(f"top-up pack validity_rule must be {TOP_UP_VALIDITY_RULE!r}")
        packs.append(
            {
                "key": key,
                "minutes": minutes,
                "validity_rule": TOP_UP_VALIDITY_RULE,
                "price_paise": _minor_units(pack, "price_paise"),
                "price_cents": _minor_units(pack, "price_cents"),
            }
        )
    return packs


class Plan(Base):
    """One commercial plan. ``status`` governs visibility; prices and limits stay NULL
    until the owner confirms them (C3), and nothing activates a plan in this slice."""

    __tablename__ = "plans"
    __table_args__ = (
        UniqueConstraint("key"),
        # PostgreSQL enforces the full key regex (migration 0065); this is the portable form.
        CheckConstraint("length(key) BETWEEN 2 AND 40", name="key_shape"),
        CheckConstraint(
            "status IN ('draft', 'coming_soon', 'active', 'retired')", name="status_supported"
        ),
        CheckConstraint(
            "monthly_price_paise IS NULL OR monthly_price_paise >= 0",
            name="monthly_price_paise_not_negative",
        ),
        CheckConstraint(
            "yearly_price_paise IS NULL OR yearly_price_paise >= 0",
            name="yearly_price_paise_not_negative",
        ),
        CheckConstraint(
            "monthly_price_cents IS NULL OR monthly_price_cents >= 0",
            name="monthly_price_cents_not_negative",
        ),
        CheckConstraint(
            "yearly_price_cents IS NULL OR yearly_price_cents >= 0",
            name="yearly_price_cents_not_negative",
        ),
        CheckConstraint(
            "included_minutes IS NULL OR included_minutes >= 0",
            name="included_minutes_not_negative",
        ),
        CheckConstraint("seat_min IS NULL OR seat_min >= 1", name="seat_min_positive"),
        CheckConstraint(
            "seat_min IS NULL OR seat_max IS NULL OR seat_max >= seat_min",
            name="seat_max_not_below_seat_min",
        ),
        CheckConstraint(
            "longest_call_minutes IS NULL OR longest_call_minutes > 0",
            name="longest_call_minutes_positive",
        ),
        CheckConstraint(
            "retention_days IS NULL OR retention_days > 0", name="retention_days_positive"
        ),
        CheckConstraint(
            "rollover_months IS NULL OR rollover_months >= 0", name="rollover_months_not_negative"
        ),
        CheckConstraint("revision >= 1", name="revision_positive"),
    )

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid4)
    key: Mapped[str] = mapped_column(String(40), nullable=False)
    name: Mapped[str] = mapped_column(String(80), nullable=False)
    audience: Mapped[str] = mapped_column(String(160), nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False)
    monthly_price_paise: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    yearly_price_paise: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    monthly_price_cents: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    yearly_price_cents: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    included_minutes: Mapped[int | None] = mapped_column(Integer, nullable=True)
    seat_min: Mapped[int | None] = mapped_column(Integer, nullable=True)
    seat_max: Mapped[int | None] = mapped_column(Integer, nullable=True)
    per_seat: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    longest_call_minutes: Mapped[int | None] = mapped_column(Integer, nullable=True)
    retention_days: Mapped[int | None] = mapped_column(Integer, nullable=True)
    rollover_months: Mapped[int | None] = mapped_column(Integer, nullable=True)
    feature_keys: Mapped[list[str]] = mapped_column(JSON, nullable=False, default=list)
    top_up_packs: Mapped[list[dict[str, Any]]] = mapped_column(JSON, nullable=False, default=list)
    sort_order: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    revision: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=_utc_now, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=_utc_now,
        onupdate=_utc_now,
        server_default=func.now(),
    )

    @validates("key")
    def _validate_key(self, _field: str, value: object) -> str:
        return validate_plan_key(value)

    @validates("feature_keys")
    def _validate_feature_keys(self, _field: str, value: object) -> list[str]:
        return validate_feature_keys(value)

    @validates("top_up_packs")
    def _validate_top_up_packs(self, _field: str, value: object) -> list[dict[str, Any]]:
        return validate_top_up_packs(value)


__all__ = [
    "PLAN_KEY_PATTERN",
    "PLAN_STATUSES",
    "TOP_UP_PACK_FIELDS",
    "TOP_UP_VALIDITY_RULE",
    "Plan",
    "PlanValidationError",
    "validate_feature_keys",
    "validate_plan_key",
    "validate_top_up_packs",
]
