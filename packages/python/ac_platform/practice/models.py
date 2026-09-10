"""Local pilot persistence. Earned journal/history is append-only, never course progress."""

from __future__ import annotations

from datetime import date, datetime
from typing import Any
from uuid import UUID

from sqlalchemy import (
    JSON,
    CheckConstraint,
    Date,
    DateTime,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    Integer,
    String,
    UniqueConstraint,
    Uuid,
    event,
)
from sqlalchemy.orm import Mapped, mapped_column

from ac_platform.db.base import Base


def member_fk() -> ForeignKeyConstraint:
    return ForeignKeyConstraint(
        ["tenant_id", "person_id"], ["memberships.tenant_id", "memberships.person_id"]
    )


def attempt_fk() -> ForeignKeyConstraint:
    return ForeignKeyConstraint(
        ["attempt_id", "tenant_id", "person_id"],
        ["practice_attempts.id", "practice_attempts.tenant_id", "practice_attempts.person_id"],
    )


class PracticeProfile(Base):
    __tablename__ = "practice_profiles"
    __table_args__ = (
        member_fk(),
        CheckConstraint("revision >= 1", name="positive_revision"),
        CheckConstraint(
            "(pending_timezone IS NULL AND pending_effective_at IS NULL) OR "
            "(pending_timezone IS NOT NULL AND pending_effective_at IS NOT NULL)",
            name="pending_shape",
        ),
    )
    tenant_id: Mapped[UUID] = mapped_column(Uuid, primary_key=True)
    person_id: Mapped[UUID] = mapped_column(Uuid, primary_key=True)
    timezone: Mapped[str] = mapped_column(String(64))
    revision: Mapped[int] = mapped_column(Integer)
    pending_timezone: Mapped[str | None] = mapped_column(String(64))
    pending_effective_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class PracticeSetVersion(Base):
    __tablename__ = "practice_set_versions"
    __table_args__ = (
        UniqueConstraint("tenant_id", "content_digest"),
        UniqueConstraint("id", "tenant_id"),
    )
    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True)
    tenant_id: Mapped[UUID] = mapped_column(Uuid, ForeignKey("tenants.id"))
    family_id: Mapped[str] = mapped_column(String(64))
    definition_version: Mapped[str] = mapped_column(String(64))
    content_digest: Mapped[str] = mapped_column(String(64))
    snapshot: Mapped[dict[str, Any]] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class PracticeAttempt(Base):
    __tablename__ = "practice_attempts"
    __table_args__ = (
        member_fk(),
        Index("ix_practice_attempts_recent", "tenant_id", "person_id", "updated_at", "id"),
        UniqueConstraint("id", "tenant_id", "person_id"),
        ForeignKeyConstraint(
            ["set_version_id", "tenant_id"],
            ["practice_set_versions.id", "practice_set_versions.tenant_id"],
        ),
        CheckConstraint("revision >= 0", name="revision_nonnegative"),
        CheckConstraint(
            "(state = 'in_progress' AND completed_at IS NULL) OR "
            "(state = 'completed' AND completed_at IS NOT NULL)",
            name="state_shape",
        ),
    )
    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True)
    tenant_id: Mapped[UUID] = mapped_column(Uuid)
    person_id: Mapped[UUID] = mapped_column(Uuid)
    set_version_id: Mapped[UUID] = mapped_column(Uuid)
    revision: Mapped[int] = mapped_column(Integer)
    state: Mapped[str] = mapped_column(String(16))
    issued_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class PracticeResponse(Base):
    __tablename__ = "practice_responses"
    __table_args__ = (
        attempt_fk(),
        UniqueConstraint("attempt_id", "sequence"),
        UniqueConstraint("id", "attempt_id", "tenant_id", "person_id"),
        CheckConstraint("sequence > 0", name="positive_sequence"),
    )
    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True)
    tenant_id: Mapped[UUID] = mapped_column(Uuid)
    person_id: Mapped[UUID] = mapped_column(Uuid)
    attempt_id: Mapped[UUID] = mapped_column(Uuid)
    item_id: Mapped[str] = mapped_column(String(64))
    sequence: Mapped[int] = mapped_column(Integer)
    selections: Mapped[list[int]] = mapped_column(JSON)
    feedback: Mapped[dict[str, Any]] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class PracticeFeedbackAck(Base):
    __tablename__ = "practice_feedback_acks"
    __table_args__ = (
        ForeignKeyConstraint(
            ["response_id", "attempt_id", "tenant_id", "person_id"],
            [
                "practice_responses.id",
                "practice_responses.attempt_id",
                "practice_responses.tenant_id",
                "practice_responses.person_id",
            ],
        ),
        UniqueConstraint("response_id"),
    )
    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True)
    tenant_id: Mapped[UUID] = mapped_column(Uuid)
    person_id: Mapped[UUID] = mapped_column(Uuid)
    attempt_id: Mapped[UUID] = mapped_column(Uuid)
    response_id: Mapped[UUID] = mapped_column(Uuid)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class PracticeParticipation(Base):
    __tablename__ = "practice_participations"
    __table_args__ = (
        attempt_fk(),
        Index(
            "ix_practice_participations_week", "tenant_id", "person_id", "week_start", "local_day"
        ),
        UniqueConstraint("attempt_id"),
        UniqueConstraint("id", "tenant_id", "person_id"),
    )
    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True)
    tenant_id: Mapped[UUID] = mapped_column(Uuid)
    person_id: Mapped[UUID] = mapped_column(Uuid)
    attempt_id: Mapped[UUID] = mapped_column(Uuid)
    local_day: Mapped[date] = mapped_column(Date)
    week_start: Mapped[date] = mapped_column(Date)
    timezone: Mapped[str] = mapped_column(String(64))
    policy_version: Mapped[str] = mapped_column(String(64))
    audit_event_id: Mapped[UUID] = mapped_column(Uuid, ForeignKey("audit_events.id"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class PracticeRewardClaim(Base):
    __tablename__ = "practice_reward_claims"
    __table_args__ = (
        ForeignKeyConstraint(
            ["participation_id", "tenant_id", "person_id"],
            [
                "practice_participations.id",
                "practice_participations.tenant_id",
                "practice_participations.person_id",
            ],
        ),
        UniqueConstraint("id", "tenant_id", "person_id"),
        UniqueConstraint(
            "tenant_id",
            "person_id",
            "kind",
            "dedup_key",
            name="uq_practice_reward_claims_eligibility",
        ),
        UniqueConstraint(
            "tenant_id",
            "person_id",
            "local_day",
            "daily_slot",
            name="uq_practice_reward_claims_daily_slot",
        ),
        Index("ix_practice_reward_claims_day", "tenant_id", "person_id", "local_day"),
        CheckConstraint(
            "(kind = 'daily_set' AND credits = 10 AND xp = 30 "
            "AND daily_slot IS NOT NULL AND daily_slot IN (1, 2)) OR "
            "(kind = 'weekly_rhythm' AND credits = 40 AND xp = 0 AND daily_slot IS NULL)",
            name="approved_award_shape",
        ),
    )
    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True)
    tenant_id: Mapped[UUID] = mapped_column(Uuid)
    person_id: Mapped[UUID] = mapped_column(Uuid)
    participation_id: Mapped[UUID] = mapped_column(Uuid)
    kind: Mapped[str] = mapped_column(String(24))
    dedup_key: Mapped[str] = mapped_column(String(100))
    credits: Mapped[int] = mapped_column(Integer)
    xp: Mapped[int] = mapped_column(Integer)
    daily_slot: Mapped[int | None] = mapped_column(Integer)
    local_day: Mapped[date] = mapped_column(Date)
    week_start: Mapped[date] = mapped_column(Date)
    policy_version: Mapped[str] = mapped_column(String(64))
    audit_event_id: Mapped[UUID] = mapped_column(Uuid, ForeignKey("audit_events.id"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class PracticeLedgerEntry(Base):
    __tablename__ = "practice_ledger_entries"
    __table_args__ = (
        Index("ix_practice_ledger_entries_balance", "tenant_id", "person_id", "account", "unit"),
        ForeignKeyConstraint(
            ["claim_id", "tenant_id", "person_id"],
            [
                "practice_reward_claims.id",
                "practice_reward_claims.tenant_id",
                "practice_reward_claims.person_id",
            ],
        ),
        UniqueConstraint("claim_id", "unit", "account"),
        CheckConstraint("unit IN ('credits', 'xp')", name="known_unit"),
        CheckConstraint(
            "(account = 'available' AND amount > 0) OR (account = 'issuance' AND amount < 0)",
            name="earned_only_accounts",
        ),
    )
    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True)
    tenant_id: Mapped[UUID] = mapped_column(Uuid)
    person_id: Mapped[UUID] = mapped_column(Uuid)
    claim_id: Mapped[UUID] = mapped_column(Uuid)
    unit: Mapped[str] = mapped_column(String(16))
    account: Mapped[str] = mapped_column(String(16))
    amount: Mapped[int] = mapped_column(Integer)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class PracticeCommand(Base):
    __tablename__ = "practice_commands"
    __table_args__ = (member_fk(), UniqueConstraint("tenant_id", "person_id", "key"))
    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True)
    tenant_id: Mapped[UUID] = mapped_column(Uuid)
    person_id: Mapped[UUID] = mapped_column(Uuid)
    key: Mapped[str] = mapped_column(String(128))
    operation: Mapped[str] = mapped_column(String(32))
    intent_digest: Mapped[str] = mapped_column(String(64))
    result_id: Mapped[UUID | None] = mapped_column(Uuid)
    audit_event_id: Mapped[UUID] = mapped_column(Uuid, ForeignKey("audit_events.id"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


IMMUTABLE_MODELS = (
    PracticeSetVersion,
    PracticeResponse,
    PracticeFeedbackAck,
    PracticeParticipation,
    PracticeRewardClaim,
    PracticeLedgerEntry,
    PracticeCommand,
)


def _immutable(*args: Any) -> None:
    raise RuntimeError("Practice history is immutable; append a new command.")


for _model in IMMUTABLE_MODELS:
    event.listen(_model, "before_update", _immutable)
    event.listen(_model, "before_delete", _immutable)
