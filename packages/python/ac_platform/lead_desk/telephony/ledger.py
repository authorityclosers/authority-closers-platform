"""Each company-number call as append-only audit events, in the organisation's chain.

A call is one resource (``lead_desk_company_call``, its id). It is never edited: each
step appends an event, and reading folds them in order, the newest word winning.

1. **requested**: who, which lead, which notice, the time limit and what the call
   holds of the budget. This is written before the provider is asked, so a call is on
   record even if the provider's answer is lost.
2. **placed** (with the provider's call id), or **not placed** (with the words).
3. **status**: each change the provider reports. The final one carries the talk time,
   the cost (the provider's price, else our estimate) and the lead's history event.
4. **recording fetched**: the recording was handed to the seller's app for analysis,
   with its size and SHA-256 (provenance).

Phone numbers are kept as their last four digits only; the lead's number is on the
lead, and the seller's in Settings. Costs stay here and in Admin, never in the app.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, replace
from datetime import UTC, datetime, timedelta
from typing import Any, Final
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ac_platform.audit.models import AuditEvent
from ac_platform.audit.service import AuditRepository
from ac_platform.lead_desk.telephony.providers import FINAL, CallReport

RESOURCE_TYPE: Final = "lead_desk_company_call"
REQUESTED: Final = "lead_desk.company_call.requested.v1"
PLACED: Final = "lead_desk.company_call.placed.v1"
NOT_PLACED: Final = "lead_desk.company_call.not_placed.v1"
STATUS: Final = "lead_desk.company_call.status.v1"
RECORDING: Final = "lead_desk.company_call.recording_fetched.v1"
# A call nobody heard back about holds its reserve this long, then stops counting.
RESERVE_FOR: Final = timedelta(hours=2)


def tail(number: str | None) -> str | None:
    return f"…{number[-4:]}" if number else None


@dataclass(frozen=True, slots=True)
class CompanyCall:
    id: UUID
    tenant_id: UUID
    lead_id: UUID
    seller_person_id: UUID
    provider: str
    requested_at: datetime
    time_limit: int
    rate_paise: int
    reserve_paise: int
    notice_version: str | None
    status: str = "requested"
    sid: str | None = None
    words: str | None = None
    seller_answered: bool | None = None
    lead_answered: bool | None = None
    talk_seconds: int | None = None
    cost_paise: int | None = None
    recording: bool = False
    lead_event_id: UUID | None = None
    updated_at: datetime | None = None

    @property
    def final(self) -> bool:
        return self.status in FINAL or self.status == "not_placed"

    def holds(self, now: datetime) -> int:
        """What the call counts against the budget now."""
        if self.final:
            return self.cost_paise or 0
        return self.reserve_paise if now - self.requested_at < RESERVE_FOR else 0


def _uuid(raw: object) -> UUID | None:
    try:
        return UUID(str(raw))
    except (TypeError, ValueError):
        return None


def _utc(moment: datetime) -> datetime:
    return moment.replace(tzinfo=UTC) if moment.tzinfo is None else moment.astimezone(UTC)


def fold(
    rows: Sequence[tuple[str, Mapping[str, Any], datetime]], call_id: UUID, tenant_id: UUID
) -> CompanyCall | None:
    """The call as its events tell it, oldest first; None without a request."""
    call: CompanyCall | None = None
    for action, payload, at in rows:
        at = _utc(at)
        if action == REQUESTED:
            lead_id = _uuid(payload.get("lead_id"))
            seller = _uuid(payload.get("seller_person_id"))
            if lead_id is None or seller is None:
                continue
            call = CompanyCall(
                id=call_id,
                tenant_id=tenant_id,
                lead_id=lead_id,
                seller_person_id=seller,
                provider=str(payload.get("provider") or ""),
                requested_at=at,
                time_limit=int(payload.get("time_limit") or 0),
                rate_paise=int(payload.get("rate_paise") or 0),
                reserve_paise=int(payload.get("reserve_paise") or 0),
                notice_version=payload.get("notice_version")
                if isinstance(payload.get("notice_version"), str)
                else None,
                updated_at=at,
            )
        elif call is None:
            continue
        elif action == PLACED:
            call = replace(
                call,
                sid=str(payload.get("sid") or ""),
                status=str(payload.get("status") or "queued"),
                updated_at=at,
            )
        elif action == NOT_PLACED:
            call = replace(
                call,
                status="not_placed",
                words=str(payload.get("words") or ""),
                cost_paise=0,
                updated_at=at,
            )
        elif action == STATUS and not call.final:
            call = replace(
                call,
                status=str(payload.get("status") or call.status),
                seller_answered=payload.get("seller_answered")
                if isinstance(payload.get("seller_answered"), bool)
                else call.seller_answered,
                lead_answered=payload.get("lead_answered")
                if isinstance(payload.get("lead_answered"), bool)
                else call.lead_answered,
                talk_seconds=payload.get("talk_seconds")
                if isinstance(payload.get("talk_seconds"), int)
                else call.talk_seconds,
                cost_paise=payload.get("cost_paise")
                if isinstance(payload.get("cost_paise"), int)
                else call.cost_paise,
                recording=payload.get("recording") is True or call.recording,
                lead_event_id=_uuid(payload.get("lead_event_id")) or call.lead_event_id,
                words=payload.get("words") if isinstance(payload.get("words"), str) else call.words,
                updated_at=at,
            )
    return call


async def _rows(
    db: AsyncSession, tenant_id: UUID, *, call_id: UUID | None = None, since: datetime | None = None
) -> list[Any]:
    query = select(
        AuditEvent.resource_id, AuditEvent.action, AuditEvent.payload, AuditEvent.occurred_at
    ).where(AuditEvent.tenant_id == tenant_id, AuditEvent.resource_type == RESOURCE_TYPE)
    if call_id is not None:
        query = query.where(AuditEvent.resource_id == str(call_id))
    if since is not None:
        query = query.where(AuditEvent.occurred_at >= since)
    query = query.order_by(AuditEvent.occurred_at, AuditEvent.sequence_no)
    return list((await db.execute(query)).all())


async def read(db: AsyncSession, tenant_id: UUID, call_id: UUID) -> CompanyCall | None:
    rows = await _rows(db, tenant_id, call_id=call_id)
    return fold(
        [
            (row.action, row.payload if isinstance(row.payload, Mapping) else {}, row.occurred_at)
            for row in rows
        ],
        call_id,
        tenant_id,
    )


async def spent(db: AsyncSession, tenant_id: UUID, *, since: datetime, now: datetime) -> int:
    """What the calls requested since then cost or still hold, in paise."""
    grouped: dict[str, list[tuple[str, Mapping[str, Any], datetime]]] = {}
    for row in await _rows(db, tenant_id, since=since):
        grouped.setdefault(str(row.resource_id), []).append(
            (row.action, row.payload if isinstance(row.payload, Mapping) else {}, row.occurred_at)
        )
    total = 0
    for resource_id, rows in grouped.items():
        call_id = _uuid(resource_id)
        call = fold(rows, call_id, tenant_id) if call_id is not None else None
        if call is not None:
            total += call.holds(now)
    return total


async def _append(
    db: AsyncSession,
    *,
    tenant_id: UUID,
    call_id: UUID,
    action: str,
    payload: dict[str, Any],
    reason: str,
    now: datetime,
    person_id: UUID | None = None,
    session_id: UUID | None = None,
) -> None:
    await AuditRepository(db).append(
        tenant_id=tenant_id,
        actor_person_id=person_id,
        actor_type="person" if person_id is not None else "provider",
        session_id=session_id,
        action=action,
        resource_type=RESOURCE_TYPE,
        resource_id=str(call_id),
        payload=payload,
        reason=reason,
        now=now,
    )


async def requested(
    db: AsyncSession,
    *,
    call_id: UUID,
    tenant_id: UUID,
    person_id: UUID,
    session_id: UUID | None,
    lead_id: UUID,
    provider: str,
    caller_id: str,
    lead_phone: str,
    seller_phone: str,
    notice_version: str | None,
    time_limit: int,
    rate_paise: int,
    reserve_paise: int,
    source: str,
    command_id: UUID,
    now: datetime,
) -> None:
    await _append(
        db,
        tenant_id=tenant_id,
        call_id=call_id,
        action=REQUESTED,
        payload={
            "lead_id": str(lead_id),
            "seller_person_id": str(person_id),
            "provider": provider,
            "caller_id": caller_id,
            "lead_phone": tail(lead_phone),
            "seller_phone": tail(seller_phone),
            "notice_version": notice_version,
            "record": True,
            "time_limit": time_limit,
            "rate_paise": rate_paise,
            "reserve_paise": reserve_paise,
            "lead_source": source,
            "command_id": str(command_id),
        },
        reason="Called a lead from the company number.",
        now=now,
        person_id=person_id,
        session_id=session_id,
    )


async def placed(
    db: AsyncSession, call: CompanyCall, *, sid: str, status: str, now: datetime
) -> None:
    await _append(
        db,
        tenant_id=call.tenant_id,
        call_id=call.id,
        action=PLACED,
        payload={"sid": sid, "status": status},
        reason="The calling service took the call.",
        now=now,
    )


async def not_placed(
    db: AsyncSession, call: CompanyCall, *, words: str, code: str | None, now: datetime
) -> None:
    await _append(
        db,
        tenant_id=call.tenant_id,
        call_id=call.id,
        action=NOT_PLACED,
        payload={"words": words, "code": code},
        reason="The calling service didn't take the call.",
        now=now,
    )


async def status(
    db: AsyncSession,
    call: CompanyCall,
    report: CallReport,
    *,
    cost_paise: int | None,
    priced: bool,
    lead_event_id: UUID | None,
    words: str | None,
    now: datetime,
) -> None:
    await _append(
        db,
        tenant_id=call.tenant_id,
        call_id=call.id,
        action=STATUS,
        payload={
            "status": report.status,
            "final": report.final,
            "seller_answered": report.seller_answered,
            "lead_answered": report.lead_answered,
            "talk_seconds": report.talk_seconds,
            "total_seconds": report.total_seconds,
            "leg_seconds": list(report.leg_seconds),
            "cost_paise": cost_paise,
            "cost_from": "provider" if priced else "estimate",
            "recording": bool(report.recording_url),
            "lead_event_id": str(lead_event_id) if lead_event_id else None,
            "words": words,
        },
        reason="The calling service reported the call's progress.",
        now=now,
    )


async def recording_fetched(
    db: AsyncSession, call: CompanyCall, *, person_id: UUID, size: int, sha256: str, now: datetime
) -> None:
    await _append(
        db,
        tenant_id=call.tenant_id,
        call_id=call.id,
        action=RECORDING,
        payload={"bytes": size, "sha256": sha256, "provider": call.provider, "sid": call.sid},
        reason="The call's recording was handed to the seller's app for analysis.",
        now=now,
        person_id=person_id,
    )
