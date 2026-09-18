"""Global Cohorva public identity and academy-scoped participation.

Email and private profile fields deliberately do not enter this boundary.
The legacy academy profile remains immutable history after the global identity
contract supersedes it.
"""

from __future__ import annotations

from datetime import datetime
from uuid import UUID, uuid4

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


class CommunityDiscoveryPreference(Base):
    """Explicit academy-scoped discovery surface, private by default.

    A row is created only when the learner changes this preference.  The
    username remains the only account locator; display and avatar references
    are user-selected fields and are ignored while ``discoverable`` is false.
    """

    __tablename__ = "community_discovery_preferences"
    __table_args__ = (
        ForeignKeyConstraint(
            ["tenant_id", "person_id"],
            ["memberships.tenant_id", "memberships.person_id"],
            name="fk_community_discovery_preferences_membership",
        ),
        ForeignKeyConstraint(
            ["tenant_id", "avatar_asset_id"],
            ["media_assets.tenant_id", "media_assets.id"],
            name="fk_community_discovery_preferences_avatar_asset",
        ),
        CheckConstraint("revision >= 0", name="revision_nonnegative"),
        CheckConstraint(
            "public_display_name IS NULL OR length(trim(public_display_name)) > 0",
            name="public_display_name_nonblank",
        ),
    )

    tenant_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True)
    person_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True)
    discoverable: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default="false"
    )
    public_display_name: Mapped[str | None] = mapped_column(String(120), nullable=True)
    avatar_asset_id: Mapped[UUID | None] = mapped_column(Uuid(as_uuid=True), nullable=True)
    revision: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()
    )


class CommunityConnection(Base):
    """Current projection for one unordered learner pair in one academy."""

    __tablename__ = "community_connections"
    __table_args__ = (
        ForeignKeyConstraint(
            ["tenant_id", "person_a_id"],
            ["memberships.tenant_id", "memberships.person_id"],
            name="fk_community_connections_person_a_membership",
        ),
        ForeignKeyConstraint(
            ["tenant_id", "person_b_id"],
            ["memberships.tenant_id", "memberships.person_id"],
            name="fk_community_connections_person_b_membership",
        ),
        ForeignKeyConstraint(
            ["tenant_id", "requested_by_person_id"],
            ["memberships.tenant_id", "memberships.person_id"],
            name="fk_community_connections_requester_membership",
        ),
        UniqueConstraint(
            "tenant_id", "person_a_id", "person_b_id", name="uq_community_connections_pair"
        ),
        UniqueConstraint("tenant_id", "id", name="uq_community_connections_tenant_id"),
        CheckConstraint("person_a_id <> person_b_id", name="distinct_people"),
        CheckConstraint(
            "state IN ('pending','accepted','declined','removed')", name="state_supported"
        ),
        CheckConstraint("revision >= 1", name="revision_positive"),
    )

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid4)
    tenant_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    person_a_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    person_b_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    requested_by_person_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    state: Mapped[str] = mapped_column(String(16), nullable=False, default="pending")
    revision: Mapped[int] = mapped_column(Integer, nullable=False, default=1, server_default="1")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()
    )


class CommunityConnectionEvent(Base):
    """Append-only action history for a connection projection."""

    __tablename__ = "community_connection_events"
    __table_args__ = (
        ForeignKeyConstraint(
            ["tenant_id", "connection_id"],
            ["community_connections.tenant_id", "community_connections.id"],
            name="fk_community_connection_events_connection",
        ),
        ForeignKeyConstraint(
            ["tenant_id", "actor_person_id"],
            ["memberships.tenant_id", "memberships.person_id"],
            name="fk_community_connection_events_actor_membership",
        ),
        UniqueConstraint(
            "connection_id", "revision", name="uq_community_connection_events_revision"
        ),
        CheckConstraint(
            "action IN ('requested','accepted','declined','removed','blocked')",
            name="action_supported",
        ),
        CheckConstraint("revision >= 1", name="revision_positive"),
    )

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid4)
    connection_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    tenant_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    actor_person_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    action: Mapped[str] = mapped_column(String(16), nullable=False)
    revision: Mapped[int] = mapped_column(Integer, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class CommunityBlock(Base):
    """Persistent one-way block; it hides the blocked learner from the actor."""

    __tablename__ = "community_blocks"
    __table_args__ = (
        ForeignKeyConstraint(
            ["tenant_id", "blocker_person_id"],
            ["memberships.tenant_id", "memberships.person_id"],
            name="fk_community_blocks_blocker_membership",
        ),
        ForeignKeyConstraint(
            ["tenant_id", "blocked_person_id"],
            ["memberships.tenant_id", "memberships.person_id"],
            name="fk_community_blocks_blocked_membership",
        ),
        UniqueConstraint(
            "tenant_id", "blocker_person_id", "blocked_person_id", name="uq_community_blocks_pair"
        ),
        CheckConstraint("blocker_person_id <> blocked_person_id", name="distinct_people"),
    )

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid4)
    tenant_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    blocker_person_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    blocked_person_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class CommunityReport(Base):
    """Append-only user report; moderation workflow is deliberately deferred."""

    __tablename__ = "community_reports"
    __table_args__ = (
        ForeignKeyConstraint(
            ["tenant_id", "reporter_person_id"],
            ["memberships.tenant_id", "memberships.person_id"],
            name="fk_community_reports_reporter_membership",
        ),
        ForeignKeyConstraint(
            ["tenant_id", "reported_person_id"],
            ["memberships.tenant_id", "memberships.person_id"],
            name="fk_community_reports_reported_membership",
        ),
        CheckConstraint("reporter_person_id <> reported_person_id", name="distinct_people"),
        CheckConstraint(
            "reason IN ('spam','harassment','impersonation','other')", name="reason_supported"
        ),
    )

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid4)
    tenant_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    reporter_person_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    reported_person_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    reason: Mapped[str] = mapped_column(String(20), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
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
    "CommunityBlock",
    "CommunityConnection",
    "CommunityConnectionEvent",
    "CommunityDiscoveryPreference",
    "CommunityProfileMutationError",
    "CommunityReport",
]
