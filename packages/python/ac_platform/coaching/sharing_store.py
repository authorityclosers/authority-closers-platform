"""Persist a rep's Coaching share and focus feedback (append-only, audited).

Owner decisions 10 Oct 2026: Coaching is private by default; one revocable tap
shares it with the workspace's owners/admins (and, later, assigned coaches).
Reads always use current membership and the latest share revision; nothing is
updated or deleted, a new revision supersedes. Learner context is the one
free-text note: never edited, erased with the account. Payloads never carry
Coaching content or names into the audit chain.
"""

import hashlib
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime
from typing import Literal, cast
from uuid import UUID, uuid4

from pydantic import AwareDatetime, Field
from sqlalchemy import delete, func, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from ac_platform.audit.service import AuditRepository
from ac_platform.coaching.contracts import Model
from ac_platform.coaching.models import (
    CoachingFeedback,
    CoachingLearnerContext,
    CoachingShareRevision,
)
from ac_platform.conversation_intelligence.application import (
    ConversationConflict,
    ConversationDenied,
)
from ac_platform.identity.models import Person
from ac_platform.kernel.authz import ActorContext
from ac_platform.organisations.activity import _mask_email
from ac_platform.tenancy.models import Membership, Organisation
from ac_platform.tenancy.roles import roles_with

LEADS = roles_with("team.view")
FOCUS_CHANGED = "Your focus changed. Reload Coaching and try again."

# The learner's (focus skill, mission origin) as My coaching shows them now,
# derived on the server; None without a current pair.
CurrentFocus = Callable[[], Awaitable[tuple[str, UUID] | None]]


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


def _aware(value: datetime) -> datetime:
    return value if value.tzinfo else value.replace(tzinfo=UTC)


def _effective(latest: CoachingShareRevision | None, member: Membership | None) -> bool:
    """A share counts only if made after the membership last changed.

    Removal, re-adding and role changes all update the membership row, so
    each returns coaching to private until the rep shares again (consent is
    never carried into a new membership period).
    """
    return bool(
        latest is not None
        and latest.shared
        and member is not None
        and _aware(latest.created_at) >= _aware(member.updated_at)
    )


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
    # Views carry at most 120 characters; display names may hold 200.
    return ((display_name or "").strip() or _mask_email(email))[:120]


async def _share_lock(database: AsyncSession, tenant_id: UUID, person_id: UUID) -> None:
    """Serialize one rep's share changes without upgrading the membership row's
    shared lock (two tabs upgrading it would deadlock)."""
    key = int.from_bytes(
        hashlib.sha256(b"coaching-share:" + tenant_id.bytes + person_id.bytes).digest()[:8],
        "big",
        signed=True,
    )
    await database.execute(select(func.pg_advisory_xact_lock(key)))


async def read_sharing(database: AsyncSession, *, tenant_id: UUID, person_id: UUID) -> SharingView:
    member = await _member(database, tenant_id, person_id)
    if member is None:
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
        shared=_effective(latest, member) and available,
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
    await _share_lock(database, tenant_id, actor.person_id)
    member = await _member(database, tenant_id, actor.person_id)
    if member is None:
        raise ConversationDenied("Coaching is unavailable in this workspace.")
    if not await _organisation(database, tenant_id):
        raise ConversationConflict("A Personal workspace has nobody to share Coaching with.")
    latest = await _latest(database, tenant_id, actor.person_id)
    current_revision = latest.revision if latest else 0
    current = _effective(latest, member)
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
    # The newest revision per rep only (PostgreSQL DISTINCT ON).
    revisions = (
        await database.scalars(
            select(CoachingShareRevision)
            .where(CoachingShareRevision.tenant_id == tenant_id)
            .order_by(CoachingShareRevision.rep_person_id, CoachingShareRevision.revision.desc())
            .distinct(CoachingShareRevision.rep_person_id)
        )
    ).all()
    latest = {row.rep_person_id: row for row in revisions}
    sharing = {person for person, row in latest.items() if row.shared and person != actor.person_id}
    if not sharing:
        return ()
    rows = (
        await database.execute(
            select(Person.id, Person.display_name, Person.email, Membership)
            .join(Membership, Membership.person_id == Person.id)
            .where(
                Membership.tenant_id == tenant_id,
                Membership.status == "active",
                Membership.ended_at.is_(None),
                Person.id.in_(sharing),
            )
        )
    ).all()
    rows = [row for row in rows if _effective(latest[row[0]], row[3])]
    return tuple(
        sorted(
            (
                SharedRep(
                    person_id=person,
                    name=_name(name, email),
                    shared_at=latest[person].created_at,
                )
                for person, name, email, _member_row in rows
            ),
            key=lambda rep: rep.name.casefold(),
        )
    )


async def rep_has_shared(database: AsyncSession, *, tenant_id: UUID, rep_person_id: UUID) -> bool:
    latest = await _latest(database, tenant_id, rep_person_id)
    return _effective(latest, await _member(database, tenant_id, rep_person_id))


async def member_name(database: AsyncSession, *, person_id: UUID) -> str | None:
    """One person's display name for a shared view's header."""
    row = (
        await database.execute(
            select(Person.display_name, Person.email).where(Person.id == person_id)
        )
    ).first()
    return _name(row[0], row[1]) if row else None


async def record_feedback(
    database: AsyncSession,
    *,
    actor: ActorContext,
    tenant_id: UUID,
    command_id: UUID,
    agreement: Literal["agree", "not_completely"],
    focus_skill_id: str,
    mission_origin_submission_id: UUID,
    current_focus: CurrentFocus,
    request_id: str | None = None,
    now: datetime | None = None,
) -> None:
    """Record agreement with the current focus; the same command is idempotent.

    A retry of a recorded command is answered from that record, even after the
    focus moved on. A new command must name the server's current focus skill
    and mission origin, checked before anything is appended.
    """
    if actor.tenant_id != tenant_id or await _member(database, tenant_id, actor.person_id) is None:
        raise ConversationDenied("Coaching is unavailable in this workspace.")

    async def recorded() -> CoachingFeedback | None:
        return cast(
            CoachingFeedback | None,
            await database.scalar(
                select(CoachingFeedback).where(
                    CoachingFeedback.tenant_id == tenant_id,
                    CoachingFeedback.person_id == actor.person_id,
                    CoachingFeedback.command_id == command_id,
                )
            ),
        )

    existing = await recorded()
    if existing is None:
        if await current_focus() != (focus_skill_id, mission_origin_submission_id):
            raise ConversationConflict(FOCUS_CHANGED)
        created_at = (now or datetime.now(UTC)).astimezone(UTC)
        # One statement: a concurrent repeat of the same command waits, then sees it.
        inserted = await database.scalar(
            insert(CoachingFeedback)
            .values(
                id=uuid4(),
                tenant_id=tenant_id,
                person_id=actor.person_id,
                command_id=command_id,
                focus_skill_id=focus_skill_id,
                mission_origin_submission_id=mission_origin_submission_id,
                agreement=agreement,
                created_at=created_at,
            )
            .on_conflict_do_nothing(constraint="uq_coaching_feedback_command")
            .returning(CoachingFeedback.id)
        )
        if inserted is not None:
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
            return
        existing = await recorded()
    if existing is None or (
        existing.agreement != agreement
        or existing.focus_skill_id != focus_skill_id
        or existing.mission_origin_submission_id != mission_origin_submission_id
    ):
        raise ConversationConflict("This response was already recorded differently.")


async def record_context(
    database: AsyncSession,
    *,
    actor: ActorContext,
    tenant_id: UUID,
    command_id: UUID,
    focus_skill_id: str,
    mission_origin_submission_id: UUID,
    context: str,
    current_focus: CurrentFocus,
    request_id: str | None = None,
    now: datetime | None = None,
) -> None:
    """Keep the learner's own context on their focus; the same command is idempotent.

    Retries and new notes follow `record_feedback`'s rule. The audit event
    carries no text: the note is erased with the account.
    """
    if actor.tenant_id != tenant_id or await _member(database, tenant_id, actor.person_id) is None:
        raise ConversationDenied("Coaching is unavailable in this workspace.")

    async def recorded() -> CoachingLearnerContext | None:
        return cast(
            CoachingLearnerContext | None,
            await database.scalar(
                select(CoachingLearnerContext).where(
                    CoachingLearnerContext.tenant_id == tenant_id,
                    CoachingLearnerContext.person_id == actor.person_id,
                    CoachingLearnerContext.command_id == command_id,
                )
            ),
        )

    existing = await recorded()
    if existing is None:
        if await current_focus() != (focus_skill_id, mission_origin_submission_id):
            raise ConversationConflict(FOCUS_CHANGED)
        created_at = (now or datetime.now(UTC)).astimezone(UTC)
        inserted = await database.scalar(
            insert(CoachingLearnerContext)
            .values(
                id=uuid4(),
                tenant_id=tenant_id,
                person_id=actor.person_id,
                command_id=command_id,
                focus_skill_id=focus_skill_id,
                mission_origin_submission_id=mission_origin_submission_id,
                context=context,
                created_at=created_at,
            )
            .on_conflict_do_nothing(constraint="uq_coaching_learner_context_command")
            .returning(CoachingLearnerContext.id)
        )
        if inserted is not None:
            await AuditRepository(database).append(
                tenant_id=tenant_id,
                actor_person_id=actor.person_id,
                session_id=actor.session_id,
                action="coaching.context_added",
                resource_type="coaching_learner_context",
                resource_id=command_id,
                payload={"length": len(context)},
                request_id=request_id,
                now=created_at,
            )
            return
        existing = await recorded()
    if existing is None or (
        existing.context != context
        or existing.focus_skill_id != focus_skill_id
        or existing.mission_origin_submission_id != mission_origin_submission_id
    ):
        raise ConversationConflict("This note was already saved differently.")


async def latest_context(
    database: AsyncSession,
    *,
    tenant_id: UUID,
    person_id: UUID,
    focus_skill_id: str,
    mission_origin_submission_id: UUID,
) -> str | None:
    """The newest note this person added about this focus and mission, if any.

    A note on an earlier mission with the same skill is about another call.
    """
    note: str | None = await database.scalar(
        select(CoachingLearnerContext.context)
        .where(
            CoachingLearnerContext.tenant_id == tenant_id,
            CoachingLearnerContext.person_id == person_id,
            CoachingLearnerContext.focus_skill_id == focus_skill_id,
            CoachingLearnerContext.mission_origin_submission_id == mission_origin_submission_id,
        )
        .order_by(CoachingLearnerContext.created_at.desc())
        .limit(1)
    )
    return note


async def erase_coaching_context_for_person(database: AsyncSession, *, person_id: UUID) -> int:
    """Purge a person's free-text Coaching notes in the account-deletion transaction."""
    result = await database.execute(
        delete(CoachingLearnerContext).where(CoachingLearnerContext.person_id == person_id)
    )
    return int(getattr(result, "rowcount", 0) or 0)
