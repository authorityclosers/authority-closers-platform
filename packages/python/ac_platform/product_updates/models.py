"""Append-only product notes and seen receipts; notifications can be read once."""

from __future__ import annotations

from datetime import date, datetime
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import (
    JSON,
    Boolean,
    CheckConstraint,
    Date,
    DateTime,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
    Uuid,
    event,
    false,
    func,
    inspect,
)
from sqlalchemy.engine import Connection
from sqlalchemy.orm import Mapped, Mapper, mapped_column, validates

from ac_platform.db.base import Base


class ProductUpdate(Base):
    __tablename__ = "product_updates"
    __table_args__ = (
        CheckConstraint("length(title) BETWEEN 1 AND 60", name="title_length"),
        CheckConstraint("audience IN ('everyone', 'org_admins', 'testers')", name="audience"),
        CheckConstraint("status IN ('draft', 'approved', 'published')", name="status"),
        CheckConstraint("created_by IN ('seed', 'deploy', 'admin')", name="created_by"),
        CheckConstraint("json_array_length(items) BETWEEN 1 AND 4", name="items"),
        CheckConstraint(
            "(version = 1 AND supersedes_id IS NULL) OR "
            "(version > 1 AND supersedes_id IS NOT NULL)",
            name="version_supersession",
        ),
        CheckConstraint("(status = 'published') = (published_at IS NOT NULL)", name="publication"),
        UniqueConstraint("note_key", "version", name="uq_product_updates_note_version"),
        UniqueConstraint("supersedes_id", name="uq_product_updates_successor"),
    )

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    note_key: Mapped[str] = mapped_column(String(128), nullable=False)
    version: Mapped[int] = mapped_column(Integer, nullable=False)
    supersedes_id: Mapped[UUID | None] = mapped_column(ForeignKey("product_updates.id"))
    release_id: Mapped[str] = mapped_column(String(128), nullable=False)
    source_pr: Mapped[int | None] = mapped_column(Integer)
    note_date: Mapped[date] = mapped_column(Date, nullable=False)
    title: Mapped[str] = mapped_column(String, nullable=False)
    items: Mapped[list[str]] = mapped_column(JSON(none_as_null=True), nullable=False)
    audience: Mapped[str] = mapped_column(
        String(16), nullable=False, default="everyone", server_default="everyone"
    )
    major: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default=false()
    )
    feature_key: Mapped[str | None] = mapped_column(String(128))
    status: Mapped[str] = mapped_column(String(16), nullable=False)
    created_by: Mapped[str] = mapped_column(String(16), nullable=False)
    created_by_person_id: Mapped[UUID | None] = mapped_column(ForeignKey("persons.id"))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    @validates("items")
    def _validate_items(self, _key: str, value: list[str]) -> list[str]:
        if (
            not isinstance(value, list)
            or not 1 <= len(value) <= 4
            or any(not isinstance(item, str) or len(item) > 200 for item in value)
        ):
            raise ValueError("product update items must be 1–4 strings of up to 200 characters")
        return value


class UpdateSeen(Base):
    __tablename__ = "update_seen"
    __table_args__ = (UniqueConstraint("person_id", "note_key", name="uq_update_seen_person_note"),)

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    person_id: Mapped[UUID] = mapped_column(ForeignKey("persons.id"), nullable=False)
    note_key: Mapped[str] = mapped_column(String(128), nullable=False)
    seen_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class Notification(Base):
    __tablename__ = "notifications"
    __table_args__ = (
        CheckConstraint(
            "kind IN ('report_ready', 'analysis_paused', 'invite_received')", name="kind"
        ),
        CheckConstraint(
            r"href LIKE '/%' AND href NOT LIKE '//%' AND href = replace(href, '\', '')",
            name="relative_href",
        ),
        UniqueConstraint("person_id", "dedupe_key", name="uq_notifications_person_dedupe"),
    )

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    person_id: Mapped[UUID] = mapped_column(ForeignKey("persons.id"), nullable=False)
    tenant_id: Mapped[UUID | None] = mapped_column(ForeignKey("tenants.id"))
    kind: Mapped[str] = mapped_column(String(32), nullable=False)
    dedupe_key: Mapped[str] = mapped_column(String(128), nullable=False)
    title: Mapped[str] = mapped_column(String(200), nullable=False)
    body: Mapped[str] = mapped_column(Text, nullable=False)
    href: Mapped[str] = mapped_column(String(2048), nullable=False)
    urgent: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default=false()
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    read_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), active_history=True)


class ProductUpdateMutationError(RuntimeError):
    """Immutable product-update or notification history was changed."""


@event.listens_for(ProductUpdate, "before_update")
@event.listens_for(ProductUpdate, "before_delete")
@event.listens_for(UpdateSeen, "before_update")
@event.listens_for(UpdateSeen, "before_delete")
@event.listens_for(Notification, "before_delete")
def _reject_mutation(_mapper: Mapper[Any], _connection: Connection, _target: Base) -> None:
    raise ProductUpdateMutationError("product update history is append-only; deletes are refused")


@event.listens_for(Notification, "before_update")
def _guard_notification_read(
    _mapper: Mapper[Notification], _connection: Connection, target: Notification
) -> None:
    attributes = inspect(target).attrs
    history = attributes.read_at.history
    if (
        list(history.deleted) != [None]
        or not history.added
        or history.added[0] is None
        or any(attr.history.has_changes() for attr in attributes if attr.key != "read_at")
    ):
        raise ProductUpdateMutationError("only notifications.read_at may be set, once")
