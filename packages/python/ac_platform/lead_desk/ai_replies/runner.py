"""The AI replies loop inside the API, every 10 seconds, while Admin has them switched on.

The API never asks a model (it holds no model key). Each tick it:

1. claims each new message from a lead of an organisation in auto mode that nobody (and
   no other automation) has answered: one audit row per message. What the rules settle
   without a model is settled here (a stop, a hand-off); the rest is queued for the AI
   replies runner (``ai_replies.cli``), which asks the model Admin chose;
2. acts on what the runner decided for automatic replies: a draft is sent through the
   channel's own send (``auto="ai_reply"``) unless someone answered meanwhile or a newer
   message came, a hand-off alerts the lead's seller, a stop is recorded;
3. clears the drafts of leads that left Lead Desk.

One claimer at a time across API processes (advisory lock 1802/1270).
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager, suppress
from datetime import UTC, datetime, timedelta
from typing import Any, Final
from uuid import UUID, uuid4

import httpx
from fastapi import FastAPI
from sqlalchemy import select, text
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from ac_platform.lead_desk import push
from ac_platform.lead_desk.ai_replies import admin_settings, service
from ac_platform.lead_desk.models import Lead, LeadAiReply, LeadSocialAccount
from ac_platform.lead_desk.store import DeskError, LeadDesk, Viewer

log = logging.getLogger(__name__)

_TICK = 10
_LOCK = (1802, 1270)  # one claimer across API processes and slots
SETTLE_BATCH: Final[int] = 20
# Older than this, an automatic reply or a hand-off alert helps nobody (Meta's window
# is 24 hours): such a row is closed without acting.
LATE: Final[timedelta] = timedelta(days=1)


async def _locked(db: AsyncSession) -> bool:
    return bool(
        await db.scalar(
            text("SELECT pg_try_advisory_xact_lock(:a, :b)"), {"a": _LOCK[0], "b": _LOCK[1]}
        )
    )


async def claim(db: AsyncSession, *, now: datetime) -> int:
    """Waiting messages, each claimed by its audit row: settled by the rules, or queued."""
    claimed = 0
    for item in await service.waiting(db, now=now):
        reply_id = uuid4()
        made = await db.execute(
            insert(LeadAiReply)
            .values(
                id=reply_id,
                tenant_id=item.tenant_id,
                lead_id=item.lead_id,
                channel=item.channel,
                message_id=item.message_id,
                mode="auto",
                outcome="queued",
                reason=None,
                created_at=now,
            )
            .on_conflict_do_nothing(
                index_elements=["channel", "message_id"],
                index_where=text("mode = 'auto' AND message_id IS NOT NULL"),
            )
            .returning(LeadAiReply.id)
        )
        if made.first() is None:
            continue
        claimed += 1
        row = await db.get(LeadAiReply, reply_id)
        lead = await db.get(Lead, item.lead_id)
        if row is None or lead is None:
            continue
        if await service.opted_out(db, lead.id, item.channel):
            # They said stop on this channel: a person answers them, never the AI.
            row.outcome, row.reason = "handoff", "opt_out"
            continue
        ready = await service.prepare(db, lead, item.channel, account_id=item.account_id, now=now)
        settled = service.decide(ready)
        if settled is not None:
            service.apply(row, ready, settled, now=now)
    return claimed


async def send_on_channel(
    db: AsyncSession,
    client: httpx.AsyncClient,
    lead: Lead,
    channel: str,
    account_id: UUID | None,
    words: str,
    *,
    now: datetime,
) -> Any:
    """Send through the channel's own rules, marked as an AI reply."""
    if channel == "whatsapp":
        from ac_platform.lead_desk.whatsapp import cloud
        from ac_platform.lead_desk.whatsapp import inbox as wa_inbox

        cfg = cloud.config()
        rows = await wa_inbox.numbers(db, lead.tenant_id)
        if cfg is None or not rows:
            raise DeskError(409, "WhatsApp isn't connected.")
        desk = LeadDesk(
            db,
            Viewer(
                person_id=rows[0].connected_by_person_id,
                tenant_id=lead.tenant_id,
                role="system",
                name="AI replies",
            ),
            now=now,
        )
        return await wa_inbox.send(
            desk,
            cfg,
            cloud.Cloud(cfg, client, timeout=8),
            lead.id,
            command_id=uuid4(),
            number_id=None,
            body=words,
            template=None,
            language=None,
            values=[],
            auto="ai_reply",
        )
    from ac_platform.lead_desk.social import graph
    from ac_platform.lead_desk.social import inbox as social_inbox

    social_cfg = graph.config()
    account = await db.get(LeadSocialAccount, account_id) if account_id else None
    if social_cfg is None or account is None or account.status != "active":
        raise DeskError(409, "That Page isn't connected.")
    desk = LeadDesk(
        db,
        Viewer(
            person_id=account.connected_by_person_id,
            tenant_id=lead.tenant_id,
            role="system",
            name="AI replies",
        ),
        now=now,
    )
    return await social_inbox.send(
        desk,
        social_cfg,
        graph.Graph(social_cfg, client, timeout=8),
        lead.id,
        command_id=uuid4(),
        channel=channel,
        account_id=account.id,
        body=words,
        auto="ai_reply",
    )


async def settle(
    sessions: async_sessionmaker[AsyncSession],
    client: httpx.AsyncClient,
    fcm: push.Fcm | None,
    *,
    now: datetime,
) -> dict[str, int]:
    """Act on automatic replies the rules or the runner decided: send, alert or stop."""
    out = {"sent": 0, "handoff": 0, "stopped": 0, "failed": 0}
    async with sessions() as db:
        pending = list(
            (
                await db.scalars(
                    select(LeadAiReply.id)
                    .where(
                        LeadAiReply.mode == "auto",
                        LeadAiReply.settled_at.is_(None),
                        LeadAiReply.outcome.in_(("drafted", "handoff", "opted_out")),
                    )
                    .order_by(LeadAiReply.created_at)
                    .limit(SETTLE_BATCH)
                )
            ).all()
        )
    for reply_id in pending:
        tokens: list[str] = []
        lead: Lead | None = None
        async with sessions() as db, db.begin():
            row = await db.get(LeadAiReply, reply_id, with_for_update=True)
            if row is None or row.settled_at is not None:
                continue
            lead = await db.get(Lead, row.lead_id, with_for_update=True) if row.lead_id else None
            row.settled_at = now
            if row.created_at < now - LATE:
                if row.outcome == "drafted":
                    row.outcome, row.reason, row.draft = "failed", "late", None
                out["failed"] += 1
                continue
            if lead is None:
                row.outcome, row.reason, row.draft = "failed", "lead_gone", None
                out["failed"] += 1
                continue
            if row.outcome == "drafted":
                out[await _send(db, client, lead, row, now=now)] += 1
            elif row.outcome == "handoff":
                tokens = await service.owner_tokens(db, lead)
                out["handoff"] += 1
            else:
                await service.record_stop(service.system_desk(db, lead, now), lead, row.channel)
                out["stopped"] += 1
        if fcm is not None and lead is not None:
            for token in tokens:
                await fcm.send(client, token, service.handoff_alert(lead))
    return out


async def _send(
    db: AsyncSession, client: httpx.AsyncClient, lead: Lead, row: LeadAiReply, *, now: datetime
) -> str:
    """Send one drafted automatic reply, unless it no longer fits the conversation."""
    ready = await service.prepare_row(db, row, now=now)
    late = "lead_gone" if ready is None else service.gone_by(row, ready)
    if late is not None or ready is None or not row.draft:
        row.outcome, row.reason, row.draft = "failed", late or "failed", None
        return "failed"
    try:
        message = await send_on_channel(
            db, client, lead, row.channel, ready.account_id, row.draft, now=now
        )
    except DeskError as error:
        log.info("ai reply not sent: %s", error)
        row.outcome, row.reason = "failed", "window"
        return "failed"
    if getattr(message, "status", None) != "sent":
        row.outcome, row.reason = "failed", "failed"
        return "failed"
    row.outcome, row.reason, row.sent_message_id = "sent", None, message.id
    return "sent"


async def tick(
    sessions: async_sessionmaker[AsyncSession],
    client: httpx.AsyncClient,
    fcm: push.Fcm | None,
    *,
    now: datetime,
) -> dict[str, int]:
    """One tick: nothing at all while Admin has AI replies switched off."""
    out = {"claimed": 0, "erased": 0}
    async with sessions() as db, db.begin():
        if not await _locked(db):
            return out
        config, _ = await admin_settings.read(db)
        if not config["enabled"]:
            return out
        out["claimed"] = await claim(db, now=now)
    out.update(await settle(sessions, client, fcm, now=now))
    async with sessions() as db, db.begin():
        out["erased"] = await service.erasure_sweep(db, now)
    return out


async def run(
    sessions: async_sessionmaker[AsyncSession], stop: asyncio.Event, *, first_delay: int = _TICK
) -> None:
    with suppress(TimeoutError):
        await asyncio.wait_for(stop.wait(), timeout=first_delay)
    fcm_cfg = push.config()
    fcm = push.Fcm(fcm_cfg) if fcm_cfg is not None else None
    async with httpx.AsyncClient(timeout=15) as client:
        while not stop.is_set():
            try:
                await tick(sessions, client, fcm, now=datetime.now(UTC))
            except Exception:  # noqa: BLE001 - the loop must survive a bad tick
                log.warning("ai replies tick failed", exc_info=True)
            with suppress(TimeoutError):
                await asyncio.wait_for(stop.wait(), timeout=_TICK)


def attach(
    application: FastAPI, sessions: async_sessionmaker[AsyncSession], environment: str
) -> None:
    """Run the loop for the API's lifetime by wrapping the app's own lifespan."""
    if environment in {"local", "test"}:
        return
    inner = application.router.lifespan_context

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[Any]:
        async with inner(app) as state:
            stop = asyncio.Event()
            task = asyncio.create_task(run(sessions, stop), name="lead-desk-ai-replies")
            try:
                yield state
            finally:
                stop.set()
                task.cancel()
                with suppress(asyncio.CancelledError):
                    await task

    application.router.lifespan_context = lifespan
