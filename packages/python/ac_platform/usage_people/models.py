"""This environment's secret for pseudonymous person ids in the usage export (see
``pseudonyms``): one row, the HMAC-SHA-256 inner and outer padded keys, never answered."""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import CheckConstraint, DateTime, Integer, LargeBinary
from sqlalchemy.orm import Mapped, mapped_column

from ac_platform.db.base import Base


class MetricsPseudonymKey(Base):
    """The key that turns person ids into usage pseudonyms here (made once, kept)."""

    __tablename__ = "metrics_pseudonym_keys"
    __table_args__ = (
        CheckConstraint("id = 1", name="single"),
        CheckConstraint("length(inner_pad) = 64 AND length(outer_pad) = 64", name="pad_lengths"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=False)
    inner_pad: Mapped[bytes] = mapped_column(LargeBinary)
    outer_pad: Mapped[bytes] = mapped_column(LargeBinary)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
