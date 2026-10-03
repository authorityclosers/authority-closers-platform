"""Private speaker choices, superseded by appending and purged with their source."""

from datetime import datetime
from typing import Any
from uuid import UUID

from sqlalchemy import (
    JSON,
    CheckConstraint,
    DateTime,
    ForeignKeyConstraint,
    Index,
    Integer,
    String,
    UniqueConstraint,
    Uuid,
)
from sqlalchemy.orm import Mapped, mapped_column

from ac_platform.db.base import Base


class ConversationSpeakerMapRevision(Base):
    """One owner-authored decision tied to the transcript the owner saw."""

    __tablename__ = "conversation_speaker_map_revisions"
    __table_args__ = (
        ForeignKeyConstraint(
            ["tenant_id", "submission_id"],
            [
                "conversation_guest_submissions.tenant_id",
                "conversation_guest_submissions.submission_id",
            ],
        ),
        ForeignKeyConstraint(
            ["tenant_id", "actor_person_id"],
            ["memberships.tenant_id", "memberships.person_id"],
        ),
        UniqueConstraint("tenant_id", "submission_id", "revision", name="uq_speaker_map_revision"),
        CheckConstraint("revision >= 1 AND revision <= 50", name="revision_bounds"),
        CheckConstraint(
            "length(trim(transcript_revision)) > 0 AND length(transcript_revision) <= 256",
            name="transcript_bounds",
        ),
        Index("ix_speaker_map_latest", "tenant_id", "submission_id", "revision"),
        Index("ix_speaker_map_actor", "tenant_id", "actor_person_id"),
    )

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True)
    tenant_id: Mapped[UUID] = mapped_column(Uuid)
    submission_id: Mapped[UUID] = mapped_column(Uuid)
    revision: Mapped[int] = mapped_column(Integer)
    transcript_revision: Mapped[str] = mapped_column(String(256))
    speakers: Mapped[list[dict[str, Any]]] = mapped_column(JSON)
    actor_person_id: Mapped[UUID] = mapped_column(Uuid)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
