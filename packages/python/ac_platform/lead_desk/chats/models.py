"""Read marks for the Chats screen (0113): how far each person has read each chat."""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from sqlalchemy import CheckConstraint, DateTime, ForeignKeyConstraint, Index, String, Uuid
from sqlalchemy.orm import Mapped, mapped_column

from ac_platform.db.base import Base


class LeadChatRead(Base):
    """One person read one conversation up to a message time. Rows are only added,
    never changed: the newest ``read_to`` per person and conversation is the mark.
    A conversation is a lead on one channel and one account (the WhatsApp number or
    the Facebook Page). Ids and times only, never a message's words or Meta's ids."""

    __tablename__ = "lead_desk_chat_reads"
    __table_args__ = (
        ForeignKeyConstraint(["tenant_id"], ["tenants.id"], name="fk_lead_desk_chat_read_tenant"),
        CheckConstraint("channel IN ('whatsapp', 'messenger', 'instagram')", name="channel"),
        CheckConstraint("read_to <= created_at", name="read_time"),
        Index(
            "ix_lead_desk_chat_read_mark",
            "tenant_id",
            "person_id",
            "channel",
            "account_id",
            "lead_id",
            "read_to",
        ),
    )

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True)
    tenant_id: Mapped[UUID] = mapped_column(Uuid)
    person_id: Mapped[UUID] = mapped_column(Uuid)
    channel: Mapped[str] = mapped_column(String(16))
    account_id: Mapped[UUID] = mapped_column(Uuid)
    lead_id: Mapped[UUID] = mapped_column(Uuid)
    read_to: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
