"""Lead stages back to Meta: the Conversions API for CRM.

An organisation that runs Meta lead ads picks (or creates) one of its own Meta
datasets in Sales Xray. From then on, each stage its Meta leads reach in the CRM goes
to that dataset, so Meta's ads learn which leads become customers and find more like
them. Settings are per organisation, in its Lead Desk settings (``meta_conversions``);
the token is the one from the organisation's last Continue with Meta, sealed
(``meta_connection``).

What goes to Meta, and nothing else:

- Only leads that came from a Meta lead form (source ``meta``, with Meta's lead id).
- One event per lead, dataset and stage name: Meta's lead id (unhashed, as Meta asks),
  and the email and phone as SHA-256 after Meta's normalising. No names, notes,
  cities, amounts or call details.
- Every Lead Desk stage maps to an event name the organisation can change or switch
  off. A funnel stage (New, Follow-up, Interested, Won) also sends the earlier funnel
  stages a lead skipped, because Meta wants every earlier stage before a later one.
- Meta refuses a whole request when any event is older than 7 days, so an event that
  could not go out within 7 days is dropped, never sent.

Each event is built once from Lead Desk's own history (captured, reopened, a call's
result) and frozen in ``lead_desk_meta_conversions``; every send adds a row to
``lead_desk_meta_conversion_attempts`` (the delivery log). Passing failures retry
with growing gaps; a lost connection or permission waits an hour and says so on the
page. Lead Desk's events stay the record of a lead's stage: nothing here is read
back as state. Bodies are emptied after 90 days.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import re
import time
from collections.abc import AsyncIterator, Mapping
from contextlib import asynccontextmanager, suppress
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any, Final
from uuid import UUID, uuid4

import httpx
import structlog
from fastapi import FastAPI
from sqlalchemy import and_, cast, func, or_, select, text
from sqlalchemy.dialects.postgresql import JSONB, insert
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from ac_platform.lead_desk.connectors import meta
from ac_platform.lead_desk.models import (
    Lead,
    LeadDeskSettings,
    LeadEvent,
    LeadMetaConversion,
    LeadMetaConversionAttempt,
)

log = logging.getLogger(__name__)
events_log = structlog.get_logger(__name__)  # stdlib info lines don't reach the journal

KEY: Final[str] = "meta_conversions"
CONNECTION: Final[str] = "meta_connection"
CRM_NAME: Final[str] = "Sales Xray"
STAGES: Final[tuple[str, ...]] = (
    "new",
    "not_connected",
    "follow_up",
    "interested",
    "won",
    "lost",
)
# The sales funnel, in order. Lost and Not connected sit beside it.
FUNNEL: Final[tuple[str, ...]] = ("new", "follow_up", "interested", "won")
DEFAULT_EVENTS: Final[dict[str, str | None]] = {
    "new": "Lead",
    "not_connected": None,
    "follow_up": "Follow-up",
    "interested": "Interested",
    "won": "Won",
    "lost": "Lost",
}
EVENT_NAME: Final[re.Pattern[str]] = re.compile(r"^[A-Za-z0-9][A-Za-z0-9 _.-]{0,49}$")
DATASET_ID: Final[re.Pattern[str]] = re.compile(r"^[0-9]{5,20}$")
META_LEAD_ID: Final[re.Pattern[str]] = re.compile(r"^[0-9]{15,17}$")
TEST_CODE: Final[re.Pattern[str]] = re.compile(r"^[A-Za-z0-9]{4,32}$")
# Meta takes events up to 7 days old; keep a margin for the request itself.
MAX_AGE: Final[timedelta] = timedelta(days=7) - timedelta(minutes=10)
# Read a Lead Desk event once it is surely committed (the pull files many in one go).
SETTLE: Final[timedelta] = timedelta(minutes=5)
KEEP: Final[timedelta] = timedelta(days=90)
MAX_ATTEMPTS: Final[int] = 20
WAIT_FOR_CUSTOMER: Final[timedelta] = timedelta(hours=1)
COLLECT_LIMIT: Final[int] = 500
SEND_LIMIT: Final[int] = 25
TIMEOUT: Final[float] = 10.0
_TICK = 60
_LOCK = (1802, 1265)  # one sender across API processes and slots
# Graph error codes worth trying again (Meta's error-handling guide).
_RETRY_CODES: Final[frozenset[int]] = frozenset({1, 2, 4, 17, 32, 341, 368, 613})


class ConversionsError(ValueError):
    """A setting the manager must fix; the message is shown as is."""


# ----- settings --------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class Settings:
    dataset_id: str
    dataset_name: str
    on: bool
    events: dict[str, str | None]
    test_code: str | None
    since: int
    cursor: tuple[datetime, UUID] | None


def read_settings(config: Mapping[str, Any]) -> Settings | None:
    """The organisation's choice, or None while no dataset was picked."""
    value = config.get(KEY)
    if not isinstance(value, Mapping) or not DATASET_ID.fullmatch(str(value.get("dataset_id"))):
        return None
    events = value.get("events")
    return Settings(
        dataset_id=str(value["dataset_id"]),
        dataset_name=str(value.get("dataset_name") or value["dataset_id"])[:120],
        on=value.get("on") is True,
        events=clean_events(events if isinstance(events, Mapping) else None),
        test_code=value["test_code"] if isinstance(value.get("test_code"), str) else None,
        since=int(value.get("since") or 0),
        cursor=_cursor(value.get("cursor")),
    )


def _cursor(value: Any) -> tuple[datetime, UUID] | None:
    """Where collecting got to: the last Lead Desk event read (time, id)."""
    if not isinstance(value, Mapping):
        return None
    try:
        return datetime.fromisoformat(str(value["at"])), UUID(str(value["id"]))
    except (KeyError, ValueError):
        return None


def clean_events(events: Mapping[str, Any] | None) -> dict[str, str | None]:
    """Every stage's event name (or None to send nothing), defaults filled in."""
    out = dict(DEFAULT_EVENTS)
    for stage, name in (events or {}).items():
        if stage not in out:
            raise ConversionsError("Pick names for the CRM's own stages only.")
        if name is None or (isinstance(name, str) and not name.strip()):
            out[stage] = None
            continue
        if not isinstance(name, str) or not EVENT_NAME.fullmatch(name.strip()):
            raise ConversionsError(
                "Use up to 50 letters, numbers, spaces, dots, dashes or underscores for "
                "each event name."
            )
        out[stage] = name.strip()
    names = [name for name in out.values() if name]
    if len(set(names)) != len(names):
        raise ConversionsError("Give each stage its own event name.")
    return out


def saved(
    config: Mapping[str, Any],
    *,
    dataset_id: str,
    dataset_name: str,
    on: bool,
    events: Mapping[str, Any] | None,
    test_code: str | None,
    now: int,
    by: UUID,
) -> dict[str, Any]:
    """The Lead Desk config with the organisation's new choice. Turning sending on, or
    picking another dataset, starts from now: earlier stages are never sent."""
    if not DATASET_ID.fullmatch(dataset_id):
        raise ConversionsError("Pick one of your Meta datasets.")
    if test_code is not None and not TEST_CODE.fullmatch(test_code):
        raise ConversionsError("Copy the test code from Meta Events Manager → Test events.")
    before = read_settings(config)
    fresh = before is None or before.dataset_id != dataset_id or (on and not before.on)
    return {
        **config,
        KEY: {
            "dataset_id": dataset_id,
            "dataset_name": dataset_name.strip()[:120] or dataset_id,
            "on": on,
            "events": clean_events(events),
            "test_code": test_code,
            "since": now if fresh or before is None else before.since,
            "cursor": None
            if fresh or before is None or before.cursor is None
            else {"at": before.cursor[0].isoformat(), "id": str(before.cursor[1])},
            "by": str(by),
            "at": now,
        },
    }


# ----- what one event says --------------------------------------------------------


def sha256(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()


def hashed_email(email: str | None) -> str | None:
    """Meta's rule: trimmed, lower case, then SHA-256."""
    value = (email or "").strip().lower()
    return sha256(value) if "@" in value else None


def hashed_phone(phone: str | None) -> str | None:
    """Meta's rule: digits only with the country code, no leading zeros, then SHA-256."""
    digits = re.sub(r"[^0-9]", "", phone or "").lstrip("0")
    return sha256(digits) if 8 <= len(digits) <= 15 else None


def event_id(meta_lead_id: str, event_name: str) -> str:
    """The same lead and stage always get the same id, so Meta keeps one copy."""
    return sha256(f"sales-xray:{meta_lead_id}:{event_name}")[:40]


def stages_reached(kind: str, data: Mapping[str, Any]) -> str | None:
    """The stage a Lead Desk event moves a lead to, or None when it moves nowhere."""
    if kind == "captured":
        return "new"
    if kind == "repeat" and data.get("reopened") is True:
        return "new"
    if kind == "result":
        stage, before = data.get("stage"), data.get("from_stage")
        if stage in STAGES and stage != before:
            return str(stage)
    return None


def with_earlier(stage: str) -> list[str]:
    """A funnel stage and every funnel stage before it; any other stage alone."""
    if stage in FUNNEL:
        return list(FUNNEL[: FUNNEL.index(stage) + 1])
    return [stage]


def event_body(
    *,
    meta_lead_id: str,
    email: str | None,
    phone: str | None,
    event_name: str,
    at: datetime,
) -> dict[str, Any]:
    """One Conversions API for CRM event: Meta's lead id and hashed identifiers only."""
    user: dict[str, Any] = {"lead_id": int(meta_lead_id)}
    em, ph = hashed_email(email), hashed_phone(phone)
    if em:
        user["em"] = [em]
    if ph:
        user["ph"] = [ph]
    return {
        "event_name": event_name,
        "event_time": int(at.timestamp()),
        "event_id": event_id(meta_lead_id, event_name),
        "action_source": "system_generated",
        "user_data": user,
        "custom_data": {"event_source": "crm", "lead_event_source": CRM_NAME},
    }


def digest(body: Mapping[str, Any]) -> str:
    return sha256(json.dumps(body, sort_keys=True, separators=(",", ":")))


# ----- Meta's answer ----------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class Answer:
    """What one send came to: delivered, try again (when), or rejected for good."""

    http_status: int | None
    error_code: str | None
    duration_ms: int
    events_received: int | None = None
    fbtrace_id: str | None = None
    wait: str = "retry"  # retry | customer | never

    @property
    def delivered(self) -> bool:
        return self.error_code is None


def read_answer(status: int, body: Any, duration_ms: int) -> Answer:
    data = body if isinstance(body, Mapping) else {}
    trace = data.get("fbtrace_id")
    error = data.get("error") if isinstance(data.get("error"), Mapping) else None
    if error is not None:
        trace = error.get("fbtrace_id") or trace
    trace = str(trace)[:64] if trace else None
    received = data.get("events_received")
    if status == 200 and error is None and isinstance(received, int) and received >= 1:
        return Answer(status, None, duration_ms, received, trace)
    code = error.get("code") if error is not None else None
    code = code if isinstance(code, int) and not isinstance(code, bool) else None
    name = f"meta_{code}" if code is not None else f"http_{status}"
    if (
        status >= 500
        or status == 429
        or (code is not None and (code in _RETRY_CODES or 80000 <= code < 81000))
    ):
        return Answer(status, name, duration_ms, None, trace, "retry")
    if code in (190, 102) or code in (10, 3) or (code is not None and 200 <= code < 300):
        return Answer(status, name, duration_ms, None, trace, "customer")
    if status == 200:
        return Answer(status, "not_received", duration_ms, received, trace, "retry")
    return Answer(status, name, duration_ms, None, trace, "never")


async def post_event(
    client: httpx.AsyncClient,
    cfg: meta.MetaConfig,
    *,
    dataset_id: str,
    token: str,
    body: Mapping[str, Any],
    test_code: str | None,
) -> Answer:
    """One event to the dataset. Never logs the token or the body."""
    started = time.monotonic()

    def elapsed() -> int:
        return max(0, round((time.monotonic() - started) * 1000))

    form = {"data": json.dumps([body], separators=(",", ":")), "access_token": token}
    if test_code:
        form["test_event_code"] = test_code
    try:
        response = await client.post(f"{cfg.graph}/{dataset_id}/events", data=form, timeout=TIMEOUT)
    except httpx.TimeoutException:
        return Answer(None, "timeout", elapsed())
    except httpx.HTTPError:
        return Answer(None, "connect_error", elapsed())
    try:
        answer = response.json()
    except ValueError:
        answer = {}
    return read_answer(int(response.status_code), answer, elapsed())


def retry_delay(failures: int) -> timedelta:
    return timedelta(seconds=min(3600, 30 * 2 ** max(0, failures - 1)))


# ----- collecting: Lead Desk history to frozen events ------------------------------


def _settings_on() -> Any:
    flag = func.jsonb_extract_path_text(cast(LeadDeskSettings.config, JSONB), KEY, "on")
    return flag == "true"


async def collect(
    sessions: async_sessionmaker[AsyncSession], *, environment: str, now: datetime
) -> int:
    """Freeze the events for new stage changes of every organisation that sends."""
    made = 0
    async with sessions() as db, db.begin():
        rows = (
            await db.scalars(
                select(LeadDeskSettings).where(_settings_on()).with_for_update(skip_locked=True)
            )
        ).all()
        for row in rows:
            settings = read_settings(row.config or {})
            if settings is None or not settings.on:
                continue
            made += await _collect_one(db, row, settings, environment=environment, now=now)
    return made


async def _collect_one(
    db: AsyncSession,
    row: LeadDeskSettings,
    settings: Settings,
    *,
    environment: str,
    now: datetime,
) -> int:
    floor = max(datetime.fromtimestamp(settings.since, UTC), now - MAX_AGE)
    query = (
        select(LeadEvent, Lead)
        .join(Lead, and_(Lead.tenant_id == LeadEvent.tenant_id, Lead.id == LeadEvent.lead_id))
        .where(
            LeadEvent.tenant_id == row.tenant_id,
            LeadEvent.kind.in_(("captured", "repeat", "result")),
            LeadEvent.created_at >= floor,
            LeadEvent.created_at <= now - SETTLE,
            Lead.source == "meta",
            Lead.source_ref.is_not(None),
        )
        .order_by(LeadEvent.created_at, LeadEvent.id)
        .limit(COLLECT_LIMIT)
    )
    if settings.cursor is not None:
        at, after = settings.cursor
        query = query.where(
            or_(LeadEvent.created_at > at, and_(LeadEvent.created_at == at, LeadEvent.id > after))
        )
    if environment == "production":
        query = query.where(Lead.test_data.is_(False))
    made = 0
    last: tuple[datetime, UUID] | None = None
    for event, lead in (await db.execute(query)).tuples():
        last = (event.created_at, event.id)
        reached = stages_reached(event.kind, event.data if isinstance(event.data, dict) else {})
        meta_lead_id = str(lead.source_ref or "")
        if reached is None or not META_LEAD_ID.fullmatch(meta_lead_id):
            continue
        for stage in with_earlier(reached):
            name = settings.events.get(stage)
            if not name:
                continue
            body = event_body(
                meta_lead_id=meta_lead_id,
                email=lead.email,
                phone=lead.phone,
                event_name=name,
                at=event.created_at,
            )
            inserted = await db.execute(
                insert(LeadMetaConversion)
                .values(
                    id=uuid4(),
                    tenant_id=row.tenant_id,
                    lead_id=lead.id,
                    source_event_id=event.id,
                    dataset_id=settings.dataset_id,
                    stage=stage,
                    event_name=name,
                    event_time=event.created_at,
                    payload=body,
                    payload_sha256=digest(body),
                    status="pending",
                    attempts=0,
                    next_attempt_at=now,
                    created_at=now,
                )
                .on_conflict_do_nothing(
                    index_elements=["tenant_id", "dataset_id", "lead_id", "event_name"]
                )
                .returning(LeadMetaConversion.id)
            )
            made += inserted.first() is not None
    if last is not None:
        config = dict(row.config or {})
        config[KEY] = {**config[KEY], "cursor": {"at": last[0].isoformat(), "id": str(last[1])}}
        row.config = config
    return made


# ----- sending ------------------------------------------------------------------------


def connection_token(
    config: Mapping[str, Any], cfg: meta.MetaConfig, tenant_id: UUID
) -> str | None:
    """The organisation's sealed Meta token from its last Continue with Meta."""
    box = config.get(CONNECTION)
    if not isinstance(box, Mapping) or not isinstance(box.get("token"), Mapping):
        return None
    try:
        return meta.unseal(cfg.token_key, box["token"], page_id=connection_bound(tenant_id))
    except meta.MetaError:
        return None


def connection_bound(tenant_id: UUID) -> str:
    """What a connection token is sealed to: it can't be moved to another organisation."""
    return f"organisation:{tenant_id}"


async def deliver(
    db: AsyncSession,
    client: httpx.AsyncClient,
    cfg: meta.MetaConfig,
    *,
    now: datetime,
    limit: int = SEND_LIMIT,
    clock: Any = None,
) -> list[dict[str, Any]]:
    """Send the events that are due, oldest first, in the caller's transaction."""
    clock = clock or (lambda: datetime.now(UTC))
    due = (
        await db.scalars(
            select(LeadMetaConversion)
            .where(
                LeadMetaConversion.status == "pending", LeadMetaConversion.next_attempt_at <= now
            )
            .order_by(LeadMetaConversion.next_attempt_at, LeadMetaConversion.event_time)
            .limit(limit)
            .with_for_update(skip_locked=True)
        )
    ).all()
    lines: list[dict[str, Any]] = []
    configs: dict[UUID, dict[str, Any]] = {}
    for row in due:
        if row.tenant_id not in configs:
            settings_row = await db.get(LeadDeskSettings, row.tenant_id)
            configs[row.tenant_id] = dict(settings_row.config or {}) if settings_row else {}
        config = configs[row.tenant_id]
        settings = read_settings(config)
        line: dict[str, Any] = {"conversion": str(row.id)[:8], "stage": row.stage}
        lines.append(line)
        if settings is None or not settings.on or settings.dataset_id != row.dataset_id:
            _drop(row, "switched_off", now)
            line["dropped"] = "switched_off"
            continue
        if row.event_time < now - MAX_AGE:
            _drop(row, "too_old", now)
            line["dropped"] = "too_old"
            continue
        lead = await db.get(Lead, row.lead_id)
        if lead is None or lead.tenant_id != row.tenant_id or row.payload is None:
            _drop(row, "lead_gone", now)
            line["dropped"] = "lead_gone"
            continue
        if digest(row.payload) != row.payload_sha256:
            answer = Answer(None, "payload_integrity", 0, wait="never")
        else:
            token = connection_token(config, cfg, row.tenant_id)
            if token is None:
                answer = Answer(None, "not_connected", 0, wait="customer")
            else:
                started = clock()
                answer = await post_event(
                    client,
                    cfg,
                    dataset_id=row.dataset_id,
                    token=token,
                    body=row.payload,
                    test_code=settings.test_code,
                )
                await _record(db, row, answer, started, clock())
                line.update(status=row.status, http_status=answer.http_status)
                if answer.error_code:
                    line["error"] = answer.error_code
                continue
        await _record(db, row, answer, now, now)
        line.update(status=row.status, error=answer.error_code)
    return lines


def _drop(row: LeadMetaConversion, reason: str, now: datetime) -> None:
    row.status = "dropped"
    row.last_error_code = reason
    row.payload = None
    row.erased_at = now


async def _record(
    db: AsyncSession, row: LeadMetaConversion, answer: Answer, started: datetime, finished: datetime
) -> None:
    attempt = row.attempts + 1
    await db.execute(
        insert(LeadMetaConversionAttempt)
        .values(
            conversion_id=row.id,
            attempt=attempt,
            started_at=started,
            finished_at=max(finished, started),
            http_status=answer.http_status,
            error_code=answer.error_code,
            events_received=answer.events_received,
            fbtrace_id=answer.fbtrace_id,
            duration_ms=answer.duration_ms,
        )
        .on_conflict_do_nothing(index_elements=["conversion_id", "attempt"])
    )
    row.attempts = attempt
    row.last_http_status = answer.http_status
    row.last_error_code = answer.error_code
    row.fbtrace_id = answer.fbtrace_id or row.fbtrace_id
    if answer.delivered:
        row.status = "delivered"
        row.delivered_at = finished
    elif answer.wait == "never":
        row.status = "rejected"
    elif answer.wait == "customer":
        # Only the customer can fix it (connect again, allow a permission): wait, and
        # let the 7-day limit drop what can no longer go.
        row.next_attempt_at = finished + WAIT_FOR_CUSTOMER
    elif attempt >= MAX_ATTEMPTS:
        row.status = "dead_letter"
    else:
        row.next_attempt_at = finished + retry_delay(attempt)


async def retry(db: AsyncSession, tenant_id: UUID, conversion_id: UUID, now: datetime) -> bool:
    """A manager's "Try again" on an event Meta refused for good, while it is fresh."""
    row = await db.scalar(
        select(LeadMetaConversion)
        .where(LeadMetaConversion.id == conversion_id, LeadMetaConversion.tenant_id == tenant_id)
        .with_for_update()
    )
    if row is None or row.status not in ("rejected", "dead_letter") or row.payload is None:
        return False
    if row.event_time < now - MAX_AGE:
        _drop(row, "too_old", now)
        return False
    row.status = "pending"
    row.next_attempt_at = now
    return True


_SWEEP = """
    UPDATE lead_desk_meta_conversions SET payload = NULL, erased_at = :now
    WHERE id IN (
      SELECT id FROM lead_desk_meta_conversions
      WHERE payload IS NOT NULL AND status IN ('delivered', 'rejected', 'dead_letter')
        AND created_at < :before
      ORDER BY created_at LIMIT 500
    )
"""


# A lead that is no longer in Lead Desk takes its hashed identifiers with it, whatever
# the event's state: a waiting one is dropped, a sent one keeps only its id and result.
_GONE = """
    UPDATE lead_desk_meta_conversions c
    SET payload = NULL, erased_at = :now,
        status = CASE WHEN c.status = 'pending' THEN 'dropped' ELSE c.status END,
        last_error_code = CASE WHEN c.status = 'pending' THEN 'lead_gone'
                               ELSE c.last_error_code END
    WHERE c.id IN (
      SELECT x.id FROM lead_desk_meta_conversions x
      WHERE x.payload IS NOT NULL
        AND NOT EXISTS (
          SELECT 1 FROM lead_desk_leads l WHERE l.tenant_id = x.tenant_id AND l.id = x.lead_id
        )
      LIMIT 500
    )
"""


async def erasure_sweep(db: AsyncSession, now: datetime) -> int:
    """Empty event bodies older than 90 days, and at once those of a lead that is gone;
    ids, digests, results and attempts stay."""
    old = await db.execute(text(_SWEEP), {"now": now, "before": now - KEEP})
    gone = await db.execute(text(_GONE), {"now": now})
    return int(getattr(old, "rowcount", 0) or 0) + int(getattr(gone, "rowcount", 0) or 0)


async def tick(
    sessions: async_sessionmaker[AsyncSession],
    cfg: meta.MetaConfig,
    client: httpx.AsyncClient,
    *,
    environment: str,
    now: datetime | None = None,
) -> dict[str, int]:
    """Collect new stage changes, send what is due, empty old bodies; one runner at a time."""
    now = now or datetime.now(UTC)
    made = await collect(sessions, environment=environment, now=now)
    async with sessions() as db, db.begin():
        if not await db.scalar(
            text("SELECT pg_try_advisory_xact_lock(:a, :b)"), {"a": _LOCK[0], "b": _LOCK[1]}
        ):
            return {"made": made, "sent": 0}
        lines = await deliver(db, client, cfg, now=now)
        swept = await erasure_sweep(db, now)
    delivered = sum(1 for line in lines if line.get("status") == "delivered")
    if lines:
        events_log.info(
            "lead_desk_meta_conversions", made=made, tried=len(lines), delivered=delivered
        )
    return {"made": made, "sent": len(lines), "delivered": delivered, "swept": swept}


async def run_sender(
    sessions: async_sessionmaker[AsyncSession],
    stop: asyncio.Event,
    *,
    environment: str,
    first_delay: int = _TICK,
) -> None:
    """Every minute, while Meta is set up, send lead stages. Survives a bad tick."""
    with suppress(TimeoutError):
        await asyncio.wait_for(stop.wait(), timeout=first_delay)
    async with httpx.AsyncClient(timeout=TIMEOUT) as client:
        while not stop.is_set():
            cfg = meta.config()
            if cfg is not None:
                try:
                    await tick(sessions, cfg, client, environment=environment)
                except Exception:  # noqa: BLE001 - the loop must survive a bad tick
                    log.warning("meta conversions tick failed", exc_info=True)
            with suppress(TimeoutError):
                await asyncio.wait_for(stop.wait(), timeout=_TICK)


def attach(
    application: FastAPI, sessions: async_sessionmaker[AsyncSession], environment: str
) -> None:
    """Run the sender for the API's lifetime by wrapping the app's own lifespan."""
    if environment in {"local", "test"}:
        return
    inner = application.router.lifespan_context

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[Any]:
        async with inner(app) as state:
            stop = asyncio.Event()
            task = asyncio.create_task(
                run_sender(sessions, stop, environment=environment), name="meta-conversions"
            )
            try:
                yield state
            finally:
                stop.set()
                task.cancel()
                with suppress(asyncio.CancelledError):
                    await task

    application.router.lifespan_context = lifespan


# ----- what the page shows ------------------------------------------------------------


async def settling(
    db: AsyncSession, tenant_id: UUID, settings: Settings, now: datetime
) -> tuple[int, datetime | None]:
    """The stages that will go to Meta once their stage changes settle (5 minutes, in case
    the seller changes it back), and when the first goes."""
    floor = max(datetime.fromtimestamp(settings.since, UTC), now - MAX_AGE)
    query = (
        select(LeadEvent.kind, LeadEvent.data, LeadEvent.created_at, Lead.id, Lead.source_ref)
        .join(Lead, and_(Lead.tenant_id == LeadEvent.tenant_id, Lead.id == LeadEvent.lead_id))
        .where(
            LeadEvent.tenant_id == tenant_id,
            LeadEvent.kind.in_(("captured", "repeat", "result")),
            LeadEvent.created_at >= floor,
            Lead.source == "meta",
            Lead.source_ref.is_not(None),
        )
        .order_by(LeadEvent.created_at, LeadEvent.id)
        .limit(COLLECT_LIMIT)
    )
    if settings.cursor is not None:
        at, after = settings.cursor
        query = query.where(
            or_(LeadEvent.created_at > at, and_(LeadEvent.created_at == at, LeadEvent.id > after))
        )
    pairs: dict[tuple[UUID, str], datetime] = {}
    for kind, data, at, lead_id, ref in (await db.execute(query)).tuples():
        reached = stages_reached(kind, data if isinstance(data, dict) else {})
        if reached is None or not META_LEAD_ID.fullmatch(str(ref or "")):
            continue
        for stage in with_earlier(reached):
            name = settings.events.get(stage)
            if name:
                pairs.setdefault((lead_id, name), at)
    if pairs:
        made = (
            await db.execute(
                select(LeadMetaConversion.lead_id, LeadMetaConversion.event_name).where(
                    LeadMetaConversion.tenant_id == tenant_id,
                    LeadMetaConversion.dataset_id == settings.dataset_id,
                    LeadMetaConversion.lead_id.in_({lead for lead, _ in pairs}),
                )
            )
        ).tuples()
        for done in made:
            pairs.pop((done[0], done[1]), None)
    first = min(pairs.values(), default=None)
    return len(pairs), first + SETTLE if first is not None else None


async def summary(
    db: AsyncSession, tenant_id: UUID, now: datetime, settings: Settings | None = None
) -> dict[str, Any]:
    """Counts for the last 7 days, the last delivery, the 20 newest events, and what is
    still settling before it goes."""
    week = now - timedelta(days=7)
    counts = {
        status: int(count)
        for status, count in (
            await db.execute(
                select(LeadMetaConversion.status, func.count())
                .where(
                    LeadMetaConversion.tenant_id == tenant_id,
                    LeadMetaConversion.created_at >= week,
                )
                .group_by(LeadMetaConversion.status)
            )
        ).tuples()
    }
    last = await db.scalar(
        select(func.max(LeadMetaConversion.delivered_at)).where(
            LeadMetaConversion.tenant_id == tenant_id
        )
    )
    recent = (
        await db.execute(
            select(LeadMetaConversion, Lead.name)
            .join(
                Lead,
                and_(
                    Lead.tenant_id == LeadMetaConversion.tenant_id,
                    Lead.id == LeadMetaConversion.lead_id,
                ),
            )
            .where(LeadMetaConversion.tenant_id == tenant_id)
            .order_by(LeadMetaConversion.created_at.desc(), LeadMetaConversion.event_time.desc())
            .limit(20)
        )
    ).tuples()
    waiting = await db.scalar(
        select(LeadMetaConversion.last_error_code)
        .where(
            LeadMetaConversion.tenant_id == tenant_id,
            LeadMetaConversion.status == "pending",
            LeadMetaConversion.attempts > 0,
        )
        .order_by(LeadMetaConversion.next_attempt_at.desc())
        .limit(1)
    )
    waits, sends_at = (
        await settling(db, tenant_id, settings, now)
        if settings is not None and settings.on
        else (0, None)
    )
    return {
        "counts": counts,
        "last_delivered_at": last,
        "waiting_on": waiting,
        "settling": waits,
        "sends_at": sends_at,
        "recent": [
            {
                "id": row.id,
                "lead_id": row.lead_id,
                "lead_name": name,
                "stage": row.stage,
                "event_name": row.event_name,
                "status": row.status,
                "attempts": row.attempts,
                "event_time": row.event_time,
                "delivered_at": row.delivered_at,
                "error": row.last_error_code,
            }
            for row, name in recent
        ],
    }
