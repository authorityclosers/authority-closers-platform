"""Lead calls stuck before analysis, across organisations, for Admin Health's "Stuck now".

Owner order, 30 Oct 2026: "I need each single call getting tracked". A connected lead call
whose recording has not reached the server 30 minutes after the call ended is stuck at
"recorded": the seller's phone names the cause (a held upload, a blocked network, no recorder),
and the AC team sees it here. Read-only and bounded. It shows workspace, seller, time and length,
never the lead's name, number or audio. Private and sample calls are left out, as on the
seller's own screens (capture_guard).
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import String, and_, cast, exists, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import aliased

from ac_platform.identity.models import Person
from ac_platform.lead_desk.models import LeadEvent
from ac_platform.tenancy.models import Organisation, Tenant

WINDOW = timedelta(days=2)
LATE = timedelta(minutes=30)
LIMIT = 50
_NOT_TALKED = {"missed", "rejected", "blocked"}


def expects_recording(data: dict[str, Any]) -> bool:
    """A connected call with a lead, not a sample and not itself a recording row."""
    if not isinstance(data, dict) or data.get("simulated") or data.get("recording") is True:
        return False
    if data.get("for_call") or data.get("direction") in _NOT_TALKED:
        return False
    seconds = data.get("duration_seconds")
    return isinstance(seconds, int | float) and seconds > 0


def overdue(at: datetime, data: dict[str, Any], now: datetime) -> bool:
    """No recording 30 minutes after the call ended (the capture guard's "missing")."""
    return now - (at + timedelta(seconds=float(data.get("duration_seconds") or 0))) >= LATE


async def stuck_calls(db: AsyncSession, *, now: datetime, limit: int = LIMIT) -> dict[str, Any]:
    attachment = aliased(LeadEvent)
    rows = (
        await db.execute(
            select(LeadEvent, Tenant.name, Person.display_name)
            .join(Organisation, Organisation.tenant_id == LeadEvent.tenant_id)
            .join(Tenant, Tenant.id == LeadEvent.tenant_id)
            .outerjoin(Person, Person.id == LeadEvent.actor_person_id)
            .where(
                LeadEvent.kind == "call",
                LeadEvent.created_at >= now - WINDOW,
                LeadEvent.created_at <= now - LATE,
                ~exists().where(
                    and_(
                        attachment.tenant_id == LeadEvent.tenant_id,
                        attachment.kind == "call",
                        attachment.data["for_call"].as_string() == cast(LeadEvent.id, String),
                        attachment.data["recording"].as_boolean().is_(True),
                    )
                ),
            )
            .order_by(LeadEvent.created_at.desc(), LeadEvent.id)
            .limit(limit * 4 + 1)
        )
    ).all()
    candidates = [
        (event, workspace, seller)
        for event, workspace, seller in rows
        if expects_recording(event.data) and overdue(_utc(event.created_at), event.data, now)
    ]
    private = await _private(db, {event.tenant_id for event, _, _ in candidates}, now - WINDOW)
    calls = [
        {
            "event_id": str(event.id),
            "tenant_id": str(event.tenant_id),
            "workspace": workspace,
            "seller": seller or "Seller",
            "at": _utc(event.created_at).isoformat(),
            "seconds": int(float(event.data.get("duration_seconds") or 0)),
            "reason": "no_recording",
        }
        for event, workspace, seller in candidates
        if str(event.id) not in private
    ]
    return {"calls": calls[:limit], "truncated": len(calls) > limit or len(rows) > limit * 4}


async def _private(db: AsyncSession, tenants: set[Any], since: datetime) -> frozenset[str]:
    """Calls their sellers marked private (the newest marker wins), as LeadDesk._private_calls."""
    from ac_platform.lead_desk.store import PRIVATE_CALL  # the store imports half the app

    if not tenants:
        return frozenset()
    state: dict[str, bool] = {}
    for data in (
        await db.scalars(
            select(LeadEvent.data)
            .where(
                LeadEvent.tenant_id.in_(tenants),
                LeadEvent.kind == "edited",
                LeadEvent.created_at >= since,
            )
            .order_by(LeadEvent.created_at)
        )
    ).all():
        call = data.get(PRIVATE_CALL) if isinstance(data, dict) else None
        if isinstance(call, str):
            state[call] = data.get("private") is True
    return frozenset(call for call, private in state.items() if private)


def _utc(at: datetime) -> datetime:
    return at.replace(tzinfo=UTC) if at.tzinfo is None else at
