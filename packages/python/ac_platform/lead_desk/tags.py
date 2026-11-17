"""Lead tags (owner's picks, 17 Nov 2026: the M2-A bar's "Add tag", the M1-A dock's Tag and
lead import I4-A "Source and tags", e.g. "Nov video ad"; docs/product/lead-desk/
lead-management-api.md §5).

A tag is a workspace's own short word with a colour (migration 0161, ``lead_desk_tags``); a
lead carries up to ``MAX_ON_LEAD`` of them (``lead_desk_lead_tags``). Owners, admins and
managers make, rename, recolour and delete tags; anyone who may change a lead puts the
workspace's tags on it or takes them off. Many leads at once go through a bulk job ("tag" /
"untag", bulk_jobs.py), undoable for its 30 minutes; an import can tag every lead it makes.

A tag change is a history line on the lead (an "edited" event: ``changed`` ["tags"] with the
tag names added and taken off), and never the lead's revision: a tag is no edit of the lead's
details, so a seller's open edit of the same lead never goes stale because of it.

A deleted tag comes off every lead at once; the lines already in their history keep its name.
One audit event says who deleted it and from how many leads (ids and counts only).
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from typing import TYPE_CHECKING, Any, Final
from uuid import UUID, uuid4, uuid5

from sqlalchemy import delete, func, select

from ac_platform.audit.service import AuditRepository
from ac_platform.lead_desk.contracts import (
    LeadRow,
    LeadTags,
    LeadTagsChange,
    Tag,
    TagChip,
    TagCommand,
    TagDelete,
    TagEdit,
    Tags,
)
from ac_platform.lead_desk.errors import DeskError
from ac_platform.lead_desk.models import Lead, LeadEvent, LeadTag, LeadTagLink

if TYPE_CHECKING:
    from ac_platform.lead_desk.store import LeadDesk

MAX_TAGS: Final = 60  # per workspace
MAX_ON_LEAD: Final = 10
FIELD: Final = "tags"
ADDED: Final = "tags_added"
REMOVED: Final = "tags_removed"
DELETED: Final = "lead_desk.tag.deleted"


def key(name: str) -> str:
    """How two names are the same tag: case and spaces aside ("Nov  Video ad")."""
    return " ".join(name.split()).lower()


def _clean(name: str) -> str:
    cleaned = " ".join(name.split())
    if not cleaned:
        raise DeskError(422, "Give the tag a name.")
    return cleaned


def _manager(desk: LeadDesk) -> None:
    if not desk.viewer.can_manage:
        raise DeskError(403, "Only owners, admins and managers make and change tags.")


def has_tag(tenant_id: UUID, tag_id: UUID) -> Any:
    """GET /leads?tag=: the leads carrying this tag."""
    return Lead.id.in_(
        select(LeadTagLink.lead_id).where(
            LeadTagLink.tenant_id == tenant_id, LeadTagLink.tag_id == tag_id
        )
    )


def _view(row: LeadTag, leads: int | None = None) -> Tag:
    return Tag(
        tag_id=row.id,
        name=row.name,
        colour=row.colour,
        revision=row.revision,
        leads=leads,
        created_at=row.created_at,
    )


async def _tag(desk: LeadDesk, tag_id: UUID, *, lock: bool = False) -> LeadTag:
    query = select(LeadTag).where(LeadTag.tenant_id == desk.tenant_id, LeadTag.id == tag_id)
    row = await desk.db.scalar(query.with_for_update() if lock else query)
    if row is None:
        raise DeskError(404, "This tag isn't here.")
    return row


async def _tags(desk: LeadDesk, tag_ids: Iterable[UUID]) -> list[LeadTag]:
    wanted = list(dict.fromkeys(tag_ids))
    if not wanted:
        return []
    rows = list(
        await desk.db.scalars(
            select(LeadTag).where(LeadTag.tenant_id == desk.tenant_id, LeadTag.id.in_(wanted))
        )
    )
    if len(rows) != len(wanted):
        raise DeskError(404, "One of these tags isn't here any more.")
    order = {tag_id: index for index, tag_id in enumerate(wanted)}
    rows.sort(key=lambda row: order[row.id])
    return rows


async def listed(desk: LeadDesk, *, counts: bool = True) -> Tags:
    """The workspace's tags by name, each with how many leads carry it (Bin aside)."""
    rows = (
        await desk.db.scalars(
            select(LeadTag).where(LeadTag.tenant_id == desk.tenant_id).order_by(LeadTag.name_key)
        )
    ).all()
    numbers: dict[UUID, int] = {}
    if counts and rows:
        numbers = {
            tag_id: int(count)
            for tag_id, count in (
                await desk.db.execute(
                    select(LeadTagLink.tag_id, func.count())
                    .join(Lead, Lead.id == LeadTagLink.lead_id)
                    .where(
                        LeadTagLink.tenant_id == desk.tenant_id,
                        desk._seen(),
                        Lead.binned_at.is_(None),
                    )
                    .group_by(LeadTagLink.tag_id)
                )
            ).all()
        }
    return Tags(
        tags=tuple(_view(row, numbers.get(row.id, 0) if counts else None) for row in rows),
        can_change=desk.viewer.can_manage,
    )


async def create(desk: LeadDesk, command: TagCommand) -> Tag:
    """A new tag; a name already here gives that tag back (the sheet's "Create" twice)."""
    _manager(desk)
    done = await desk.db.scalar(
        select(LeadTag).where(
            LeadTag.tenant_id == desk.tenant_id, LeadTag.command_id == command.command_id
        )
    )
    if done is not None:
        return _view(done)
    name = _clean(command.name)
    same = await desk.db.scalar(
        select(LeadTag).where(LeadTag.tenant_id == desk.tenant_id, LeadTag.name_key == key(name))
    )
    if same is not None:
        return _view(same)
    taken = int(
        await desk.db.scalar(
            select(func.count()).select_from(LeadTag).where(LeadTag.tenant_id == desk.tenant_id)
        )
        or 0
    )
    if taken >= MAX_TAGS:
        raise DeskError(422, f"Up to {MAX_TAGS} tags; delete one first.")
    row = LeadTag(
        id=uuid4(),
        tenant_id=desk.tenant_id,
        name=name,
        name_key=key(name),
        colour=command.colour,
        revision=1,
        command_id=command.command_id,
        created_by_person_id=desk.viewer.person_id,
        created_at=desk.now,
        updated_at=desk.now,
    )
    desk.db.add(row)
    await desk.db.flush()
    return _view(row)


async def edit(desk: LeadDesk, tag_id: UUID, command: TagEdit) -> Tag:
    _manager(desk)
    row = await _tag(desk, tag_id, lock=True)
    if row.revision != command.expected_revision:
        raise DeskError(409, "This tag changed since you opened it. Open it again.")
    if command.name is not None:
        name = _clean(command.name)
        same = await desk.db.scalar(
            select(LeadTag.id).where(
                LeadTag.tenant_id == desk.tenant_id,
                LeadTag.id != row.id,
                LeadTag.name_key == key(name),
            )
        )
        if same is not None:
            raise DeskError(409, "A tag with this name is already here.")
        row.name, row.name_key = name, key(name)
    if command.colour is not None:
        row.colour = command.colour
    row.revision += 1
    row.updated_at = desk.now
    await desk.db.flush()
    return _view(row)


async def delete_tag(desk: LeadDesk, tag_id: UUID, command: TagDelete) -> Tags:
    """The tag comes off every lead; their history keeps its name."""
    _manager(desk)
    row = await _tag(desk, tag_id, lock=True)
    if row.revision != command.expected_revision:
        raise DeskError(409, "This tag changed since you opened it. Open it again.")
    removed = await desk.db.execute(
        delete(LeadTagLink)
        .where(LeadTagLink.tenant_id == desk.tenant_id, LeadTagLink.tag_id == row.id)
        .execution_options(synchronize_session=False)
    )
    await AuditRepository(desk.db).append(
        tenant_id=desk.tenant_id,
        actor_person_id=desk.viewer.person_id,
        session_id=desk.viewer.session_id,
        action=DELETED,
        resource_type="lead_desk.tag",
        resource_id=str(row.id),
        payload={"leads": int(getattr(removed, "rowcount", 0) or 0)},
        reason="Tag deleted in Leads",
        now=desk.now,
    )
    await desk.db.delete(row)
    await desk.db.flush()
    return await listed(desk)


async def chips(desk: LeadDesk, lead_ids: Sequence[UUID]) -> dict[UUID, tuple[TagChip, ...]]:
    """Each lead's tags, by name: one look-up for a page of rows."""
    if not lead_ids:
        return {}
    found: dict[UUID, list[TagChip]] = {}
    for lead_id, tag_id, name, colour in (
        await desk.db.execute(
            select(LeadTagLink.lead_id, LeadTag.id, LeadTag.name, LeadTag.colour)
            .join(LeadTag, LeadTag.id == LeadTagLink.tag_id)
            .where(LeadTagLink.tenant_id == desk.tenant_id, LeadTagLink.lead_id.in_(lead_ids))
            .order_by(LeadTag.name_key)
        )
    ).all():
        found.setdefault(lead_id, []).append(TagChip(tag_id=tag_id, name=name, colour=colour))
    return {lead_id: tuple(items) for lead_id, items in found.items()}


async def on_rows(desk: LeadDesk, rows: Sequence[LeadRow]) -> tuple[LeadRow, ...]:
    found = await chips(desk, [row.lead_id for row in rows])
    return tuple(
        row.model_copy(update={"tags": found[row.lead_id]}) if row.lead_id in found else row
        for row in rows
    )


def _words(added: Sequence[str], removed: Sequence[str]) -> str:
    parts = []
    if added:
        parts.append(f"Tagged {', '.join(added)}")
    if removed:
        parts.append(f"Tag taken off: {', '.join(removed)}")
    return " · ".join(parts)


async def apply(
    desk: LeadDesk,
    leads: Sequence[Lead],
    *,
    add: Sequence[LeadTag] = (),
    remove: Sequence[LeadTag] = (),
    command_id: UUID,
    per_lead: Any,
    history: bool = True,
    strict: bool = False,
) -> list[UUID]:
    """Put ``add`` on these leads and take ``remove`` off; a history line on each lead that
    changed (its command id ``per_lead(command_id, lead_id)``). The leads that changed."""
    ids = [lead.id for lead in leads]
    if not ids or not (add or remove):
        return []
    have: dict[UUID, set[UUID]] = {}
    for lead_id, tag_id in (
        await desk.db.execute(
            select(LeadTagLink.lead_id, LeadTagLink.tag_id).where(
                LeadTagLink.tenant_id == desk.tenant_id, LeadTagLink.lead_id.in_(ids)
            )
        )
    ).all():
        have.setdefault(lead_id, set()).add(tag_id)
    gone = {tag.id for tag in remove}
    changed: list[UUID] = []
    full = 0
    for lead in leads:
        now = have.get(lead.id, set())
        put = [tag for tag in add if tag.id not in now and tag.id not in gone]
        off = [tag for tag in remove if tag.id in now]
        if len(now) - len(off) + len(put) > MAX_ON_LEAD:
            full += 1
            continue
        if not put and not off:
            continue
        for tag in put:
            desk.db.add(
                LeadTagLink(
                    tenant_id=desk.tenant_id,
                    lead_id=lead.id,
                    tag_id=tag.id,
                    added_by_person_id=desk.viewer.person_id,
                    command_id=command_id,
                    added_at=desk.now,
                )
            )
        if off:
            await desk.db.execute(
                delete(LeadTagLink)
                .where(
                    LeadTagLink.tenant_id == desk.tenant_id,
                    LeadTagLink.lead_id == lead.id,
                    LeadTagLink.tag_id.in_([tag.id for tag in off]),
                )
                .execution_options(synchronize_session=False)
            )
        if history:
            added, removed = [tag.name for tag in put], [tag.name for tag in off]
            desk._event(
                lead,
                "edited",
                {
                    "changed": [FIELD],
                    ADDED: added,
                    REMOVED: removed,
                    "reason_text": _words(added, removed),
                },
                actor=desk.viewer.person_id,
                command_id=per_lead(command_id, lead.id),
            )
        changed.append(lead.id)
    if strict and full:
        raise DeskError(422, f"A lead carries up to {MAX_ON_LEAD} tags; take one off first.")
    await desk.db.flush()
    return changed


def tag_one(job_id: UUID, lead_id: UUID) -> UUID:
    """The per-lead command id of a tag change (its history line)."""
    return uuid5(job_id, f"tag:{lead_id}")


async def set_on_lead(desk: LeadDesk, lead_id: UUID, command: LeadTagsChange) -> LeadTags:
    """One lead's tags from its page: what to put on and take off (idempotent by command)."""
    lead = await desk._lead(lead_id, lock=True)
    again = await desk.db.scalar(
        select(LeadEvent.id).where(
            LeadEvent.tenant_id == desk.tenant_id,
            LeadEvent.command_id == tag_one(command.command_id, lead.id),
        )
    )
    if again is None:
        await apply(
            desk,
            [lead],
            add=await _tags(desk, command.add),
            remove=await _tags(desk, command.remove),
            command_id=command.command_id,
            per_lead=tag_one,
            strict=True,
        )
    return LeadTags(lead_id=lead.id, tags=(await chips(desk, [lead.id])).get(lead.id, ()))


async def bulk(
    desk: LeadDesk, leads: Sequence[Lead], tag_ids: Sequence[UUID], *, add: bool, job_id: UUID
) -> list[UUID]:
    """A bulk job's "tag" or "untag" (bulk_jobs.py): the leads that changed."""
    if not tag_ids:
        raise DeskError(422, "Choose a tag.")
    chosen = await _tags(desk, tag_ids)
    return await apply(
        desk,
        leads,
        add=chosen if add else (),
        remove=() if add else chosen,
        command_id=job_id,
        per_lead=tag_one,
    )


async def undo_bulk(
    desk: LeadDesk, job_id: UUID, lead_ids: Sequence[UUID], tag_ids: Sequence[UUID], *, added: bool
) -> list[UUID]:
    """Undo a tag job: the tags it put on come off again where they still are (and were put
    on by this job); a job that took tags off puts them back on, where the tag still exists.
    The leads put back."""
    tags = list(
        await desk.db.scalars(
            select(LeadTag).where(LeadTag.tenant_id == desk.tenant_id, LeadTag.id.in_(tag_ids))
        )
    )
    leads = list(
        await desk.db.scalars(
            select(Lead)
            .where(desk._visible(), Lead.id.in_(list(lead_ids)), Lead.binned_at.is_(None))
            .order_by(Lead.id)
        )
    )
    if not tags or not leads:
        return []
    if added:
        # Only what this job put on: a tag someone put on again since stays.
        mine = {
            (lead_id, tag_id)
            for lead_id, tag_id in (
                await desk.db.execute(
                    select(LeadTagLink.lead_id, LeadTagLink.tag_id).where(
                        LeadTagLink.tenant_id == desk.tenant_id,
                        LeadTagLink.command_id == job_id,
                    )
                )
            ).all()
        }
        restored: list[UUID] = []
        for lead in leads:
            off = [tag for tag in tags if (lead.id, tag.id) in mine]
            if off:
                restored += await apply(
                    desk,
                    [lead],
                    remove=off,
                    command_id=uuid5(job_id, "undo"),
                    per_lead=lambda command, lead_id: uuid5(job_id, f"undo:{lead_id}"),
                )
        return restored
    return await apply(
        desk,
        leads,
        add=tags,
        command_id=uuid5(job_id, "undo"),
        per_lead=lambda command, lead_id: uuid5(job_id, f"undo:{lead_id}"),
    )


async def on_import(
    desk: LeadDesk, lead_ids: Sequence[UUID], tag_ids: Sequence[UUID], *, import_id: UUID
) -> None:
    """An import's tags on every lead it made (I4-A "Source and tags"): its "captured" line
    already says where they came from, so no line of their own."""
    if not lead_ids or not tag_ids:
        return
    chosen = await _tags(desk, tag_ids)
    leads = list(
        await desk.db.scalars(
            select(Lead).where(Lead.tenant_id == desk.tenant_id, Lead.id.in_(list(lead_ids)))
        )
    )
    await apply(
        desk,
        leads,
        add=chosen[:MAX_ON_LEAD],
        command_id=import_id,
        per_lead=tag_one,
        history=False,
    )
