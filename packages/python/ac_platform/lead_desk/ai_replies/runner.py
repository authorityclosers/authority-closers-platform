"""The AI replies loop for organisations in auto mode, every 10 seconds inside the API.

Each new message from a lead that nobody (and no other automation) has answered gets
one try: it is claimed first (the audit row, one per message), the model is asked with
no transaction open, then the reply is sent through the channel's own send, or the
conversation is handed to the lead's seller with a phone alert. One claimer at a time
across API processes (advisory lock 1802/1270).
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager, suppress
from datetime import UTC, datetime
from typing import Any
from uuid import UUID, uuid4

import httpx
from fastapi import FastAPI
from sqlalchemy import select, text
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from ac_platform.lead_desk import push
from ac_platform.lead_desk.ai_replies import service
from ac_platform.lead_desk.models import Lead, LeadAiReply, LeadSocialAccount
from ac_platform.lead_desk.store import DeskError, LeadDesk, Viewer

log = logging.getLogger(__name__)

_TICK = 10
_LOCK = (1802, 1270)  # one claimer across API processes and slots


class _Idle(Exception):
    """This tick has nothing to do (the model can't run here)."""


async def _locked(db: AsyncSession) -> bool:
    return bool(
        await db.scalar(
            text("SELECT pg_try_advisory_xact_lock(:a, :b)"), {"a": _LOCK[0], "b": _LOCK[1]}
        )
    )


async def claim(db: AsyncSession, *, now: datetime) -> list[tuple[UUID, service.Waiting]]:
    """Waiting messages, each claimed by its audit row (outcome filled in later)."""
    claimed: list[tuple[UUID, service.Waiting]] = []
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
                outcome="failed",
                reason="working",
                created_at=now,
            )
            .on_conflict_do_nothing(
                index_elements=["channel", "message_id"],
                index_where=text("mode = 'auto' AND message_id IS NOT NULL"),
            )
            .returning(LeadAiReply.id)
        )
        if made.first() is not None:
            claimed.append((reply_id, item))
    return claimed


async def send_on_channel(
    db: AsyncSession,
    client: httpx.AsyncClient,
    lead: Lead,
    item: service.Waiting,
    words: str,
    *,
    now: datetime,
) -> Any:
    """Send through the channel's own rules, marked as an AI reply."""
    if item.channel == "whatsapp":
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
    account = await db.get(LeadSocialAccount, item.account_id) if item.account_id else None
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
        channel=item.channel,
        account_id=account.id,
        body=words,
        auto="ai_reply",
    )


async def auto_pass(
    sessions: async_sessionmaker[AsyncSession],
    model: service.Model,
    client: httpx.AsyncClient,
    fcm: push.Fcm | None,
    *,
    now: datetime,
) -> dict[str, int]:
    out = {"claimed": 0, "sent": 0, "handoff": 0, "stopped": 0, "failed": 0, "erased": 0}
    async with sessions() as db, db.begin():
        if not await _locked(db):
            return out
        claimed = await claim(db, now=now)
    out["claimed"] = len(claimed)
    for reply_id, item in claimed:
        async with sessions() as db:
            lead = await db.get(Lead, item.lead_id)
            if lead is None:
                continue
            stopped = await service.opted_out(db, lead.id, item.channel)
            ready = await service.prepare(
                db, lead, item.channel, account_id=item.account_id, now=now
            )
        if stopped:
            result = service.Outcome("handoff", "opt_out")
        elif ready.last_in_id != item.message_id:
            result = service.Outcome("handoff", "unsure")  # a newer message is next
        else:
            result = await service.think(model, ready)
        tokens: list[str] = []
        async with sessions() as db, db.begin():
            lead = await db.get(Lead, item.lead_id, with_for_update=True)
            row = await db.get(LeadAiReply, reply_id, with_for_update=True)
            if lead is None or row is None:
                continue
            sent_id: UUID | None = None
            if result.outcome == "drafted" and result.draft:
                try:
                    message = await send_on_channel(db, client, lead, item, result.draft, now=now)
                except DeskError as error:
                    result = service.Outcome("failed", "window", completion=result.completion)
                    log.info("ai reply not sent: %s", error)
                else:
                    if getattr(message, "status", None) == "sent":
                        sent_id = message.id
                        result = service.Outcome(
                            "sent", None, draft=result.draft, completion=result.completion
                        )
                    else:
                        result = service.Outcome("failed", "failed", completion=result.completion)
            elif result.outcome == "opted_out":
                await service.record_stop(service.system_desk(db, lead, now), lead, item.channel)
            final = service.audit(ready, result, mode="auto", now=now, sent_message_id=sent_id)
            for name in (
                "outcome",
                "reason",
                "draft",
                "sent_message_id",
                "provider",
                "model",
                "input_tokens",
                "output_tokens",
                "cost_inr",
                "usage_ref",
            ):
                setattr(row, name, getattr(final, name))
            if result.outcome == "handoff":
                tokens = await service.owner_tokens(db, lead)
            key = {"sent": "sent", "handoff": "handoff", "opted_out": "stopped"}.get(
                result.outcome, "failed"
            )
            out[key] += 1
        if fcm is not None:
            for token in tokens:
                await fcm.send(client, token, service.handoff_alert(lead))
    async with sessions() as db, db.begin():
        out["erased"] = await service.erasure_sweep(db, now)
    return out


async def run(
    sessions: async_sessionmaker[AsyncSession], stop: asyncio.Event, *, first_delay: int = _TICK
) -> None:
    from ac_platform.lead_desk.ai_replies.registry import available, model_for

    with suppress(TimeoutError):
        await asyncio.wait_for(stop.wait(), timeout=first_delay)
    fcm_cfg = push.config()
    fcm = push.Fcm(fcm_cfg) if fcm_cfg is not None else None
    async with httpx.AsyncClient(timeout=15) as client:
        while not stop.is_set():
            try:
                # Nothing is claimed while the model can't run here (gate or key).
                if not available()[0]:
                    raise _Idle
                async with sessions() as db:
                    any_auto = await db.scalar(
                        select(text("1"))
                        .select_from(text("lead_desk_settings"))
                        .where(text("CAST(config AS JSONB) -> 'ai_replies' ->> 'mode' = 'auto'"))
                    )
                if any_auto:
                    await auto_pass(
                        sessions, model_for(sessions), client, fcm, now=datetime.now(UTC)
                    )
            except _Idle:
                pass
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
