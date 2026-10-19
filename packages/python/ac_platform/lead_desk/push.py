"""Phone alerts for the Lead Desk: a new lead for you, or a call that is due now.

The API sends Firebase Cloud Messaging (FCM) data messages to the seller's Sales
Xray Android app. A message carries no lead details, only the lead's id and how
many calls are waiting. The app then asks Sales Xray for the words to show, on
the seller's own session (``GET /v1/lead-desk/leads/{id}/alert``), so names and
numbers never pass through Google.

Each assignment and each due time alerts once (``Lead.alerted_assigned_at`` and
``Lead.alerted_due_at``). Several alerts for one seller in one pass become one
"3 leads to call now". Nothing older than two hours is sent, so a phone that
registers late is not flooded.

Off until the FCM settings exist (``AC_FCM_SERVICE_ACCOUNT`` and the app's client
settings ``AC_FCM_APP_ID``, ``AC_FCM_API_KEY``, ``AC_FCM_SENDER_ID``). They live in
Infisical, never in git.

A second run of the same loop sends gold review alerts to the same phones (``review_push``).
"""

from __future__ import annotations

import asyncio
import base64
import binascii
import json
import logging
import os
from collections import defaultdict
from collections.abc import AsyncIterator, Awaitable, Callable, Mapping, Sequence
from contextlib import asynccontextmanager, suppress
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Any, Literal
from uuid import UUID

import httpx
from fastapi import FastAPI
from sqlalchemy import and_, delete, exists, or_, select, text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from ac_platform.lead_desk import hours
from ac_platform.lead_desk.contracts import PushConfig
from ac_platform.lead_desk.models import Lead, LeadDevice
from ac_platform.lead_desk.store import LeadDesk, Viewer
from ac_platform.lead_desk.vocabulary import OPEN_STAGES

log = logging.getLogger(__name__)

SCOPE = "https://www.googleapis.com/auth/firebase.messaging"
WINDOW = timedelta(hours=2)
BATCH = 200
_TICK = 30
_LOCK = (1802, 1262)  # one sender across API processes and slots
_HOURS_TICK = 60
_HOURS_LOCK = (1802, 1263)  # one work-hours release across processes

Kind = Literal["new", "due"]


@dataclass(frozen=True, slots=True)
class FcmConfig:
    project_id: str
    service_account: dict[str, Any]
    app_id: str
    api_key: str
    sender_id: str


def _service_account(raw: str) -> dict[str, Any] | None:
    text_value = raw.strip()
    if not text_value:
        return None
    if not text_value.startswith("{"):
        try:
            text_value = base64.b64decode(text_value, validate=True).decode()
        except (binascii.Error, UnicodeDecodeError):
            return None
    try:
        value = json.loads(text_value)
    except json.JSONDecodeError:
        return None
    if not isinstance(value, dict) or value.get("type") != "service_account":
        return None
    if not all(isinstance(value.get(name), str) for name in ("project_id", "client_email")):
        return None
    return value


def config(env: Mapping[str, str] | None = None) -> FcmConfig | None:
    """The FCM settings, or None while any is missing (alerts stay off)."""
    env = os.environ if env is None else env
    account = _service_account(env.get("AC_FCM_SERVICE_ACCOUNT") or "")
    client = {
        name: (env.get(f"AC_FCM_{name.upper()}") or "").strip()
        for name in ("app_id", "api_key", "sender_id")
    }
    if account is None or not all(client.values()):
        return None
    return FcmConfig(
        project_id=str(account["project_id"]),
        service_account=account,
        app_id=client["app_id"],
        api_key=client["api_key"],
        sender_id=client["sender_id"],
    )


def client_config(cfg: FcmConfig | None) -> PushConfig:
    """What the app needs to start Firebase: public client settings, no secrets."""
    if cfg is None:
        return PushConfig(enabled=False)
    return PushConfig(
        enabled=True,
        project_id=cfg.project_id,
        app_id=cfg.app_id,
        api_key=cfg.api_key,
        sender_id=cfg.sender_id,
    )


class Fcm:
    """FCM HTTP v1 with a service account; one short-lived access token at a time."""

    def __init__(self, cfg: FcmConfig) -> None:
        from google.oauth2 import service_account

        self.cfg = cfg
        self._credentials = service_account.Credentials.from_service_account_info(  # type: ignore[no-untyped-call]
            cfg.service_account, scopes=[SCOPE]
        )
        self._lock = asyncio.Lock()

    async def _token(self) -> str:
        async with self._lock:
            if not self._credentials.valid:
                from google.auth.transport.requests import Request

                await asyncio.to_thread(self._credentials.refresh, Request())
            return str(self._credentials.token)

    async def send(
        self, client: httpx.AsyncClient, token: str, data: Mapping[str, str]
    ) -> Literal["sent", "gone", "failed"]:
        url = f"https://fcm.googleapis.com/v1/projects/{self.cfg.project_id}/messages:send"
        body = {
            "message": {
                "token": token,
                "data": dict(data),
                "android": {"priority": "HIGH", "ttl": "3600s"},
            }
        }
        try:
            response = await client.post(
                url,
                json=body,
                headers={"Authorization": f"Bearer {await self._token()}"},
                timeout=15,
            )
        except (httpx.HTTPError, OSError):
            return "failed"
        if response.status_code == 200:
            return "sent"
        if response.status_code == 404 or (
            response.status_code == 400 and "registration token" in response.text.lower()
        ):
            return "gone"
        log.warning("fcm send refused: %s", response.status_code)
        return "failed"


@dataclass(slots=True)
class Alert:
    tenant_id: UUID
    person_id: UUID
    leads: list[tuple[Kind, UUID]] = field(default_factory=list)
    to_call: int = 0
    tokens: list[str] = field(default_factory=list)

    def data(self) -> dict[str, str]:
        """The FCM data: ids and a count only, never a lead's name or number."""
        first_kind, first = self.leads[0]
        kind = first_kind if len(self.leads) == 1 else "many"
        return {
            "type": "lead_desk",
            "kind": kind,
            "lead": str(first),
            "tenant": str(self.tenant_id),
            "alerts": str(len(self.leads)),
            "count": str(self.to_call),
        }


def _has_device() -> Any:
    return exists().where(
        LeadDevice.tenant_id == Lead.tenant_id, LeadDevice.person_id == Lead.owner_person_id
    )


async def collect(database: AsyncSession, now: datetime) -> list[Alert]:
    """Finds the alerts to send now and marks them sent (the caller commits)."""
    since = now - WINDOW
    owned = and_(Lead.owner_person_id.is_not(None), Lead.stage.in_(OPEN_STAGES), _has_device())
    assigned = (
        await database.scalars(
            select(Lead)
            .where(
                owned,
                Lead.assigned_at > since,
                Lead.assigned_at <= now,
                or_(
                    Lead.alerted_assigned_at.is_(None),
                    Lead.alerted_assigned_at < Lead.assigned_at,
                ),
                # A lead someone added for themselves needs no alert.
                or_(
                    Lead.created_by_person_id.is_(None),
                    Lead.created_by_person_id != Lead.owner_person_id,
                ),
            )
            .order_by(Lead.assigned_at)
            .limit(BATCH)
            .with_for_update(skip_locked=True)
        )
    ).all()
    due = (
        await database.scalars(
            select(Lead)
            .where(
                owned,
                Lead.next_action_at > since,
                Lead.next_action_at <= now,
                or_(Lead.alerted_due_at.is_(None), Lead.alerted_due_at != Lead.next_action_at),
            )
            .order_by(Lead.next_action_at)
            .limit(BATCH)
            .with_for_update(skip_locked=True)
        )
    ).all()
    alerts: dict[tuple[UUID, UUID], Alert] = {}
    seen: set[UUID] = set()
    for kind, leads in (("new", assigned), ("due", due)):
        for lead in leads:
            if kind == "new":
                lead.alerted_assigned_at = lead.assigned_at
            # Marked either way: an assignment that is also due alerts once.
            if lead.next_action_at is not None and lead.next_action_at <= now:
                lead.alerted_due_at = lead.next_action_at
            if lead.id in seen or lead.owner_person_id is None:
                continue
            seen.add(lead.id)
            key = (lead.tenant_id, lead.owner_person_id)
            alert = alerts.setdefault(key, Alert(tenant_id=key[0], person_id=key[1]))
            alert.leads.append((kind, lead.id))  # type: ignore[arg-type]
    if not alerts:
        return []
    devices: dict[tuple[UUID, UUID], list[str]] = defaultdict(list)
    for tenant_id, person_id, token in (
        await database.execute(
            select(LeadDevice.tenant_id, LeadDevice.person_id, LeadDevice.token).where(
                or_(
                    *(
                        and_(LeadDevice.tenant_id == tenant, LeadDevice.person_id == person)
                        for tenant, person in alerts
                    )
                )
            )
        )
    ).tuples():
        devices[(tenant_id, person_id)].append(token)
    for key, alert in alerts.items():
        alert.tokens = devices.get(key, [])
        desk = LeadDesk(
            database, Viewer(person_id=key[1], tenant_id=key[0], role="member", name=""), now=now
        )
        alert.to_call = (await desk.badge()).to_call
    return [alert for alert in alerts.values() if alert.tokens]


async def send(
    alerts: Sequence[Alert], fcm: Fcm, client: httpx.AsyncClient
) -> tuple[int, list[str]]:
    """Sends each alert to each of its phones; returns how many went and the dead tokens."""
    sent = 0
    gone: list[str] = []
    for alert in alerts:
        data = alert.data()
        for token in alert.tokens:
            outcome = await fcm.send(client, token, data)
            sent += outcome == "sent"
            if outcome == "gone":
                gone.append(token)
    return sent, gone


async def tick(
    sessions: async_sessionmaker[AsyncSession],
    fcm: Fcm,
    client: httpx.AsyncClient,
    *,
    now: datetime | None = None,
) -> int:
    """One pass: collect and mark under a lock, commit, then send."""
    now = now or datetime.now(UTC)
    async with sessions() as database, database.begin():
        if not await database.scalar(
            text("SELECT pg_try_advisory_xact_lock(:a, :b)"), {"a": _LOCK[0], "b": _LOCK[1]}
        ):
            return 0
        alerts = await collect(database, now)
    if not alerts:
        return 0
    sent, gone = await send(alerts, fcm, client)
    if gone:
        from ac_platform.lead_desk.store import token_digest

        async with sessions() as database, database.begin():
            await database.execute(
                delete(LeadDevice).where(
                    LeadDevice.token_sha256.in_([token_digest(token) for token in gone])
                )
            )
    return sent


Pass = Callable[[async_sessionmaker[AsyncSession], Fcm, httpx.AsyncClient], Awaitable[int]]


async def run_push_sender(
    sessions: async_sessionmaker[AsyncSession],
    stop: asyncio.Event,
    *,
    first_delay: int = _TICK,
    send_pass: Pass = tick,
    what: str = "lead desk",
) -> None:
    """Every 30 seconds, send the alerts that are due. Does nothing until FCM is set up."""
    with suppress(TimeoutError):
        await asyncio.wait_for(stop.wait(), timeout=first_delay)
    fcm: Fcm | None = None
    async with httpx.AsyncClient() as client:
        while not stop.is_set():
            cfg = config()
            if cfg is not None:
                try:
                    if fcm is None or fcm.cfg != cfg:
                        fcm = Fcm(cfg)
                    sent = await send_pass(sessions, fcm, client)
                    if sent:
                        log.info("%s sent %d phone alerts", what, sent)
                except Exception:  # noqa: BLE001 - the loop must survive a bad tick
                    log.warning("%s alert tick failed", what)
            with suppress(TimeoutError):
                await asyncio.wait_for(stop.wait(), timeout=_TICK)


async def run_hours_release(
    sessions: async_sessionmaker[AsyncSession],
    stop: asyncio.Event,
    *,
    first_delay: int = _HOURS_TICK,
) -> None:
    """Every minute: leads that waited for work hours go out once work starts."""
    with suppress(TimeoutError):
        await asyncio.wait_for(stop.wait(), timeout=first_delay)
    while not stop.is_set():
        try:
            async with sessions() as database, database.begin():
                if await database.scalar(
                    text("SELECT pg_try_advisory_xact_lock(:a, :b)"),
                    {"a": _HOURS_LOCK[0], "b": _HOURS_LOCK[1]},
                ):
                    released = await hours.release_held(database, datetime.now(UTC))
                    if released:
                        log.info("lead desk gave out %d leads at the start of work", released)
        except Exception:  # noqa: BLE001 - the loop must survive a bad pass
            log.warning("lead desk work-hours release failed")
        with suppress(TimeoutError):
            await asyncio.wait_for(stop.wait(), timeout=_HOURS_TICK)


def attach(
    application: FastAPI, sessions: async_sessionmaker[AsyncSession], environment: str
) -> None:
    """Run the sender for the API's lifetime by wrapping the app's own lifespan."""
    if environment in {"local", "test"}:
        return
    from ac_platform.lead_desk import review_push

    inner = application.router.lifespan_context

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[Any]:
        async with inner(app) as state:
            stop = asyncio.Event()
            tasks = [
                asyncio.create_task(run_push_sender(sessions, stop), name="lead-desk-alerts"),
                asyncio.create_task(
                    run_push_sender(sessions, stop, send_pass=review_push.tick, what="gold review"),
                    name="gold-review-alerts",
                ),
                asyncio.create_task(run_hours_release(sessions, stop), name="lead-desk-hours"),
            ]
            try:
                yield state
            finally:
                stop.set()
                for task in tasks:
                    task.cancel()
                for task in tasks:
                    with suppress(asyncio.CancelledError):
                        await task

    application.router.lifespan_context = lifespan
