"""Persistence for academy-scoped public learner identity.

Email and private profile fields deliberately do not enter this boundary.
"""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKeyConstraint,
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


__all__ = ["AcademyPublicProfile", "CommunityProfileMutationError"]
