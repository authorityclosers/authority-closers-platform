"""The day's digest and the two-hourly sweep on each seller's phone (rules: ``digests``).

For each seller with a phone, in a workspace that hasn't turned them off (settings
``team.digests`` false), when a slot is due (10:00 IST for the digest; 12:00, 14:00, 16:00 and
18:00 for the sweep, inside work hours when the workspace has some), it counts the seller's
own work and writes the slot to the ledger (``lead_desk_digests``, unique per seller, kind and
slot) before the push, so two senders send one. A slot with nothing to say is written and not
sent. The push carries the kind and a count, never a lead or words; the app reads the words
from ``GET /v1/lead-desk/alert?kind=digest|sweep`` on the seller's own session.

It runs inside the lead alerts' pass (``push.tick``), under the same lock.
"""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Collection
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import TYPE_CHECKING
from uuid import UUID, uuid4

from sqlalchemy import and_, func, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from ac_platform.lead_desk import digests
from ac_platform.lead_desk import hours as work_hours
from ac_platform.lead_desk.contracts import AlertText
from ac_platform.lead_desk.models import Lead, LeadDevice, LeadDigest
from ac_platform.lead_desk.vocabulary import OPEN_STAGES
from ac_platform.tenancy.models import Membership

if TYPE_CHECKING:
    from ac_platform.lead_desk.store import LeadDesk


@dataclass(slots=True)
class DigestAlert:
    tenant_id: UUID
    person_id: UUID
    kind: digests.Kind
    count: int
    tokens: list[str] = field(default_factory=list)

    def data(self) -> dict[str, str]:
        """The FCM data: the kind and a count, no lead and no words."""
        return {
            "type": "lead_desk",
            "kind": self.kind,
            "tenant": str(self.tenant_id),
            "count": str(self.count),
        }


async def counts(desk: LeadDesk) -> dict[str, int]:
    """The seller's own work: follow-ups due by the end of today (late ones too), follow-ups
    already late, and new leads not yet called."""
    mine = and_(
        Lead.tenant_id == desk.tenant_id,
        Lead.owner_person_id == desk.viewer.person_id,
        Lead.stage.in_(OPEN_STAGES),
    )
    day_end = desk._day_start() + timedelta(days=1)
    row = (
        await desk.db.execute(
            select(
                func.count().filter(Lead.next_action_at < day_end),
                func.count().filter(Lead.next_action_at < desk.now),
                func.count().filter(and_(Lead.stage == "new", Lead.next_action_at.is_(None))),
            ).where(mine)
        )
    ).one()
    return {"follow_ups": int(row[0]), "overdue": int(row[1]), "new": int(row[2])}


def _words(kind: digests.Kind, found: dict[str, int]) -> digests.Words | None:
    if kind == "digest":
        return digests.digest_words(found["follow_ups"])
    return digests.sweep_words(found["overdue"], found["new"])


def _count(kind: digests.Kind, found: dict[str, int]) -> int:
    return found["follow_ups"] if kind == "digest" else found["overdue"] + found["new"]


async def words(desk: LeadDesk, kind: digests.Kind) -> AlertText:
    """The words on a digest or sweep push, counted now on the seller's own session."""
    said = _words(kind, await counts(desk))
    if said is None:
        return AlertText(title="Nothing due right now", body="", lead_id=None, url="/leads")
    return AlertText(title=said.title, body=said.body, lead_id=None, url=said.url)


async def collect(
    database: AsyncSession,
    now: datetime,
    *,
    tenants: Collection[UUID] | None = None,
    forced: digests.Kind | None = None,
) -> list[DigestAlert]:
    """The digests and sweeps to send now, each written to the ledger first (the caller
    commits). ``forced`` sends that kind now, in its own slot (this moment), whatever the
    clock and work hours say: the on-demand test (``send-digests-now.py``), only for the
    workspaces in ``tenants``."""
    from ac_platform.lead_desk.store import SELLER_ROLES, LeadDesk, Viewer

    phones: dict[UUID, dict[UUID, list[str]]] = defaultdict(lambda: defaultdict(list))
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
                Membership.status == "active",
                Membership.ended_at.is_(None),
                Membership.role.in_(SELLER_ROLES),
                *([LeadDevice.tenant_id.in_(tuple(tenants))] if tenants is not None else []),
            )
        )
    ).tuples():
        phones[tenant_id][person_id].append(token)
    alerts: list[DigestAlert] = []
    for tenant_id, people in phones.items():
        first = next(iter(people))
        _, config = await LeadDesk(
            database, Viewer(person_id=first, tenant_id=tenant_id, role="member", name=""), now=now
        ).settings()
        if forced is not None:
            slot: digests.Due | None = digests.Due(forced, now)
        elif dict(config.get("team") or {}).get("digests") is False:
            continue
        else:
            slot = digests.due(now, work_hours.parse(config))
        if slot is None:
            continue
        written = set(
            (
                await database.scalars(
                    select(LeadDigest.person_id).where(
                        LeadDigest.tenant_id == tenant_id,
                        LeadDigest.kind == slot.kind,
                        LeadDigest.slot == slot.slot,
                    )
                )
            ).all()
        )
        for person_id, tokens in people.items():
            if person_id in written:
                continue
            desk = LeadDesk(
                database,
                Viewer(person_id=person_id, tenant_id=tenant_id, role="member", name=""),
                now=now,
            )
            found = await counts(desk)
            say = _words(slot.kind, found) is not None
            claimed = await database.scalar(
                insert(LeadDigest)
                .values(
                    id=uuid4(),
                    tenant_id=tenant_id,
                    person_id=person_id,
                    kind=slot.kind,
                    slot=slot.slot,
                    counts=found,
                    claimed_at=now,
                    sent_at=now if say else None,
                )
                .on_conflict_do_nothing(index_elements=["tenant_id", "person_id", "kind", "slot"])
                .returning(LeadDigest.id)
            )
            if claimed is not None and say:
                alerts.append(
                    DigestAlert(tenant_id, person_id, slot.kind, _count(slot.kind, found), tokens)
                )
    return alerts
