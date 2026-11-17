"""Saved views on Leads, on the server (owner, 16 Nov 2026; 02-management-findings-and-spec.md
§4.6, M5 and §6; the owner's 17 Nov pick M4-B; docs/product/lead-desk/lead-management-api.md
§4).

A view is a named Leads list: the same filter options as GET /leads (``LeadFilter``) and how it
shows (``display``: columns, density, sort; the screen's own small JSON). It is one person's
("me": only they see it) or the team's ("team": everyone in the workspace sees it; owners,
admins and managers make, change and delete those). The list gives each view's count on
request, as the list itself would count it for the person asking (a seller's team view counts
only what they may see). A seller never sees another person's "me" views.

Changes are by revision (a stale edit is refused, never lost silently); a create is idempotent
by ``command_id``. A deleted view is removed: it is a preference, not history.
"""

from __future__ import annotations

import json
from typing import TYPE_CHECKING, Any, Final
from uuid import UUID, uuid4

from sqlalchemy import and_, func, or_, select

from ac_platform.lead_desk.contracts import (
    LeadFilter,
    SavedView,
    SavedViewCommand,
    SavedViewDelete,
    SavedViewEdit,
    SavedViews,
)
from ac_platform.lead_desk.errors import DeskError
from ac_platform.lead_desk.models import LeadSavedView

if TYPE_CHECKING:
    from ac_platform.lead_desk.store import LeadDesk

MAX_VIEWS: Final = 40  # per person, and for the team
MAX_DISPLAY_BYTES: Final = 4000


def _may_change(desk: LeadDesk, view: LeadSavedView) -> None:
    if view.visibility == "team":
        if not desk.viewer.can_manage:
            raise DeskError(403, "Only owners, admins and managers change team views.")
    elif view.owner_person_id != desk.viewer.person_id:
        raise DeskError(404, "This view isn't here.")


def _check_display(display: dict[str, object]) -> None:
    if len(json.dumps(display, separators=(",", ":"))) > MAX_DISPLAY_BYTES:
        raise DeskError(422, "This view's layout is too large to save.")


def _seen(desk: LeadDesk) -> Any:
    return and_(
        LeadSavedView.tenant_id == desk.tenant_id,
        or_(
            LeadSavedView.visibility == "team",
            LeadSavedView.owner_person_id == desk.viewer.person_id,
        ),
    )


async def _count(desk: LeadDesk, query: LeadFilter) -> int | None:
    """The view's number as its list would show it to this person; None when they can't open
    it (a team-wide list for a seller's role)."""
    try:
        page = await desk.leads(
            scope=query.scope,
            stage=query.stage,
            search=query.search,
            offset=0,
            test_only=query.test,
            older_only=query.older,
            owner=query.owner,
            pipeline=query.pipeline,
            source=query.source,
            due=query.due,
            contact=query.contact,
            created=query.created,
            duplicates=query.duplicates,
            side=query.side,
            view=query.view,
            step=query.step,
            when=query.when,
            since=query.since,
            until=query.until,
            shelf=query.shelf,
            freeze=0,
            tag=query.tag,
        )
    except DeskError:
        return None
    return page.total


async def _view(desk: LeadDesk, row: LeadSavedView, *, counts: bool) -> SavedView:
    query = LeadFilter.model_validate(row.query)
    return SavedView(
        view_id=row.id,
        name=row.name,
        visibility=row.visibility,
        owner_person_id=row.owner_person_id,
        mine=row.owner_person_id == desk.viewer.person_id,
        can_change=row.visibility == "team"
        and desk.viewer.can_manage
        or row.visibility == "me"
        and row.owner_person_id == desk.viewer.person_id,
        filter=query,
        display=row.display,
        position=row.position,
        revision=row.revision,
        count=await _count(desk, query) if counts else None,
        created_at=row.created_at,
        updated_at=row.updated_at,
    )


async def _row(desk: LeadDesk, view_id: UUID, *, lock: bool = False) -> LeadSavedView:
    query = select(LeadSavedView).where(LeadSavedView.id == view_id, _seen(desk))
    row = await desk.db.scalar(query.with_for_update() if lock else query)
    if row is None:
        raise DeskError(404, "This view isn't here.")
    return row


async def listed(desk: LeadDesk, *, counts: bool = False) -> SavedViews:
    """The team's views, then this person's own, each in its order."""
    rows = (
        await desk.db.scalars(
            select(LeadSavedView)
            .where(_seen(desk))
            .order_by(
                (LeadSavedView.visibility == "me").asc(),
                LeadSavedView.position,
                LeadSavedView.created_at,
            )
        )
    ).all()
    return SavedViews(views=tuple([await _view(desk, row, counts=counts) for row in rows]))


async def create(desk: LeadDesk, command: SavedViewCommand) -> SavedView:
    if command.visibility == "team" and not desk.viewer.can_manage:
        raise DeskError(403, "Only owners, admins and managers make team views.")
    done = await desk.db.scalar(
        select(LeadSavedView).where(
            LeadSavedView.tenant_id == desk.tenant_id,
            LeadSavedView.command_id == command.command_id,
        )
    )
    if done is not None:
        return await _view(desk, done, counts=False)
    _check_display(command.display)
    mine = (
        LeadSavedView.visibility == "team"
        if command.visibility == "team"
        else and_(
            LeadSavedView.visibility == "me",
            LeadSavedView.owner_person_id == desk.viewer.person_id,
        )
    )
    taken = (
        await desk.db.execute(
            select(func.count(), func.coalesce(func.max(LeadSavedView.position), -1)).where(
                LeadSavedView.tenant_id == desk.tenant_id, mine
            )
        )
    ).one()
    if int(taken[0]) >= MAX_VIEWS:
        raise DeskError(422, f"Up to {MAX_VIEWS} views; delete one first.")
    same = await desk.db.scalar(
        select(LeadSavedView.id).where(
            LeadSavedView.tenant_id == desk.tenant_id,
            mine,
            func.lower(LeadSavedView.name) == command.name.lower(),
        )
    )
    if same is not None:
        raise DeskError(409, "A view with this name is already here.")
    row = LeadSavedView(
        id=uuid4(),
        tenant_id=desk.tenant_id,
        owner_person_id=desk.viewer.person_id,
        visibility=command.visibility,
        name=command.name,
        query=command.filter.model_dump(mode="json", exclude_none=True),
        display=dict(command.display),
        position=int(taken[1]) + 1,
        revision=1,
        command_id=command.command_id,
        created_at=desk.now,
        updated_at=desk.now,
    )
    desk.db.add(row)
    await desk.db.flush()
    return await _view(desk, row, counts=False)


async def edit(desk: LeadDesk, view_id: UUID, command: SavedViewEdit) -> SavedView:
    row = await _row(desk, view_id, lock=True)
    _may_change(desk, row)
    if row.revision != command.expected_revision:
        raise DeskError(409, "This view changed since you opened it. Open it again.")
    if command.visibility is not None and command.visibility != row.visibility:
        if not desk.viewer.can_manage:
            raise DeskError(403, "Only owners, admins and managers make team views.")
        row.visibility = command.visibility
    if command.name is not None and command.name.lower() != row.name.lower():
        same = await desk.db.scalar(
            select(LeadSavedView.id).where(
                LeadSavedView.tenant_id == desk.tenant_id,
                LeadSavedView.id != row.id,
                LeadSavedView.visibility == row.visibility,
                or_(
                    LeadSavedView.visibility == "team",
                    LeadSavedView.owner_person_id == row.owner_person_id,
                ),
                func.lower(LeadSavedView.name) == command.name.lower(),
            )
        )
        if same is not None:
            raise DeskError(409, "A view with this name is already here.")
    if command.name is not None:
        row.name = command.name
    if command.filter is not None:
        row.query = command.filter.model_dump(mode="json", exclude_none=True)
    if command.display is not None:
        _check_display(command.display)
        row.display = dict(command.display)
    if command.position is not None:
        row.position = command.position
    row.revision += 1
    row.updated_at = desk.now
    await desk.db.flush()
    return await _view(desk, row, counts=False)


async def delete(desk: LeadDesk, view_id: UUID, command: SavedViewDelete) -> SavedViews:
    row = await _row(desk, view_id, lock=True)
    _may_change(desk, row)
    if row.revision != command.expected_revision:
        raise DeskError(409, "This view changed since you opened it. Open it again.")
    await desk.db.delete(row)
    await desk.db.flush()
    return await listed(desk)
