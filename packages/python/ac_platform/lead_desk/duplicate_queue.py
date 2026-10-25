"""The duplicate review queue (design: docs/product/lead-desk/duplicates.md, D4): owners and
managers see the pairs the scan found, the likeliest first, compare a pair side by side with
the reasons, the lead a merge would keep and who would have it, and decide: Merge
(``merging``) or Not the same, which keeps the pair out of every later scan. A lead's page
names its possible duplicates (to managers) and the lead it was merged into; a seller who
worked on a merged lead lately keeps reading the lead it went into ("worked before"). Admin
reads counts per organisation, never a lead.

Pairs are only ever read within the viewer's organisation (``tenant_id`` on every query).
"""

from __future__ import annotations

from collections.abc import Iterable
from typing import TYPE_CHECKING, Any, Final
from uuid import UUID, uuid5

from sqlalchemy import case, cast, delete, func, or_, select, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.ext.asyncio import AsyncSession

from ac_platform.lead_desk import dupes, duplicate_scan, merging
from ac_platform.lead_desk.contracts import (
    DuplicateBand,
    DuplicateCompare,
    DuplicateHint,
    DuplicateLead,
    DuplicatePairView,
    DuplicateQueue,
    MergedInto,
    NotSame,
    OwnerOption,
)
from ac_platform.lead_desk.errors import DeskError
from ac_platform.lead_desk.journey import model as journeys
from ac_platform.lead_desk.models import (
    Lead,
    LeadDuplicateDecision,
    LeadDuplicatePair,
    LeadMerge,
)
from ac_platform.lead_desk.vocabulary import SOURCE_LABELS

if TYPE_CHECKING:
    from ac_platform.lead_desk.store import LeadDesk

QUEUE_LIMIT: Final = 50
HINTS: Final = 5
# The pairs worth a person's look: the queue's default and the Leads "Duplicates" filter.
REVIEW: Final[tuple[DuplicateBand, ...]] = ("certain", "probable")
# Certain before probable before possible (a band is decided by its rule, not its score),
# then the score.
LIKELIEST: Final = (
    case(dupes.RANK, value=LeadDuplicatePair.band, else_=0).desc(),
    LeadDuplicatePair.score.desc(),
    LeadDuplicatePair.id,
)


def reviewable(tenant_id: UUID) -> Any:
    """The leads in a pair worth review, as a subquery (the Leads "Duplicates" filter)."""
    pairs = (LeadDuplicatePair.tenant_id == tenant_id, LeadDuplicatePair.band.in_(REVIEW))
    return (
        select(LeadDuplicatePair.first_lead_id)
        .where(*pairs)
        .union(select(LeadDuplicatePair.second_lead_id).where(*pairs))
    )


async def _sides(
    desk: LeadDesk, rows: Iterable[LeadDuplicatePair]
) -> tuple[dict[UUID, Lead], dict[UUID, DuplicateLead]]:
    wanted = {lead_id for row in rows for lead_id in (row.first_lead_id, row.second_lead_id)}
    if not wanted:
        return {}, {}
    leads = {
        lead.id: lead
        for lead in (
            await desk.db.scalars(
                select(Lead).where(Lead.tenant_id == desk.tenant_id, Lead.id.in_(wanted))
            )
        ).all()
    }
    for key in {journeys.pipeline_of(lead) for lead in leads.values()}:
        await desk._labels(key)
    names = await desk._names(lead.owner_person_id for lead in leads.values())
    full = bool((await desk.settings())[1].get("show_full_phones"))
    views = {
        lead.id: DuplicateLead(
            lead_id=lead.id,
            name=lead.name,
            company=lead.company,
            city=lead.city,
            phone_last4=lead.phone[-4:] if lead.phone else None,
            phone=lead.phone if full else None,
            email=lead.email,
            stage_label=desk._stage_label(lead),
            owner_person_id=lead.owner_person_id,
            owner_name=names.get(lead.owner_person_id) if lead.owner_person_id else None,
            source_label=lead.source_label or SOURCE_LABELS.get(lead.source, lead.source),
            received_at=lead.created_at,
        )
        for lead in leads.values()
    }
    return leads, views


def _pair(row: LeadDuplicatePair, sides: dict[UUID, DuplicateLead]) -> DuplicatePairView | None:
    first, second = sides.get(row.first_lead_id), sides.get(row.second_lead_id)
    if first is None or second is None:
        return None
    return DuplicatePairView(
        pair_id=row.id,
        band=row.band,
        score=row.score,
        reasons=tuple(row.reasons or ()),
        against=tuple(row.against or ()),
        first=first,
        second=second,
        computed_at=row.computed_at,
    )


async def queue(desk: LeadDesk, band: DuplicateBand | None = None) -> DuplicateQueue:
    """The pairs to review, the likeliest first, and how many there are in each band."""
    desk._require_manager()
    counts = {
        str(name): int(count)
        for name, count in (
            await desk.db.execute(
                select(LeadDuplicatePair.band, func.count())
                .where(LeadDuplicatePair.tenant_id == desk.tenant_id)
                .group_by(LeadDuplicatePair.band)
            )
        ).all()
    }
    bands = (band,) if band else REVIEW
    rows = (
        await desk.db.scalars(
            select(LeadDuplicatePair)
            .where(
                LeadDuplicatePair.tenant_id == desk.tenant_id,
                LeadDuplicatePair.band.in_(bands),
            )
            .order_by(*LIKELIEST)
            .limit(QUEUE_LIMIT)
        )
    ).all()
    _, sides = await _sides(desk, rows)
    return DuplicateQueue(
        pairs=tuple(view for row in rows if (view := _pair(row, sides)) is not None),
        total=sum(counts.get(name, 0) for name in bands),
        counts=counts,
    )


async def _row(desk: LeadDesk, pair_id: UUID) -> LeadDuplicatePair:
    row: LeadDuplicatePair | None = await desk.db.scalar(
        select(LeadDuplicatePair).where(
            LeadDuplicatePair.tenant_id == desk.tenant_id, LeadDuplicatePair.id == pair_id
        )
    )
    if row is None:
        raise DeskError(404, "This pair isn't waiting for review any more.")
    return row


async def compare(desk: LeadDesk, pair_id: UUID) -> DuplicateCompare:
    """One pair side by side: the reasons, the lead a merge would keep, who would have it
    and why; with two sellers active lately, the manager picks."""
    desk._require_manager()
    row = await _row(desk, pair_id)
    leads, sides = await _sides(desk, [row])
    view = _pair(row, sides)
    if view is None:
        raise DeskError(404, "One of these leads isn't here any more.")
    first = await merging._side(desk, leads[row.first_lead_id])
    second = await merging._side(desk, leads[row.second_lead_id])
    kept, _ = dupes.survivor(first, second)
    choice = dupes.owner_after(first, second, desk.now)
    candidates = [choice.person_id, *choice.others] if choice.person_id else []
    names = await desk._names(candidates)
    activity = {first.lead_id: first.human_activity, second.lead_id: second.human_activity}
    view = view.model_copy(
        update={
            "first": view.first.model_copy(update={"activity": activity[row.first_lead_id]}),
            "second": view.second.model_copy(update={"activity": activity[row.second_lead_id]}),
        }
    )
    name = names.get(choice.person_id) if choice.person_id else None
    return DuplicateCompare(
        pair=view,
        keep_lead_id=kept.lead_id,
        owner_person_id=choice.person_id,
        owner_name=name,
        owner_why=choice.why,
        owner_reason=merging._owner_words(
            choice.why,
            name,
            desk.viewer.name,
            [names[person] for person in choice.others if person in names],
        ),
        choose_owner=choice.why == "asked",
        owner_choices=tuple(
            OwnerOption(person_id=person, name=names[person])
            for person in candidates
            if person is not None and person in names
        )
        if choice.why == "asked"
        else (),
    )


async def not_same(desk: LeadDesk, pair_id: UUID, command: NotSame) -> DuplicateQueue:
    """Two different people after all: the pair leaves the queue, and no later scan brings
    it back. A retry of the same command is one decision."""
    desk._require_manager()
    decision_id = uuid5(command.command_id, "not-same")
    if await desk.db.get(LeadDuplicateDecision, decision_id) is None:
        row = await _row(desk, pair_id)
        desk.db.add(
            LeadDuplicateDecision(
                id=decision_id,
                tenant_id=desk.tenant_id,
                first_lead_id=row.first_lead_id,
                second_lead_id=row.second_lead_id,
                decision="not_same",
                decided_by_person_id=desk.viewer.person_id,
                decided_at=desk.now,
                note=(command.note or "").strip() or None,
            )
        )
        await desk.db.execute(
            delete(LeadDuplicatePair).where(
                LeadDuplicatePair.tenant_id == desk.tenant_id, LeadDuplicatePair.id == row.id
            )
        )
        await desk.db.flush()
    return await queue(desk)


async def scan_now(desk: LeadDesk) -> DuplicateQueue:
    """Look for duplicates now, as the six-hourly scan does; one at a time per organisation
    (a scan already running is left to finish)."""
    desk._require_manager()
    if await duplicate_scan.lock(desk.db, desk.tenant_id):
        await duplicate_scan.scan(desk.db, desk.tenant_id, desk.now)
        await desk.db.flush()
    return await queue(desk)


async def hints(desk: LeadDesk, lead: Lead) -> tuple[DuplicateHint, ...]:
    """The lead's possible duplicates, for its page (owners and managers only)."""
    if not desk.viewer.can_manage or lead.merged_into_id is not None:
        return ()
    rows = (
        await desk.db.scalars(
            select(LeadDuplicatePair)
            .where(
                LeadDuplicatePair.tenant_id == desk.tenant_id,
                or_(
                    LeadDuplicatePair.first_lead_id == lead.id,
                    LeadDuplicatePair.second_lead_id == lead.id,
                ),
            )
            .order_by(*LIKELIEST)
            .limit(HINTS)
        )
    ).all()
    others = {
        row.id: row.second_lead_id if row.first_lead_id == lead.id else row.first_lead_id
        for row in rows
    }
    names: dict[UUID, str] = {}
    if others:
        names = {
            lead_id: name
            for lead_id, name in (
                await desk.db.execute(
                    select(Lead.id, Lead.name).where(
                        Lead.tenant_id == desk.tenant_id, Lead.id.in_(set(others.values()))
                    )
                )
            ).tuples()
        }
    return tuple(
        DuplicateHint(
            pair_id=row.id,
            other_lead_id=others[row.id],
            other_name=names[others[row.id]],
            band=row.band,
            reasons=tuple(row.reasons or ()),
        )
        for row in rows
        if others[row.id] in names
    )


async def merged_into(desk: LeadDesk, lead: Lead) -> MergedInto | None:
    """The lead this one was merged into (followed to the last one), for its page."""
    if lead.merged_into_id is None:
        return None
    kept = await desk._live(lead)
    if kept.id == lead.id:
        return None
    mine = await desk.db.scalar(select(Lead.id).where(Lead.id == kept.id, desk._visible()))
    return MergedInto(
        lead_id=kept.id,
        name=kept.name,
        merged_at=lead.merged_at,
        can_open=mine is not None or await worked_before(desk, kept.id),
    )


async def worked_before(desk: LeadDesk, lead_id: UUID) -> bool:
    """Whether this person worked lately on a lead merged into this one (the merge names
    them): they keep reading it, without editing it."""
    found = await desk.db.scalar(
        select(LeadMerge.id)
        .where(
            LeadMerge.tenant_id == desk.tenant_id,
            LeadMerge.survivor_lead_id == lead_id,
            LeadMerge.undone_at.is_(None),
            cast(LeadMerge.moved["also_worked"], JSONB).contains([str(desk.viewer.person_id)]),
        )
        .limit(1)
    )
    return found is not None


_ADMIN = text(
    """
    WITH pairs AS (
      SELECT tenant_id,
             count(*) FILTER (WHERE band = 'certain') AS certain,
             count(*) FILTER (WHERE band = 'probable') AS probable,
             count(*) FILTER (WHERE band = 'possible') AS possible,
             max(computed_at) AS scanned_at
      FROM lead_desk_duplicate_pairs GROUP BY tenant_id
    ), merges AS (
      SELECT tenant_id,
             count(*) FILTER (WHERE undone_at IS NULL) AS merged,
             count(*) FILTER (WHERE undone_at IS NOT NULL) AS undone
      FROM lead_desk_merges GROUP BY tenant_id
    ), refused AS (
      SELECT tenant_id, count(*) AS not_same
      FROM lead_desk_duplicate_decisions WHERE decision = 'not_same' GROUP BY tenant_id
    ), here AS (
      SELECT tenant_id FROM pairs UNION SELECT tenant_id FROM merges
      UNION SELECT tenant_id FROM refused
    )
    SELECT h.tenant_id, t.name AS workspace,
           coalesce(p.certain, 0) AS certain, coalesce(p.probable, 0) AS probable,
           coalesce(p.possible, 0) AS possible, p.scanned_at,
           coalesce(m.merged, 0) AS merged, coalesce(m.undone, 0) AS undone,
           coalesce(r.not_same, 0) AS not_same
    FROM here h JOIN tenants t ON t.id = h.tenant_id
    LEFT JOIN pairs p ON p.tenant_id = h.tenant_id
    LEFT JOIN merges m ON m.tenant_id = h.tenant_id
    LEFT JOIN refused r ON r.tenant_id = h.tenant_id
    ORDER BY coalesce(p.certain, 0) + coalesce(p.probable, 0) DESC, t.name
    LIMIT 200
    """
)
_COUNTS: Final = ("certain", "probable", "possible", "merged", "undone", "not_same")


async def admin_overview(db: AsyncSession) -> dict[str, Any]:
    """Admin's metric for one environment: per organisation, the pairs waiting by band,
    merges kept and undone, pairs marked not the same, and the last scan. Counts only."""
    rows = [dict(row) for row in (await db.execute(_ADMIN)).mappings().all()]
    return {
        "totals": {key: sum(int(row[key]) for row in rows) for key in _COUNTS},
        "organisations": [
            {
                "tenant_id": str(row["tenant_id"]),
                "workspace": row["workspace"],
                **{key: int(row[key]) for key in _COUNTS},
                "scanned_at": row["scanned_at"].isoformat() if row["scanned_at"] else None,
            }
            for row in rows
        ],
    }
