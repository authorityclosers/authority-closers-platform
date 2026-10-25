"""Nudges on the seller's phone (team engine, section 3; docs/product/lead-desk/
team-engine.md): a distinct, urgent push that brings a seller back to work.

For each seller with a phone in a workspace that turned nudges on, ``team.nudge_now``
decides by the pure rule in ``nudges``: in work hours only (quiet hours are the server's),
one per two-hour window, three a day, never within ten minutes of a call. The window goes
into the ledger (``lead_desk_nudges``, unique per seller and window) before the push, so two
senders send one. The push carries no lead and no words, only ``kind = "nudge"``,
``urgency = "urgent"`` and how much work waits; the app reads the words from
``GET /v1/lead-desk/alert?kind=nudge`` on the seller's own session and plays its own sound.

It runs inside the lead alerts' pass (``push.tick``), under the same lock, and looks at
each seller at most every five minutes.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Final
from uuid import UUID, uuid4

from sqlalchemy import and_, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from ac_platform.lead_desk import team
from ac_platform.lead_desk.models import LeadDeskSettings, LeadDevice, LeadNudge
from ac_platform.lead_desk.store import SELLER_ROLES, LeadDesk, Viewer
from ac_platform.tenancy.models import Membership

EVERY: Final = timedelta(minutes=5)
# When each seller was last looked at, in this process: the rule reads a week of activity.
_looked: dict[tuple[UUID, UUID], datetime] = {}


@dataclass(slots=True)
class NudgeAlert:
    tenant_id: UUID
    person_id: UUID
    due: int
    tokens: list[str] = field(default_factory=list)

    def data(self) -> dict[str, str]:
        """The FCM data: no lead, no words, only that it is an urgent nudge."""
        return {
            "type": "lead_desk",
            "kind": "nudge",
            "urgency": "urgent",
            "tenant": str(self.tenant_id),
            "count": str(self.due),
        }


async def collect(
    database: AsyncSession, now: datetime, *, every: timedelta = EVERY
) -> list[NudgeAlert]:
    """The nudges to send now, each written to the ledger first (the caller commits)."""
    switched = [
        row.tenant_id
        for row in (await database.scalars(select(LeadDeskSettings))).all()
        if dict((row.config or {}).get("team") or {}).get("nudges")
    ]
    if not switched:
        return []
    phones: dict[tuple[UUID, UUID], list[str]] = defaultdict(list)
    for tenant_id, person_id, token in (
        await database.execute(
            select(LeadDevice.tenant_id, LeadDevice.person_id, LeadDevice.token)
            .join(
                Membership,
                and_(
                    Membership.tenant_id == LeadDevice.tenant_id,
                    Membership.person_id == LeadDevice.person_id,
                ),
            )
            .where(
                LeadDevice.tenant_id.in_(switched),
                Membership.status == "active",
                Membership.ended_at.is_(None),
                Membership.role.in_(SELLER_ROLES),
            )
        )
    ).tuples():
        phones[(tenant_id, person_id)].append(token)
    alerts: list[NudgeAlert] = []
    for (tenant_id, person_id), tokens in phones.items():
        looked = _looked.get((tenant_id, person_id))
        if looked is not None and timedelta(0) <= now - looked < every:
            continue
        _looked[(tenant_id, person_id)] = now
        desk = LeadDesk(
            database,
            Viewer(person_id=person_id, tenant_id=tenant_id, role="member", name=""),
            now=now,
        )
        found = await team.nudge_now(desk)
        if found is None:
            continue
        chosen, due = found
        claimed = await database.scalar(
            insert(LeadNudge)
            .values(
                id=uuid4(),
                tenant_id=tenant_id,
                person_id=person_id,
                kind=chosen.kind,
                window_start=chosen.window_start,
                words=chosen.words[:200],
                claimed_at=now,
                sent_at=now,
            )
            .on_conflict_do_nothing(index_elements=["tenant_id", "person_id", "window_start"])
            .returning(LeadNudge.id)
        )
        if claimed is not None:
            alerts.append(NudgeAlert(tenant_id, person_id, due, tokens))
    return alerts
