"""Non-content batch decisions and one-time bindings to normal acquisition usage."""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    Integer,
    String,
    UniqueConstraint,
    Uuid,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column

from ac_platform.db.base import Base


class ConversationRecordingImport(Base):
    __tablename__ = "conversation_recording_imports"
    __table_args__ = (
        UniqueConstraint("id", "tenant_id"),
        ForeignKeyConstraint(
            ["tenant_id", "uploader_person_id"], ["memberships.tenant_id", "memberships.person_id"]
        ),
        CheckConstraint("length(manifest_sha256) = 64", name="manifest_hash"),
        CheckConstraint("length(policy_sha256) = 64", name="policy_hash"),
        CheckConstraint("total_files BETWEEN 1 AND 256", name="file_bound"),
        CheckConstraint("total_bytes BETWEEN 1 AND 1073741824", name="byte_bound"),
        CheckConstraint("expires_at > created_at", name="expiry"),
        Index("ix_conversation_recording_imports_tenant", "tenant_id", "created_at"),
    )
    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True)
    tenant_id: Mapped[UUID] = mapped_column(Uuid, ForeignKey("organisations.tenant_id"))
    uploader_person_id: Mapped[UUID] = mapped_column(Uuid)
    uploader_session_id: Mapped[UUID] = mapped_column(Uuid, ForeignKey("sessions.id"))
    manifest_sha256: Mapped[str] = mapped_column(String(64))
    policy_sha256: Mapped[str] = mapped_column(String(64))
    total_files: Mapped[int] = mapped_column(Integer)
    total_bytes: Mapped[int] = mapped_column(Integer)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class ConversationRecordingImportItem(Base):
    __tablename__ = "conversation_recording_import_items"
    __table_args__ = (
        ForeignKeyConstraint(
            ["batch_id", "tenant_id"],
            ["conversation_recording_imports.id", "conversation_recording_imports.tenant_id"],
        ),
        ForeignKeyConstraint(
            ["tenant_id", "person_id"], ["memberships.tenant_id", "memberships.person_id"]
        ),
        ForeignKeyConstraint(
            ["usage_id", "tenant_id", "source_sha256"],
            [
                "conversation_acquisition_usage.id",
                "conversation_acquisition_usage.tenant_id",
                "conversation_acquisition_usage.source_sha256",
            ],
        ),
        UniqueConstraint("batch_id", "path_sha256"),
        CheckConstraint("item_index BETWEEN 0 AND 255", name="index_bound"),
        CheckConstraint("source_bytes BETWEEN 1 AND 33554432", name="byte_bound"),
        CheckConstraint("length(source_sha256) = 64", name="source_hash"),
        CheckConstraint("length(path_sha256) = 64", name="path_hash"),
        CheckConstraint("length(folder_sha256) = 64", name="folder_hash"),
        CheckConstraint("(usage_id IS NULL) = (linked_at IS NULL)", name="usage_time"),
        CheckConstraint("usage_id IS NOT NULL OR NOT reused", name="reuse_bound"),
        CheckConstraint("person_id IS NOT NULL OR usage_id IS NULL", name="assigned_usage"),
        Index("ix_conversation_recording_import_items_tenant", "tenant_id", "usage_id"),
        Index(
            "uq_conversation_recording_import_items_origin",
            "usage_id",
            unique=True,
            postgresql_where=text("usage_id IS NOT NULL AND NOT reused"),
            sqlite_where=text("usage_id IS NOT NULL AND NOT reused"),
        ),
    )
    batch_id: Mapped[UUID] = mapped_column(Uuid, primary_key=True)
    item_index: Mapped[int] = mapped_column(Integer, primary_key=True)
    tenant_id: Mapped[UUID] = mapped_column(Uuid)
    person_id: Mapped[UUID | None] = mapped_column(Uuid)
    source_sha256: Mapped[str] = mapped_column(String(64))
    source_bytes: Mapped[int] = mapped_column(Integer)
    path_sha256: Mapped[str] = mapped_column(String(64))
    folder_sha256: Mapped[str] = mapped_column(String(64))
    submission_id: Mapped[UUID] = mapped_column(Uuid)
    usage_id: Mapped[UUID | None] = mapped_column(Uuid)
    reused: Mapped[bool] = mapped_column(Boolean, default=False, server_default=text("false"))
    linked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
