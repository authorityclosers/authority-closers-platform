"""Placing a company-number call and following it to the lead's history.

1. ``prepare`` (inside the seller's request) checks the organisation, the lead, the
   seller's mobile and the budget, and writes the request to the ledger.
2. The provider is asked **after** that commits, outside any database transaction,
   so a slow provider never holds the audit chain (the 26 Oct provider-call convoy).
3. ``settle`` records whether the provider took the call.
4. ``refresh`` / ``finish`` fold what the provider reports (its webhook, or a poll
   while the seller watches). When the call ends, a ``call`` event goes on the lead's
   history as the seller's (``via: company``, talk time, answered or not), and the lead
   counts the call, like a call the phone logged by itself. The recording is fetched
   only when the seller's app asks for it, and goes through the usual upload, with its
   consent and the seller's AI setting (``http.py``).
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, time, timedelta
from typing import Any
from uuid import UUID, uuid5
from zoneinfo import ZoneInfo

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from ac_platform.lead_desk.models import Lead
from ac_platform.lead_desk.store import DeskError, LeadDesk, Viewer
from ac_platform.lead_desk.telephony import ledger, policy
from ac_platform.lead_desk.telephony.providers import (
    BridgeRequest,
    CallReport,
    Provider,
    TelephonyError,
)
from ac_platform.tenancy.models import Membership

NAMESPACE = UUID("6b1f3c2e-8d4a-4f7b-9c1e-2a5d7e9f0b13")
IST = ZoneInfo("Asia/Kolkata")


class CallRefused(Exception):
    """The call can't go from the company number; the words say why and what to do."""

    def __init__(self, refusal: policy.Refusal, *, status: int = 409) -> None:
        super().__init__(refusal.words)
        self.refusal = refusal
        self.status = status


def call_id_for(tenant_id: UUID, person_id: UUID, command_id: UUID) -> UUID:
    """The same tap sent twice is the same call."""
    return uuid5(NAMESPACE, f"{tenant_id}:{person_id}:{command_id}")


def day_start(now: datetime) -> datetime:
    local = now.astimezone(IST)
    return datetime.combine(local.date(), time.min, tzinfo=IST).astimezone(UTC)


def month_start(now: datetime) -> datetime:
    local = now.astimezone(IST)
    return datetime.combine(local.date().replace(day=1), time.min, tzinfo=IST).astimezone(UTC)


async def budget(
    db: AsyncSession, tenant_id: UUID, cap: policy.Limits, now: datetime
) -> policy.Budget:
    month = await ledger.spent(db, tenant_id, since=month_start(now), now=now)
    day = await ledger.spent(db, tenant_id, since=day_start(now), now=now)
    return policy.budget(cap, month_spent=month, day_spent=day)


@dataclass(frozen=True, slots=True)
class Prepared:
    call: ledger.CompanyCall
    bridge: BridgeRequest | None  # None: this tap was already placed


async def prepare(
    desk: LeadDesk,
    *,
    lead_id: UUID,
    command_id: UUID,
    provider: Provider,
    run: policy.Rules,
    env: Any,
    status_url: Any,
    notice_url: Any,
) -> Prepared:
    """Checks everything and writes the request; the caller places the bridge after commit.

    ``status_url`` and ``notice_url`` are callables taking the call id (or None)."""
    now = desk.now
    call_id = call_id_for(desk.tenant_id, desk.viewer.person_id, command_id)
    seen = await ledger.read(desk.db, desk.tenant_id, call_id)
    if seen is not None:
        return Prepared(seen, None)
    _, config = await desk.settings()
    settings = policy.read(config)
    refusal = policy.place_check(settings, run, real_provider=provider.real)
    if refusal is not None:
        raise CallRefused(refusal)
    lead = await desk._lead(lead_id, lock=True)
    if not (desk.viewer.can_manage or lead.owner_person_id == desk.viewer.person_id):
        raise DeskError(403, "Only the lead's owner or a manager can call this lead.")
    refusal = policy.lead_check(
        settings,
        run,
        source=lead.source,
        asked_at=lead.created_at,
        phone=lead.phone,
        now=now,
        real_provider=provider.real,
    ) or policy.mobile_check(settings, run, desk.viewer.person_id, real_provider=provider.real)
    if refusal is not None:
        raise CallRefused(refusal)
    cap = policy.limits(config, env)
    left = await budget(desk.db, desk.tenant_id, cap, now)
    limit = policy.time_limit(left.left_paise, cap.rate_paise)
    if left.paused is not None or limit is None:
        raise CallRefused(policy.PAUSED)
    reserve = min(policy.reserve_paise(cap.rate_paise), left.left_paise)
    mobile = settings.mobiles[str(desk.viewer.person_id)]
    assert settings.number is not None and lead.phone is not None  # checked above
    notice = settings.notice
    await ledger.requested(
        desk.db,
        call_id=call_id,
        tenant_id=desk.tenant_id,
        person_id=desk.viewer.person_id,
        session_id=desk.viewer.session_id,
        lead_id=lead.id,
        provider=provider.name,
        caller_id=settings.number,
        lead_phone=lead.phone,
        seller_phone=mobile,
        notice_version=notice.version if notice else None,
        time_limit=limit,
        rate_paise=cap.rate_paise,
        reserve_paise=reserve,
        source=lead.source,
        command_id=command_id,
        now=now,
    )
    call = ledger.CompanyCall(
        id=call_id,
        tenant_id=desk.tenant_id,
        lead_id=lead.id,
        seller_person_id=desk.viewer.person_id,
        provider=provider.name,
        requested_at=now,
        time_limit=limit,
        rate_paise=cap.rate_paise,
        reserve_paise=reserve,
        notice_version=notice.version if notice else None,
    )
    bridge = BridgeRequest(
        seller=mobile,
        lead=lead.phone,
        caller_id=settings.number,
        reference=str(call_id),
        status_url=status_url(call_id),
        notice_url=notice_url(notice) if notice else None,
        time_limit=limit,
    )
    return Prepared(call, bridge)


async def settle(
    sessions: async_sessionmaker[AsyncSession],
    provider: Provider,
    prepared: Prepared,
    *,
    now: datetime,
) -> ledger.CompanyCall:
    """Asks the provider (no transaction open), then records its answer."""
    call = prepared.call
    if prepared.bridge is None:
        return call
    try:
        taken = await provider.start_bridge(prepared.bridge)
    except TelephonyError as error:
        async with sessions() as db, db.begin():
            await ledger.not_placed(db, call, words=str(error), code=error.code, now=now)
        raise
    async with sessions() as db, db.begin():
        await ledger.placed(db, call, sid=taken.sid, status=taken.status, now=now)
        found = await ledger.read(db, call.tenant_id, call.id)
    return found or call


def _words(report: CallReport) -> str | None:
    if not report.final:
        return None
    if report.seller_answered is False or (
        report.seller_answered is None and not report.talk_seconds and report.status != "completed"
    ):
        return "You didn't pick up, so the lead wasn't called."
    if report.lead_answered:
        return None
    if report.status == "busy":
        return "Their line was busy."
    if report.status == "failed":
        return "The call didn't go through."
    return "They didn't answer."


async def _history(
    db: AsyncSession, call: ledger.CompanyCall, report: CallReport, now: datetime
) -> UUID | None:
    """The ended call on the lead's history, as the seller's, once."""
    role = await db.scalar(
        select(Membership.role).where(
            Membership.tenant_id == call.tenant_id,
            Membership.person_id == call.seller_person_id,
            Membership.status == "active",
            Membership.ended_at.is_(None),
        )
    )
    lead = await db.scalar(
        select(Lead)
        .where(Lead.tenant_id == call.tenant_id, Lead.id == call.lead_id)
        .with_for_update()
    )
    if lead is None:  # deleted since
        return None
    desk = LeadDesk(
        db,
        Viewer(
            person_id=call.seller_person_id,
            tenant_id=call.tenant_id,
            role=role or "member",
            name="",
        ),
        now=now,
    )
    lead = await desk._live(lead, lock=True)
    key = uuid5(NAMESPACE, f"{call.id}:history")
    seen = await desk._command_seen(key)
    if seen is not None:
        return seen.id
    talk = report.talk_seconds or 0
    talked = bool(report.lead_answered) and talk > 0
    start = min(call.requested_at, now)
    contact = max(start, lead.created_at)
    lead.calls += 1
    lead.last_contact_at = max(lead.last_contact_at or contact, contact)
    lead.first_contact_at = min(lead.first_contact_at or contact, contact)
    lead.revision += 1
    lead.updated_at = now
    event = desk._event(
        lead,
        "call",
        {
            "via": "company",
            "company_call": str(call.id),
            "direction": "outgoing",
            "duration_seconds": talk,
            "connected": talked,
            "status": report.status,
            "submission_id": None,
            "simulated": call.provider == "fake",
        },
        actor=call.seller_person_id,
        command_id=key,
        at=start,
    )
    await db.flush()
    return event.id


async def finish(
    db: AsyncSession, call: ledger.CompanyCall, report: CallReport, *, now: datetime
) -> ledger.CompanyCall:
    """One report from the provider, folded in (inside the caller's transaction)."""
    if call.final or (report.status == call.status and not report.final):
        return call
    cost: int | None = None
    lead_event_id: UUID | None = None
    if report.final:
        legs = report.leg_seconds or tuple(
            seconds for seconds in (report.total_seconds, report.talk_seconds) if seconds
        )
        cost = (
            report.price_paise
            if report.price_paise is not None
            else policy.cost_paise(legs, call.rate_paise)
        )
        if report.seller_answered is not False and (
            report.seller_answered or report.talk_seconds or report.status == "completed"
        ):
            lead_event_id = await _history(db, call, report, now)
    await ledger.status(
        db,
        call,
        report,
        cost_paise=cost,
        priced=report.price_paise is not None,
        lead_event_id=lead_event_id,
        words=_words(report),
        now=now,
    )
    return await ledger.read(db, call.tenant_id, call.id) or call


async def refresh(
    sessions: async_sessionmaker[AsyncSession],
    provider: Provider | None,
    tenant_id: UUID,
    call_id: UUID,
    *,
    now: datetime,
    report: CallReport | None = None,
) -> ledger.CompanyCall | None:
    """Asks the provider how the call is going (unless a report came with its webhook)."""
    async with sessions() as db, db.begin():
        call = await ledger.read(db, tenant_id, call_id)
    if (
        call is None
        or call.final
        or not call.sid
        or provider is None
        or call.provider != provider.name
    ):
        return call
    if report is None:
        try:
            report = await provider.report(call.sid)
        except TelephonyError:
            return call
    if report.sid and report.sid != call.sid:
        return call
    async with sessions() as db, db.begin():
        # One writer per lead at a time: two reports at once can't both end the call.
        await db.scalar(
            select(Lead.id)
            .where(Lead.tenant_id == tenant_id, Lead.id == call.lead_id)
            .with_for_update()
        )
        call = await ledger.read(db, tenant_id, call_id)
        if call is None:
            return None
        return await finish(db, call, report, now=now)


def stale(call: ledger.CompanyCall, now: datetime) -> bool:
    """Long past its time limit and still not ended: worth asking the provider again."""
    return not call.final and now - call.requested_at > timedelta(seconds=call.time_limit + 1800)
