"""Tenant-scoped source objects and permanent recording reference history (ADR 0033)."""

from datetime import datetime
from uuid import UUID

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    String,
    UniqueConstraint,
    Uuid,
    text,
)
from sqlalchemy.ext.compiler import compiles
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.sql.expression import ColumnElement

from ac_platform.conversation_intelligence.models import recording_fk
from ac_platform.db.base import Base


class _SourceDigestHexExpression(ColumnElement[bool]):
    inherit_cache = True


@compiles(_SourceDigestHexExpression, "postgresql")
def _compile_postgresql_digest_hex(
    _element: _SourceDigestHexExpression, _compiler: object, **_kw: object
) -> str:
    return "source_sha256 ~ '^[0-9a-f]{64}$'"


@compiles(_SourceDigestHexExpression)
def _compile_default_digest_hex(
    _element: _SourceDigestHexExpression, _compiler: object, **_kw: object
) -> str:
    return "length(source_sha256) = 64 AND source_sha256 = lower(source_sha256)"


class ConversationSourceObject(Base):
    __tablename__ = "conversation_source_objects"
    __table_args__ = (
        UniqueConstraint("id", "tenant_id"),
        CheckConstraint(_SourceDigestHexExpression(), name="sha256"),
        Index(
            "uq_source_object_live",
            "tenant_id",
            "source_sha256",
            unique=True,
            postgresql_where=text("deleted_at IS NULL"),
            sqlite_where=text("deleted_at IS NULL"),
        ),
    )
    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True)
    tenant_id: Mapped[UUID] = mapped_column(ForeignKey("tenants.id"))
    source_sha256: Mapped[str] = mapped_column(String(64))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class ConversationSourceReference(Base):
    __tablename__ = "conversation_source_references"
    __table_args__ = (
        recording_fk(),
        ForeignKeyConstraint(
            ["source_object_id", "tenant_id"],
            ["conversation_source_objects.id", "conversation_source_objects.tenant_id"],
        ),
        CheckConstraint(
            "(released_at IS NULL AND release_reason IS NULL) OR "
            "(released_at IS NOT NULL AND release_reason IS NOT NULL "
            "AND length(trim(release_reason)) > 0)",
            name="release_pair",
        ),
        Index(
            "ix_source_reference_live",
            "tenant_id",
            "source_object_id",
            postgresql_where=text("released_at IS NULL"),
        ),
    )
    recording_id: Mapped[UUID] = mapped_column(Uuid, primary_key=True)
    tenant_id: Mapped[UUID] = mapped_column(Uuid)
    person_id: Mapped[UUID] = mapped_column(Uuid)
    source_object_id: Mapped[UUID] = mapped_column(Uuid)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    released_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    release_reason: Mapped[str | None] = mapped_column(String(64))
