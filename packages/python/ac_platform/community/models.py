"""Global Cohorva public identity and academy-scoped participation.

Email and private profile fields deliberately do not enter this boundary.
The legacy academy profile remains immutable history after the global identity
contract supersedes it.
"""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    ForeignKeyConstraint,
    Integer,
    String,
    UniqueConstraint,
    Uuid,
    event,
    func,
    inspect,
)
from sqlalchemy.engine import Connection
from sqlalchemy.orm import Mapped, Mapper, mapped_column

from ac_platform.db.base import Base


class CohorvaPublicProfile(Base):
    """One immutable public username for a canonical person across academies."""

    __tablename__ = "community_public_profiles"
    __table_args__ = (
        UniqueConstraint("username", name="uq_community_public_profiles_username"),
        CheckConstraint("username = lower(username)", name="username_lowercase"),
        CheckConstraint("length(username) BETWEEN 3 AND 30", name="username_length"),
        CheckConstraint(
            "(claim_source = 'account_claim' AND claimed_session_id IS NOT NULL "
            "AND legacy_profile_count = 0) OR "
            "(claim_source = 'legacy_0027' AND claimed_session_id IS NULL "
            "AND legacy_profile_count >= 1)",
            name="claim_provenance",
        ),
    )

    person_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("persons.id", name="fk_community_public_profiles_person_id_persons"),
        primary_key=True,
    )
    username: Mapped[str] = mapped_column(String(30), nullable=False)
    claimed_session_id: Mapped[UUID | None] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("sessions.id", name="fk_community_public_profiles_claimed_session_id_sessions"),
        nullable=True,
    )
    claim_source: Mapped[str] = mapped_column(String(32), nullable=False)
    legacy_profile_count: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default="0"
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class AcademyLeaderboardPreference(Base):
    """Explicit leaderboard participation for one academy membership."""

    __tablename__ = "academy_leaderboard_preferences"
    __table_args__ = (
        ForeignKeyConstraint(
            ["tenant_id", "person_id"],
            ["memberships.tenant_id", "memberships.person_id"],
            name="fk_academy_leaderboard_preferences_tenant_id_memberships",
        ),
        ForeignKeyConstraint(
            ["person_id"],
            ["community_public_profiles.person_id"],
            name="fk_academy_board_preferences_person_id_community_profiles",
        ),
        CheckConstraint("revision >= 1", name="revision_positive"),
    )

    tenant_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True)
    person_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True)
    leaderboard_opted_in: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=False,
        server_default="false",
    )
    revision: Mapped[int] = mapped_column(nullable=False, default=1, server_default="1")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()
    )


class AcademyPublicProfile(Base):
    __tablename__ = "academy_public_profiles"
    __table_args__ = (
        ForeignKeyConstraint(
            ["tenant_id", "person_id"],
            ["memberships.tenant_id", "memberships.person_id"],
            name="fk_academy_public_profiles_tenant_id_memberships",
        ),
        UniqueConstraint(
            "tenant_id",
            "username",
            name="uq_academy_public_profiles_tenant_id",
        ),
        CheckConstraint("username = lower(username)", name="username_lowercase"),
        CheckConstraint("length(username) BETWEEN 3 AND 30", name="username_length"),
        CheckConstraint("revision >= 1", name="revision_positive"),
    )

    tenant_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True)
    person_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True)
    username: Mapped[str] = mapped_column(String(30), nullable=False)
    leaderboard_opted_in: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=False,
        server_default="false",
    )
    revision: Mapped[int] = mapped_column(nullable=False, default=1, server_default="1")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()
    )


class CommunityProfileMutationError(RuntimeError):
    """A stable username identity was changed or deleted instead of retained."""


@event.listens_for(CohorvaPublicProfile, "before_update")
def _guard_global_profile_update(
    _mapper: Mapper[CohorvaPublicProfile],
    _connection: Connection,
    _target: CohorvaPublicProfile,
) -> None:
    raise CommunityProfileMutationError("global public identity is immutable")


@event.listens_for(CohorvaPublicProfile, "before_delete")
def _guard_global_profile_delete(
    _mapper: Mapper[CohorvaPublicProfile],
    _connection: Connection,
    _target: CohorvaPublicProfile,
) -> None:
    raise CommunityProfileMutationError("global public identity must not be deleted")


@event.listens_for(AcademyLeaderboardPreference, "before_update")
def _guard_preference_identity(
    _mapper: Mapper[AcademyLeaderboardPreference],
    _connection: Connection,
    target: AcademyLeaderboardPreference,
) -> None:
    state = inspect(target)
    if any(
        state.attrs[field].history.has_changes()
        for field in ("tenant_id", "person_id", "created_at")
    ):
        raise CommunityProfileMutationError("academy leaderboard preference identity is immutable")


@event.listens_for(AcademyLeaderboardPreference, "before_delete")
def _guard_preference_delete(
    _mapper: Mapper[AcademyLeaderboardPreference],
    _connection: Connection,
    _target: AcademyLeaderboardPreference,
) -> None:
    raise CommunityProfileMutationError("academy leaderboard preference must not be deleted")


@event.listens_for(AcademyPublicProfile, "before_update")
def _guard_profile_identity(
    _mapper: Mapper[AcademyPublicProfile],
    _connection: Connection,
    target: AcademyPublicProfile,
) -> None:
    state = inspect(target)
    if any(
        state.attrs[field].history.has_changes()
        for field in ("tenant_id", "person_id", "username", "created_at")
    ):
        raise CommunityProfileMutationError("academy public identity is immutable")


@event.listens_for(AcademyPublicProfile, "before_delete")
def _guard_profile_delete(
    _mapper: Mapper[AcademyPublicProfile],
    _connection: Connection,
    _target: AcademyPublicProfile,
) -> None:
    raise CommunityProfileMutationError("academy public identity must not be deleted")


__all__ = [
    "AcademyLeaderboardPreference",
    "AcademyPublicProfile",
    "CohorvaPublicProfile",
    "CommunityProfileMutationError",
]
