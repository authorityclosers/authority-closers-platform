"""Tags on leads (owner's picks, 17 Nov 2026: M2-A "Add tag", the phone dock's Tag, import I4
"Source and tags"; migration 0165; docs/product/lead-desk/lead-management-api.md §5).

A tag is the workspace's own short label (a name and one of the app's colours), such as
"Nov video ad" or "Hot". Anyone in the workspace makes one and puts it on a lead they may
change; owners, admins and managers rename, recolour, reorder and delete them. A lead's tags
show on its row and page, a list can be narrowed to one tag (``GET /leads?tag=``), saved views
keep it, a bulk change adds or takes one off many leads with Undo (bulk_jobs.py), and a merge
carries the other lead's tags to the kept one (merging.py). Imports do not tag leads yet
(v1.94): Undo import must not mistake a later import's edit for the first one's own.

A lead carries up to 10 tags: one lead asked for more is refused (422), and a bulk change
counts such leads as "couldn't change". Making, renaming, recolouring, moving and deleting a
tag each write one audit event, with ids only (never the tag's name).

Every change to a lead's tags is one ``edited`` line in its history ("Tag added: Hot"), with
the tag's id and name then, so a later rename or delete never rewrites what it said. A deleted
tag is removed with its links: it is a label, not history.
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from typing import TYPE_CHECKING, Any, Final, Literal
from uuid import UUID, uuid4, uuid5

from sqlalchemy import delete, func, select
from sqlalchemy.exc import IntegrityError

from ac_platform.audit.service import AuditRepository
from ac_platform.lead_desk.contracts import (
    LeadTagsChange,
    LeadTagsChanged,
    TagChip,
    TagCommand,
    TagDelete,
    TagEdit,
    Tags,
    TagView,
)
from ac_platform.lead_desk.errors import DeskError
from ac_platform.lead_desk.history import on_desk
from ac_platform.lead_desk.models import Lead, LeadEvent, LeadTag, LeadTagLink

if TYPE_CHECKING:
    from ac_platform.lead_desk.store import LeadDesk

MAX_TAGS: Final = 100  # per workspace
MAX_ON_LEAD: Final = 10
COLOURS: Final = ("mint", "sky", "amber", "rose", "violet", "slate", "lime", "orange")
AUDIT_RESOURCE: Final = "lead_desk.tag"
# What a lead's history keeps (``LeadEventView.changed`` holds "tags").
CHANGED: Final = "tags"
# One lead asked for an 11th tag (422), and a bulk change's "couldn't change" reason.
FULL: Final = f"Up to {MAX_ON_LEAD} tags on a lead; take one off first."
FULL_REASON: Final = f"{MAX_ON_LEAD} tags already"


async def _audit(
    desk: LeadDesk, action: str, tag_id: UUID, payload: dict[str, Any], reason: str
) -> None:
    await AuditRepository(desk.db).append(
        tenant_id=desk.tenant_id,
        actor_person_id=desk.viewer.person_id,
        session_id=desk.viewer.session_id,
        action=action,
        resource_type=AUDIT_RESOURCE,
        resource_id=str(tag_id),
        payload=payload,
        reason=reason,
        now=desk.now,
    )


def clause(desk: LeadDesk, tag_id: UUID) -> Any:
    """SQL for the leads carrying this tag (``GET /leads?tag=``)."""
    return Lead.id.in_(
        select(LeadTagLink.lead_id).where(
            LeadTagLink.tenant_id == desk.tenant_id, LeadTagLink.tag_id == tag_id
        )
    )


def _chip(tag: LeadTag) -> TagChip:
    return TagChip(tag_id=tag.id, name=tag.name, colour=tag.colour)


def _clean(name: str) -> str:
    words = " ".join(name.split())
    if not words:
        raise DeskError(422, "Give the tag a name.")
    return words[:32]


async def chips(desk: LeadDesk, lead_ids: Iterable[UUID]) -> dict[UUID, tuple[TagChip, ...]]:
    """Each lead's tags, in the workspace's order (one query for a page of rows)."""
    ids = list(dict.fromkeys(lead_ids))
    if not ids:
        return {}
    rows = (
        await desk.db.execute(
            select(LeadTagLink.lead_id, LeadTag)
            .join(
                LeadTag,
                (LeadTag.id == LeadTagLink.tag_id) & (LeadTag.tenant_id == LeadTagLink.tenant_id),
            )
            .where(LeadTagLink.tenant_id == desk.tenant_id, LeadTagLink.lead_id.in_(ids))
            .order_by(LeadTag.position, LeadTag.created_at, LeadTag.id)
        )
    ).all()
    found: dict[UUID, list[TagChip]] = {}
    for lead_id, tag in rows:
        found.setdefault(lead_id, []).append(_chip(tag))
    return {lead_id: tuple(items) for lead_id, items in found.items()}


async def _tag(desk: LeadDesk, tag_id: UUID, *, lock: bool = False) -> LeadTag:
    query = select(LeadTag).where(LeadTag.id == tag_id, LeadTag.tenant_id == desk.tenant_id)
    tag = await desk.db.scalar(query.with_for_update() if lock else query)
    if tag is None:
        raise DeskError(404, "This tag isn't here.")
    return tag


async def present(desk: LeadDesk, tag_ids: Iterable[UUID]) -> dict[UUID, LeadTag]:
    """The workspace's tags among these ids that still exist."""
    wanted = list(dict.fromkeys(tag_ids))
    if not wanted:
        return {}
    return {
        tag.id: tag
        for tag in await desk.db.scalars(
            select(LeadTag).where(LeadTag.tenant_id == desk.tenant_id, LeadTag.id.in_(wanted))
        )
    }


async def known(desk: LeadDesk, tag_ids: Sequence[UUID]) -> list[LeadTag]:
    """The workspace's tags among these ids, in the order asked; 422 when one isn't here."""
    wanted = list(dict.fromkeys(tag_ids))
    found = await present(desk, wanted)
    if len(found) != len(wanted):
        raise DeskError(422, "Choose tags from this workspace.")
    return [found[tag_id] for tag_id in wanted]


def _view(desk: LeadDesk, tag: LeadTag, leads: int = 0) -> TagView:
    return TagView(
        tag_id=tag.id,
        name=tag.name,
        colour=tag.colour,
        position=tag.position,
        revision=tag.revision,
        leads=leads,
        can_change=desk.viewer.can_manage,
    )


async def listed(desk: LeadDesk) -> Tags:
    """The workspace's tags in order, each with the number of leads on the desk carrying it
    that this person may see (archived and binned leads aside)."""
    tags = (
        await desk.db.scalars(
            select(LeadTag)
            .where(LeadTag.tenant_id == desk.tenant_id)
            .order_by(LeadTag.position, LeadTag.created_at, LeadTag.id)
        )
    ).all()
    counts = await _counts(desk)
    return Tags(tags=tuple(_view(desk, tag, counts.get(tag.id, 0)) for tag in tags))


async def _counts(desk: LeadDesk, tag_id: UUID | None = None) -> dict[UUID, int]:
    """How many leads on the desk carry each tag (or this one), among those this person
    may see; archived and binned leads aside."""
    query = (
        select(LeadTagLink.tag_id, func.count())
        .join(
            Lead,
            (Lead.id == LeadTagLink.lead_id) & (Lead.tenant_id == LeadTagLink.tenant_id),
        )
        .where(LeadTagLink.tenant_id == desk.tenant_id, desk._seen(), on_desk())
        .group_by(LeadTagLink.tag_id)
    )
    if tag_id is not None:
        query = query.where(LeadTagLink.tag_id == tag_id)
    return {found: int(count) for found, count in (await desk.db.execute(query)).all()}


async def _counted(desk: LeadDesk, tag: LeadTag) -> TagView:
    """One tag as the list shows it, its lead count included (a rename moves no lead)."""
    return _view(desk, tag, (await _counts(desk, tag.id)).get(tag.id, 0))


async def _same_name(
    desk: LeadDesk, name: str, *, other_than: UUID | None = None
) -> LeadTag | None:
    query = select(LeadTag).where(
        LeadTag.tenant_id == desk.tenant_id, func.lower(LeadTag.name) == name.lower()
    )
    if other_than is not None:
        query = query.where(LeadTag.id != other_than)
    tag: LeadTag | None = await desk.db.scalar(query)
    return tag


async def _by_command(desk: LeadDesk, command_id: UUID) -> LeadTag | None:
    tag: LeadTag | None = await desk.db.scalar(
        select(LeadTag).where(LeadTag.tenant_id == desk.tenant_id, LeadTag.command_id == command_id)
    )
    return tag


async def _make(desk: LeadDesk, command_id: UUID, name: str, colour: str | None) -> LeadTag:
    done = await _by_command(desk, command_id)
    if done is not None:
        return done
    name = _clean(name)
    same = await _same_name(desk, name)
    if same is not None:
        return same
    taken = (
        await desk.db.execute(
            select(func.count(), func.coalesce(func.max(LeadTag.position), -1)).where(
                LeadTag.tenant_id == desk.tenant_id
            )
        )
    ).one()
    if int(taken[0]) >= MAX_TAGS:
        raise DeskError(422, f"Up to {MAX_TAGS} tags; delete one first.")
    tag = LeadTag(
        id=uuid4(),
        tenant_id=desk.tenant_id,
        name=name,
        # The next colour round the app's tints, unless one was picked.
        colour=colour or COLOURS[int(taken[0]) % len(COLOURS)],
        position=int(taken[1]) + 1,
        revision=1,
        command_id=command_id,
        created_by_person_id=desk.viewer.person_id,
        created_at=desk.now,
        updated_at=desk.now,
    )
    try:
        async with desk.db.begin_nested():
            desk.db.add(tag)
            await desk.db.flush()
    except IntegrityError:
        # Someone made the same name (or sent this command) at the same moment: that tag.
        won = await _by_command(desk, command_id) or await _same_name(desk, name)
        if won is None:
            raise
        return won
    await _audit(
        desk,
        "lead_desk.tag.created",
        tag.id,
        {"colour": tag.colour, "position": tag.position},
        "Tag made in Leads",
    )
    return tag


async def create(desk: LeadDesk, command: TagCommand) -> TagView:
    # A name already here answers with that tag, its leads counted.
    return await _counted(desk, await _make(desk, command.command_id, command.name, command.colour))


def _may_change(desk: LeadDesk) -> None:
    if not desk.viewer.can_manage:
        raise DeskError(403, "Only owners, admins and managers change tags.")


async def edit(desk: LeadDesk, tag_id: UUID, command: TagEdit) -> TagView:
    _may_change(desk)
    tag = await _tag(desk, tag_id, lock=True)
    if tag.revision != command.expected_revision:
        raise DeskError(409, "This tag changed since you opened it. Open it again.")
    changed: list[str] = []
    if command.name is not None:
        name = _clean(command.name)
        if await _same_name(desk, name, other_than=tag.id) is not None:
            raise DeskError(409, "A tag with this name is already here.")
        if name != tag.name:
            tag.name = name
            changed.append("name")
    if command.colour is not None and command.colour != tag.colour:
        tag.colour = command.colour
        changed.append("colour")
    if command.position is not None and command.position != tag.position:
        tag.position = command.position
        changed.append("position")
    if not changed:
        return await _counted(desk, tag)
    tag.revision += 1
    tag.updated_at = desk.now
    try:
        async with desk.db.begin_nested():
            await desk.db.flush()
    except IntegrityError:
        raise DeskError(409, "A tag with this name is already here.") from None
    # Ids and what changed only: a rename's words stay out of the audit trail.
    await _audit(
        desk,
        "lead_desk.tag.edited",
        tag.id,
        {"changed": changed, "revision": tag.revision},
        "Tag changed in Leads",
    )
    return await _counted(desk, tag)


async def remove(desk: LeadDesk, tag_id: UUID, command: TagDelete) -> Tags:
    """Delete a tag and take it off every lead. Each lead's history keeps its earlier lines;
    one audit event says which tag (its id) and how many leads, never its name."""
    _may_change(desk)
    tag = await _tag(desk, tag_id, lock=True)
    if tag.revision != command.expected_revision:
        raise DeskError(409, "This tag changed since you opened it. Open it again.")
    taken = await desk.db.execute(
        delete(LeadTagLink)
        .where(LeadTagLink.tenant_id == desk.tenant_id, LeadTagLink.tag_id == tag.id)
        .execution_options(synchronize_session=False)
    )
    await _audit(
        desk,
        "lead_desk.tag.deleted",
        tag.id,
        {"leads": int(getattr(taken, "rowcount", 0) or 0)},
        "Tag deleted in Leads",
    )
    await desk.db.delete(tag)
    await desk.db.flush()
    return await listed(desk)


async def _on(desk: LeadDesk, lead_ids: Sequence[UUID]) -> set[tuple[UUID, UUID]]:
    if not lead_ids:
        return set()
    return {
        (lead_id, tag_id)
        for lead_id, tag_id in (
            await desk.db.execute(
                select(LeadTagLink.lead_id, LeadTagLink.tag_id).where(
                    LeadTagLink.tenant_id == desk.tenant_id,
                    LeadTagLink.lead_id.in_(list(lead_ids)),
                )
            )
        ).all()
    }


def _words(added: Sequence[LeadTag], removed: Sequence[LeadTag]) -> str:
    parts = []
    if added:
        parts.append(
            f"Tag{'s' if len(added) > 1 else ''} added: {', '.join(tag.name for tag in added)}"
        )
    if removed:
        parts.append(
            f"Tag{'s' if len(removed) > 1 else ''} removed: "
            f"{', '.join(tag.name for tag in removed)}"
        )
    return " · ".join(parts)


async def apply(
    desk: LeadDesk,
    leads: Sequence[Lead],
    *,
    add: Sequence[LeadTag] = (),
    remove: Sequence[LeadTag] = (),
    command_id: UUID,
    actor: UUID | None,
    extra: dict[str, Any] | None = None,
    over: Literal["refuse", "skip", "fit"] = "refuse",
    full: set[UUID] | None = None,
) -> dict[UUID, tuple[list[LeadTag], list[LeadTag]]]:
    """Add and take off tags on these leads; each lead that changes gets one history line,
    with command id ``uuid5(command_id, lead id)``. Returns what changed per lead. A tag
    already on (or already off) a lead changes nothing there. The lead's own revision stays:
    tags are beside the lead, so an open edit of it is never refused for a tag.

    A lead that would pass ``MAX_ON_LEAD``: ``refuse`` stops the whole change (422) before
    anything is written; ``skip`` leaves that lead as it is and adds its id to ``full``;
    ``fit`` adds what fits (a merge, in the workspace's order)."""
    have = await _on(desk, [lead.id for lead in leads])
    changed: dict[UUID, tuple[list[LeadTag], list[LeadTag]]] = {}
    count: dict[UUID, int] = {}
    for lead_id, _ in have:
        count[lead_id] = count.get(lead_id, 0) + 1
    plans: list[tuple[Lead, list[LeadTag], list[LeadTag]]] = []
    for lead in leads:
        added = [tag for tag in add if (lead.id, tag.id) not in have]
        removed = [tag for tag in remove if (lead.id, tag.id) in have]
        room = MAX_ON_LEAD - count.get(lead.id, 0) + len(removed)
        if len(added) > room:
            if over == "refuse":
                raise DeskError(422, FULL)
            if over == "skip":
                if full is not None:
                    full.add(lead.id)
                continue
            added = added[: max(0, room)]
        if added or removed:
            plans.append((lead, added, removed))
    for lead, added, removed in plans:
        for tag in added:
            desk.db.add(
                LeadTagLink(
                    tenant_id=desk.tenant_id,
                    lead_id=lead.id,
                    tag_id=tag.id,
                    added_by_person_id=actor,
                    added_at=desk.now,
                )
            )
        if removed:
            await desk.db.execute(
                delete(LeadTagLink)
                .where(
                    LeadTagLink.tenant_id == desk.tenant_id,
                    LeadTagLink.lead_id == lead.id,
                    LeadTagLink.tag_id.in_([tag.id for tag in removed]),
                )
                .execution_options(synchronize_session=False)
            )
        desk._event(
            lead,
            "edited",
            {
                "changed": [CHANGED],
                "tags_added": [{"id": str(tag.id), "name": tag.name} for tag in added],
                "tags_removed": [{"id": str(tag.id), "name": tag.name} for tag in removed],
                "reason_text": _words(added, removed),
                **(extra or {}),
            },
            actor=actor,
            command_id=uuid5(command_id, str(lead.id)),
        )
        changed[lead.id] = (added, removed)
    await desk.db.flush()
    return changed


async def on_lead(desk: LeadDesk, lead_id: UUID, command: LeadTagsChange) -> LeadTagsChanged:
    """Add or take off tags on one lead, as anyone who may change it."""
    lead = await desk._lead(lead_id, lock=True)
    done = await desk.db.scalar(
        select(LeadEvent.id).where(
            LeadEvent.tenant_id == desk.tenant_id,
            LeadEvent.command_id == uuid5(command.command_id, str(lead.id)),
        )
    )
    if done is None:
        made = [
            await _make(desk, uuid5(command.command_id, f"new:{index}"), name, None)
            for index, name in enumerate(command.new)
        ]
        add = [*(await known(desk, command.add)), *made]
        remove = await known(desk, command.remove)
        result = await apply(
            desk,
            [lead],
            add=list({tag.id: tag for tag in add}.values()),
            remove=remove,
            command_id=command.command_id,
            actor=desk.viewer.person_id,
        )
        added, removed = result.get(lead.id, ([], []))
    else:
        added, removed = [], []
    return LeadTagsChanged(
        lead_id=lead.id,
        tags=(await chips(desk, [lead.id])).get(lead.id, ()),
        added=len(added),
        removed=len(removed),
    )


async def carry(desk: LeadDesk, gone: Lead, kept: Lead, *, command_id: UUID) -> list[UUID]:
    """A merge: the merged-away lead's tags go on the kept lead too, as many as fit, in the
    workspace's order (the merged-away lead keeps its own). Returns the ids added, so an
    unmerge takes off exactly those (``uncarry``)."""
    theirs = (
        await desk.db.scalars(
            select(LeadTag)
            .join(
                LeadTagLink,
                (LeadTagLink.tag_id == LeadTag.id) & (LeadTagLink.tenant_id == LeadTag.tenant_id),
            )
            .where(LeadTagLink.tenant_id == desk.tenant_id, LeadTagLink.lead_id == gone.id)
            .order_by(LeadTag.position, LeadTag.created_at, LeadTag.id)
        )
    ).all()
    if not theirs:
        return []
    done = await apply(
        desk,
        [kept],
        add=list(theirs),
        command_id=command_id,
        actor=desk.viewer.person_id,
        extra={"source": "merge"},
        over="fit",
    )
    return [tag.id for tag in done.get(kept.id, ([], []))[0]]


async def uncarry(desk: LeadDesk, kept: Lead, tag_ids: Sequence[UUID], *, command_id: UUID) -> int:
    """An unmerge: take the merge's carried tags off the kept lead (those still there)."""
    found = await present(desk, tag_ids)
    if not found:
        return 0
    done = await apply(
        desk,
        [kept],
        remove=list(found.values()),
        command_id=command_id,
        actor=desk.viewer.person_id,
        extra={"source": "merge"},
    )
    return len(done.get(kept.id, ([], []))[1])
