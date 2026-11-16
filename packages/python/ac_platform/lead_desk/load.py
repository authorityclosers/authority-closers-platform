"""Each seller's load, for the assign sheet and "By seller" (owner, 16 Nov 2026; 02-management-
findings-and-spec.md §4.4, M3 Assign, M6 and §6; the owner's 17 Nov pick M1-C: "perfect,
needed"; docs/product/lead-desk/lead-management-api.md §3).

For one side (Inbound or Cold), per person who works leads, and for nobody's leads:

- **open:** leads in the six working stages, not history, archived or binned;
- **late:** open leads more than an hour past their follow-up (or a new lead past its first
  hour), the rule the badge and the rows use (``store.overdue_filter``);
- **due_today:** open leads whose follow-up is today (business day, India time), not late;
- **untouched_7d:** open leads nobody has reached or tried for 7 days (no contact since, and in
  the desk for 7 days or more);
- **by_stage:** open leads per desk stage.

Per-seller numbers add up: the stages to ``open``, the sellers plus ``unassigned`` to
``totals``. The counts are one grouped read; the people come from the team's own list (with
whether they take new leads and their open-lead limit). Reads only.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import timedelta
from typing import TYPE_CHECKING, Final

from sqlalchemy import and_, func, or_, select

from ac_platform.lead_desk.contracts import LoadCounts, SellerLoad, SellerLoads
from ac_platform.lead_desk.errors import DeskError
from ac_platform.lead_desk.models import Lead
from ac_platform.lead_desk.sides import Side, on_side
from ac_platform.lead_desk.vocabulary import OPEN_STAGES

if TYPE_CHECKING:
    from uuid import UUID

    from ac_platform.lead_desk.store import LeadDesk

UNTOUCHED: Final = timedelta(days=7)


@dataclass(slots=True)
class _Tally:
    open: int = 0
    late: int = 0
    due_today: int = 0
    untouched_7d: int = 0
    by_stage: dict[str, int] = field(default_factory=dict)

    def add(self, stage: str, opened: int, late: int, today: int, stale: int) -> None:
        self.open += opened
        self.late += late
        self.due_today += today
        self.untouched_7d += stale
        self.by_stage[stage] = self.by_stage.get(stage, 0) + opened

    def view(self) -> LoadCounts:
        return LoadCounts(
            open=self.open,
            late=self.late,
            due_today=self.due_today,
            untouched_7d=self.untouched_7d,
            by_stage=dict(self.by_stage),
        )


async def seller_loads(desk: LeadDesk, side: Side = "inbound") -> SellerLoads:
    """Every seller's load on one side, and the leads nobody owns (owners, admins, managers
    and viewers; sellers see their own on Home)."""
    from ac_platform.lead_desk.store import overdue_filter

    if not desk.viewer.can_see_team:
        raise DeskError(403, "Your role sees your own leads only.")
    now = desk.now
    day_start = desk._day_start()
    day_end = day_start + timedelta(days=1)
    late = overdue_filter(now)
    stale = now - UNTOUCHED
    untouched = and_(
        or_(Lead.last_contact_at.is_(None), Lead.last_contact_at < stale),
        Lead.created_at < stale,
    )
    rows = (
        await desk.db.execute(
            select(
                Lead.owner_person_id,
                Lead.stage,
                func.count(),
                func.count().filter(late),
                func.count().filter(
                    and_(~late, Lead.next_action_at >= day_start, Lead.next_action_at < day_end)
                ),
                func.count().filter(untouched),
            )
            .where(Lead.tenant_id == desk.tenant_id, Lead.stage.in_(OPEN_STAGES), on_side(side))
            .group_by(Lead.owner_person_id, Lead.stage)
        )
    ).all()
    per: dict[UUID | None, _Tally] = {}
    totals = _Tally()
    for owner, stage, opened, overdue, today, stale_count in rows:
        for tally in (per.setdefault(owner, _Tally()), totals):
            tally.add(str(stage), int(opened), int(overdue), int(today), int(stale_count))
    reps = await desk._reps()
    listed = {rep.state.person_id for rep in reps}
    # Someone who holds open leads but no longer works them (a manager, a past seller) still
    # shows, so the numbers add up.
    others = [owner for owner in per if owner is not None and owner not in listed]
    names = await desk._names(others)
    sellers = [
        SellerLoad(
            person_id=rep.state.person_id,
            name=rep.state.name,
            role=rep.role,
            takes_new_leads=rep.state.available,
            max_open=rep.state.max_open,
            load=per.get(rep.state.person_id, _Tally()).view(),
        )
        for rep in reps
    ] + [
        SellerLoad(
            person_id=owner,
            name=names.get(owner) or "A former teammate",
            role=None,
            takes_new_leads=False,
            max_open=None,
            load=per[owner].view(),
        )
        for owner in sorted(others, key=lambda person: (names.get(person) or "").lower())
    ]
    return SellerLoads(
        side=side,
        generated_at=now,
        sellers=tuple(sellers),
        unassigned=per.get(None, _Tally()).view(),
        totals=totals.view(),
    )
