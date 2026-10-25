"""Notes and search on the Lead Desk (owner, 24 Oct 2026: "she has to see notes ... she
just can't"; v0.89: a Notes view, and search across leads, notes and tasks).

Notes are what people wrote on the leads the viewer can see, newest first: a note on its
own, or the remark saved with a call's outcome. Search finds a few words in a lead's
name, company, city or number, in those notes, and in the open tasks. Both read only;
the workspace bounds every query, and at most a page comes back.
"""

from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING, Any, Final, Literal

from sqlalchemy import and_, or_, select

from ac_platform.lead_desk import tasks as task_book
from ac_platform.lead_desk.contracts import ActivityItem, ActivityPage, SearchResult
from ac_platform.lead_desk.errors import DeskError
from ac_platform.lead_desk.journey import model as journeys
from ac_platform.lead_desk.models import Lead, LeadEvent, LeadTask

if TYPE_CHECKING:
    from ac_platform.lead_desk.store import LeadDesk

NOTES_PAGE: Final = 50
# Each kind of answer in search: enough to find it, short enough to read on a phone.
FOUND: Final = 8


def words(q: str | None) -> str | None:
    """The words to look for, or None for none; a single letter finds too much."""
    text = (q or "").strip()[:80]
    if not text:
        return None
    if len(text) < 2:
        raise DeskError(422, "Type at least two letters.")
    return text


def _like(text: str) -> str:
    """ILIKE's own characters stay literal."""
    escaped = text.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
    return f"%{escaped}%"


def _written() -> Any:
    """A note, or an outcome with a remark."""
    return or_(
        LeadEvent.kind == "note",
        and_(LeadEvent.kind == "result", LeadEvent.data["remark"].as_string().is_not(None)),
    )


async def notes(
    desk: LeadDesk,
    *,
    q: str | None = None,
    before: datetime | None = None,
    limit: int = NOTES_PAGE,
) -> ActivityPage:
    """What people wrote on the viewer's leads, newest first; with ``q``, only what says it
    (or whose lead's name does)."""
    limit = max(1, min(NOTES_PAGE, limit))
    needle = words(q)
    where: list[Any] = [
        LeadEvent.tenant_id == desk.tenant_id,
        _written(),
        desk._visible(),
    ]
    if needle is not None:
        like = _like(needle)
        where.append(
            or_(
                LeadEvent.data["note"].as_string().ilike(like, escape="\\"),
                LeadEvent.data["remark"].as_string().ilike(like, escape="\\"),
                Lead.name.ilike(like, escape="\\"),
            )
        )
    if before is not None:
        where.append(LeadEvent.created_at < before)
    joined = and_(Lead.id == LeadEvent.lead_id, Lead.tenant_id == LeadEvent.tenant_id)
    rows = (
        await desk.db.execute(
            select(LeadEvent, Lead)
            .join(Lead, joined)
            .where(*where)
            .order_by(LeadEvent.created_at.desc(), LeadEvent.id.desc())
            .limit(limit + 1)
        )
    ).all()
    more = len(rows) > limit
    rows = rows[:limit]
    names = await desk._names(event.actor_person_id for event, _ in rows)
    # A note an AI app added and someone undid stays out (docs/product/ai-writes.md).
    removed = await desk._undone(str(event.id) for event, _ in rows)
    labels: dict[str, journeys.Journey] = {}
    items: list[ActivityItem] = []
    for event, lead in rows:
        if str(event.id) in removed:
            continue
        key = journeys.pipeline_of(lead)
        if key not in labels:
            labels[key] = await desk._labels(key)
        items.append(
            ActivityItem(
                event_id=event.id,
                lead_id=lead.id,
                lead_name=lead.name,
                stage_label=labels[key].label(lead.stage, lead.step),
                event=desk._event_view(event, names),
            )
        )
    return ActivityPage(
        items=tuple(items),
        next_before=rows[-1][0].created_at if more and rows else None,
        counts={"note": len(items)},
    )


async def search(desk: LeadDesk, q: str | None) -> SearchResult:
    """A few words, everywhere a seller looks: leads, notes and open tasks."""
    needle = words(q)
    if needle is None:
        return SearchResult(leads=(), notes=(), tasks=())
    scope: Literal["mine", "team"] = "team" if desk.viewer.can_manage else "mine"
    leads = await desk.leads(scope=scope, stage=None, search=needle, offset=0, limit=FOUND)
    written = await notes(desk, q=needle, limit=FOUND)
    like = _like(needle)
    found = (
        await desk.db.execute(
            select(LeadTask, Lead.name)
            .join(Lead, and_(Lead.id == LeadTask.lead_id, Lead.tenant_id == LeadTask.tenant_id))
            .where(
                LeadTask.tenant_id == desk.tenant_id,
                LeadTask.status == "open",
                desk._visible(),
                or_(
                    LeadTask.title.ilike(like, escape="\\"),
                    LeadTask.note.ilike(like, escape="\\"),
                    LeadTask.location.ilike(like, escape="\\"),
                ),
            )
            .order_by(LeadTask.starts_at, LeadTask.id)
            .limit(FOUND)
        )
    ).all()
    return SearchResult(
        leads=leads.leads,
        notes=written.items,
        tasks=tuple(task_book.view(task, name, desk.now) for task, name in found),
    )
