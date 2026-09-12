"""Append-only learner app-update read receipts."""

from __future__ import annotations

from datetime import datetime
from uuid import UUID, uuid4

from sqlalchemy import (
    DateTime,
    ForeignKeyConstraint,
    Index,
    String,
    UniqueConstraint,
    Uuid,
    event,
    func,
)
from sqlalchemy.engine import Connection
from sqlalchemy.orm import Mapped, Mapper, mapped_column

from ac_platform.db.base import Base


class AppUpdateReadReceipt(Base):
    """One durable acknowledgement for one learner membership and release."""

    __tablename__ = "app_update_read_receipts"
    __table_args__ = (
        ForeignKeyConstraint(
            ["tenant_id", "person_id"],
            ["memberships.tenant_id", "memberships.person_id"],
            name="fk_app_update_read_receipts_tenant_id_memberships",
        ),
        UniqueConstraint(
            "tenant_id",
            "person_id",
            "release_id",
            name="uq_app_update_read_receipts_learner_release",
        ),
        Index(
            "ix_app_update_read_receipts_learner_read_at",
            "tenant_id",
            "person_id",
            "read_at",
        ),
    )

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid4)
    tenant_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    person_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    release_id: Mapped[str] = mapped_column(String(128), nullable=False)
    read_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class AppUpdateReceiptMutationError(RuntimeError):
    """A durable read receipt was changed or deleted."""


@event.listens_for(AppUpdateReadReceipt, "before_update")
def _guard_receipt_update(
    _mapper: Mapper[AppUpdateReadReceipt],
    _connection: Connection,
    _target: AppUpdateReadReceipt,
) -> None:
    raise AppUpdateReceiptMutationError("app update read receipts are append-only")


@event.listens_for(AppUpdateReadReceipt, "before_delete")
def _guard_receipt_delete(
    _mapper: Mapper[AppUpdateReadReceipt],
    _connection: Connection,
    _target: AppUpdateReadReceipt,
) -> None:
    raise AppUpdateReceiptMutationError("app update read receipts must not be deleted")


__all__ = ["AppUpdateReadReceipt", "AppUpdateReceiptMutationError"]
