"""Offer Studio versions: every save of an offer is a new row; none is changed or removed.

The schema gate allows no database triggers, so the ORM refuses updates and deletes (as bug
reports and audit events do).
"""

from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID

from sqlalchemy import (
    JSON,
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    UniqueConstraint,
    Uuid,
    event,
)
from sqlalchemy.orm import Mapped, mapped_column

from ac_platform.db.base import Base


class AdminOfferVersion(Base):
    """One saved version of an internal offer (Admin's Offer Studio).

    The body is the studio's own offer document (features, value equation, positioning,
    internal price tiers, ideas); the API bounds its size and keeps it as given. Archiving
    is a new version with ``archived`` set, so the history stays whole.
    """

    __tablename__ = "admin_offer_versions"
    __table_args__ = (
        UniqueConstraint("offer_id", "version", name="uq_admin_offer_version"),
        CheckConstraint("version >= 1", name="offer_version_positive"),
        CheckConstraint("length(trim(name)) BETWEEN 1 AND 200", name="offer_name_length"),
        Index("ix_admin_offer_versions_tenant", "tenant_id", "offer_id", "version"),
    )

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True)
    tenant_id: Mapped[UUID] = mapped_column(Uuid, ForeignKey("tenants.id"))
    offer_id: Mapped[UUID] = mapped_column(Uuid)
    version: Mapped[int] = mapped_column(Integer)
    name: Mapped[str] = mapped_column(String(200))
    body: Mapped[dict[str, Any]] = mapped_column(JSON)
    archived: Mapped[bool] = mapped_column(Boolean, default=False)
    author_person_id: Mapped[UUID] = mapped_column(Uuid, ForeignKey("persons.id"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class OfferHistoryError(RuntimeError):
    """An offer version was about to be changed or deleted."""


@event.listens_for(AdminOfferVersion, "before_update")
def _refuse_update(_mapper: object, _connection: object, _target: object) -> None:
    raise OfferHistoryError("Offer versions are append-only.")


@event.listens_for(AdminOfferVersion, "before_delete")
def _refuse_delete(_mapper: object, _connection: object, _target: object) -> None:
    raise OfferHistoryError("Offer versions are append-only.")
