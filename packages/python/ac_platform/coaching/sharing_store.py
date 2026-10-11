"""Persist a rep's Coaching share and focus feedback (append-only, audited).

Owner decisions 10 Oct 2026: Coaching is private by default; one revocable tap
shares it with the workspace's owners/admins (and, later, assigned coaches).
Reads always use current membership and the latest share revision; nothing is
updated or deleted, a new revision supersedes. Payloads never carry Coaching
content or names into the audit chain.
"""

from datetime import UTC, datetime
from typing import Literal, cast
from uuid import UUID, uuid4

from pydantic import AwareDatetime, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ac_platform.audit.service import AuditRepository
from ac_platform.coaching.contracts import Model
from ac_platform.coaching.models import CoachingFeedback, CoachingShareRevision
from ac_platform.conversation_intelligence.application import (
    ConversationConflict,
    ConversationDenied,
)
from ac_platform.identity.models import Person
from ac_platform.kernel.authz import ActorContext
from ac_platform.organisations.activity import _mask_email
from ac_platform.tenancy.models import Membership, Organisation

LEADS = ("owner", "admin")


class Reach(Model):
    name: str
    why: Literal["admin"]


class SharingView(Model):
    # A Personal workspace has nobody to share with.
    available: bool
    shared: bool
    revision: int = Field(ge=0)
    reaches: tuple[Reach, ...]


class SharedRep(Model):
    person_id: UUID
    name: str
    shared_at: AwareDatetime


async def _member(
    database: AsyncSession, tenant_id: UUID, person_id: UUID, *, lock: bool = False
) -> Membership | None:
    statement = select(Membership).where(
        Membership.tenant_id == tenant_id,
        Membership.person_id == person_id,
        Membership.status == "active",
        Membership.ended_at.is_(None),
    )
    if lock:
        statement = statement.with_for_update()
    return cast(Membership | None, await database.scalar(statement))


async def _latest(
    database: AsyncSession, tenant_id: UUID, person_id: UUID
) -> CoachingShareRevision | None:
    return cast(
        CoachingShareRevision | None,
        await database.scalar(
            select(CoachingShareRevision)
            .where(
                CoachingShareRevision.tenant_id == tenant_id,
                CoachingShareRevision.rep_person_id == person_id,
            )
            .order_by(CoachingShareRevision.revision.desc())
            .limit(1)
        ),
    )


async def _organisation(database: AsyncSession, tenant_id: UUID) -> bool:
    return (
        await database.scalar(
            select(Organisation.tenant_id).where(Organisation.tenant_id == tenant_id)
        )
        is not None
    )


def _name(display_name: str | None, email: str | None) -> str:
    return (display_name or "").strip() or _mask_email(email)


async def read_sharing(database: AsyncSession, *, tenant_id: UUID, person_id: UUID) -> SharingView:
    if await _member(database, tenant_id, person_id) is None:
        raise ConversationDenied("Coaching is unavailable in this workspace.")
    latest = await _latest(database, tenant_id, person_id)
    available = await _organisation(database, tenant_id)
    reaches: tuple[Reach, ...] = ()
    if available:
        rows = (
            await database.execute(
                select(Person.display_name, Person.email)
                .join(Membership, Membership.person_id == Person.id)
                .where(
                    Membership.tenant_id == tenant_id,
                    Membership.status == "active",
                    Membership.ended_at.is_(None),
                    Membership.role.in_(LEADS),
                    Membership.person_id != person_id,
                )
                .order_by(Person.display_name, Person.id)
            )
        ).all()
        reaches = tuple(Reach(name=_name(name, email), why="admin") for name, email in rows)
    return SharingView(
        available=available,
        shared=bool(latest and latest.shared and available),
        revision=latest.revision if latest else 0,
        reaches=reaches,
    )


async def set_sharing(
    database: AsyncSession,
    *,
    actor: ActorContext,
    tenant_id: UUID,
    shared: bool,
    expected_revision: int,
    request_id: str | None = None,
    now: datetime | None = None,
) -> SharingView:
    """Append one share revision; a stale retry of the same choice is harmless."""
    if actor.tenant_id != tenant_id:
        raise ConversationDenied("Coaching is unavailable in this workspace.")
    # Serialize this rep's share changes on their own membership row.
    if await _member(database, tenant_id, actor.person_id, lock=True) is None:
        raise ConversationDenied("Coaching is unavailable in this workspace.")
    if not await _organisation(database, tenant_id):
        raise ConversationConflict("A Personal workspace has nobody to share Coaching with.")
    latest = await _latest(database, tenant_id, actor.person_id)
    current_revision = latest.revision if latest else 0
    current = bool(latest and latest.shared)
    if expected_revision != current_revision:
        if shared == current:
            return await read_sharing(database, tenant_id=tenant_id, person_id=actor.person_id)
        raise ConversationConflict("Your sharing changed. Reload it before changing it again.")
    if shared == current:
        return await read_sharing(database, tenant_id=tenant_id, person_id=actor.person_id)
    created_at = (now or datetime.now(UTC)).astimezone(UTC)
    database.add(
        CoachingShareRevision(
            id=uuid4(),
            tenant_id=tenant_id,
            rep_person_id=actor.person_id,
            revision=current_revision + 1,
            shared=shared,
            created_at=created_at,
        )
    )
    await database.flush()
    await AuditRepository(database).append(
        tenant_id=tenant_id,
        actor_person_id=actor.person_id,
        session_id=actor.session_id,
        action="coaching.share_changed",
        resource_type="coaching_share",
        resource_id=actor.person_id,
        payload={"shared": shared, "revision": current_revision + 1},
        request_id=request_id,
        now=created_at,
    )
    return await read_sharing(database, tenant_id=tenant_id, person_id=actor.person_id)


async def shared_reps(
    database: AsyncSession, *, actor: ActorContext, tenant_id: UUID
) -> tuple[SharedRep, ...]:
    """Reps whose latest revision shares, for a current owner/admin only."""
    viewer = await _member(database, tenant_id, actor.person_id)
    if (
        actor.tenant_id != tenant_id
        or viewer is None
        or viewer.role not in LEADS
        or not await _organisation(database, tenant_id)
    ):
        return ()
    revisions = (
        await database.scalars(
            select(CoachingShareRevision)
            .where(CoachingShareRevision.tenant_id == tenant_id)
            .order_by(CoachingShareRevision.rep_person_id, CoachingShareRevision.revision.desc())
        )
    ).all()
    latest: dict[UUID, CoachingShareRevision] = {}
    for row in revisions:
        latest.setdefault(row.rep_person_id, row)
    sharing = {person for person, row in latest.items() if row.shared and person != actor.person_id}
    if not sharing:
        return ()
    rows = (
        await database.execute(
            select(Person.id, Person.display_name, Person.email)
            .join(Membership, Membership.person_id == Person.id)
            .where(
                Membership.tenant_id == tenant_id,
                Membership.status == "active",
                Membership.ended_at.is_(None),
                Person.id.in_(sharing),
            )
        )
    ).all()
    return tuple(
        sorted(
            (
                SharedRep(
                    person_id=person,
                    name=_name(name, email),
                    shared_at=latest[person].created_at,
                )
                for person, name, email in rows
            ),
            key=lambda rep: rep.name.casefold(),
        )
    )


async def rep_has_shared(database: AsyncSession, *, tenant_id: UUID, rep_person_id: UUID) -> bool:
    latest = await _latest(database, tenant_id, rep_person_id)
    return bool(latest and latest.shared) and (
        await _member(database, tenant_id, rep_person_id) is not None
    )


async def record_feedback(
    database: AsyncSession,
    *,
    actor: ActorContext,
    tenant_id: UUID,
    command_id: UUID,
    agreement: Literal["agree", "not_completely"],
    focus_skill_id: str,
    mission_origin_submission_id: UUID,
    request_id: str | None = None,
    now: datetime | None = None,
) -> None:
    """Record agreement with the current focus; the same command is idempotent."""
    if actor.tenant_id != tenant_id or await _member(database, tenant_id, actor.person_id) is None:
        raise ConversationDenied("Coaching is unavailable in this workspace.")
    existing = await database.scalar(
        select(CoachingFeedback).where(
            CoachingFeedback.tenant_id == tenant_id,
            CoachingFeedback.person_id == actor.person_id,
            CoachingFeedback.command_id == command_id,
        )
    )
    if existing is not None:
        if (
            existing.agreement != agreement
            or existing.focus_skill_id != focus_skill_id
            or existing.mission_origin_submission_id != mission_origin_submission_id
        ):
            raise ConversationConflict("This response was already recorded differently.")
        return
    created_at = (now or datetime.now(UTC)).astimezone(UTC)
    database.add(
        CoachingFeedback(
            id=uuid4(),
            tenant_id=tenant_id,
            person_id=actor.person_id,
            command_id=command_id,
            focus_skill_id=focus_skill_id,
            mission_origin_submission_id=mission_origin_submission_id,
            agreement=agreement,
            created_at=created_at,
        )
    )
    await database.flush()
    await AuditRepository(database).append(
        tenant_id=tenant_id,
        actor_person_id=actor.person_id,
        session_id=actor.session_id,
        action="coaching.feedback_recorded",
        resource_type="coaching_feedback",
        resource_id=command_id,
        payload={"agreement": agreement},
        request_id=request_id,
        now=created_at,
    )
