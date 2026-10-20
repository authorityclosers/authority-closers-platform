"""Daily reference rates, stored once per day and never changed (see ``reference``)."""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from uuid import UUID

from sqlalchemy import CheckConstraint, Date, DateTime, Numeric, String, UniqueConstraint, Uuid
from sqlalchemy.orm import Mapped, mapped_column

from ac_platform.db.base import Base


class FxReferenceRate(Base):
    """Rupees per US dollar on one day, from one published source (only ever added)."""

    __tablename__ = "fx_reference_rates"
    __table_args__ = (
        UniqueConstraint("day", "base", "quote", "source", name="uq_fx_reference_rates_day"),
        CheckConstraint("base = 'USD' AND quote = 'INR'", name="pair"),
        CheckConstraint("rate > 0", name="rate_positive"),
    )

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True)
    day: Mapped[date] = mapped_column(Date)
    base: Mapped[str] = mapped_column(String(3))
    quote: Mapped[str] = mapped_column(String(3))
    rate: Mapped[Decimal] = mapped_column(Numeric(12, 4))
    source: Mapped[str] = mapped_column(String(16))
    fetched_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
