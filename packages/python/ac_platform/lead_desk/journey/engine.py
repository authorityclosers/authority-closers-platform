"""The lead-stage engine: a business's stage changes, told to every ad platform it set up.

Built from the Meta-only sender (0104) and keeping its rules for every platform:

- **Collect.** Every minute, for each organisation with a platform switched on, read
  Lead Desk's new history (a lead captured or reopened, a call's result, a stage set
  by hand) once it has settled for 5 minutes, in case the seller changes it back.
  Each stage reached also brings the funnel stages a lead skipped, because platforms
  learn best from the whole way. Each confirmed match becomes one frozen event in
  ``lead_desk_conversions`` (one per lead, platform, destination and name).
- **Send.** Oldest first, one try at a time, each try a row in
  ``lead_desk_conversion_attempts``. Passing failures retry with growing gaps (30 s to
  an hour, 20 tries); a lost connection or permission waits an hour and the page says
  what to do; an event too old for the platform is dropped, never sent.
- **Forget.** Event bodies are emptied after 90 days, and at once when the lead is gone.

Lead Desk's own history stays the record of a lead's stage: nothing a platform says is
read back as state.
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import AsyncIterator, Mapping
from contextlib import asynccontextmanager, suppress
from datetime import UTC, datetime, timedelta
from typing import Any, Final
from uuid import UUID, uuid4

import httpx
import structlog
from fastapi import FastAPI
from sqlalchemy import and_, cast, func, or_, select, text
from sqlalchemy.dialects.postgresql import JSONB, insert
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from ac_platform.lead_desk.journey import mapping
from ac_platform.lead_desk.journey import model as journeys
from ac_platform.lead_desk.journey.model import Journey
from ac_platform.lead_desk.journey.providers import Answer, digest
from ac_platform.lead_desk.models import (
    Lead,
    LeadConversion,
    LeadConversionAttempt,
    LeadDeskSettings,
    LeadEvent,
)

log = logging.getLogger(__name__)
events_log = structlog.get_logger(__name__)  # stdlib info lines don't reach the journal

# Platforms take events up to 7 days old (Meta's limit, the tightest); keep a margin.
MAX_AGE: Final[timedelta] = timedelta(days=7) - timedelta(minutes=10)
SETTLE: Final[timedelta] = timedelta(minutes=5)
KEEP: Final[timedelta] = timedelta(days=90)
MAX_ATTEMPTS: Final[int] = 20
WAIT_FOR_CUSTOMER: Final[timedelta] = timedelta(hours=1)
COLLECT_LIMIT: Final[int] = 500
SEND_LIMIT: Final[int] = 25
TIMEOUT: Final[float] = 10.0
_TICK = 60
# One sender across API processes and slots. The Meta-only sender's lock (1265): this
# engine replaces it, so the two never run side by side.
LOCK: Final[tuple[int, int]] = (1802, 1265)
KINDS: Final[tuple[str, ...]] = ("captured", "repeat", "result", "stage")


def retry_delay(failures: int) -> timedelta:
    return timedelta(seconds=min(3600, 30 * 2 ** max(0, failures - 1)))


def reached(journey: Journey, kind: str, data: Mapping[str, Any]) -> str | None:
    """The business's stage a Lead Desk event moves a lead to, or None."""
    if kind == "captured" or (kind == "repeat" and data.get("reopened") is True):
        stage = journey.resolve("new", None)
        return stage.key if stage else None
    if kind not in ("result", "stage"):
        return None
    step = data.get("step") if isinstance(data.get("step"), str) else None
    desk = data.get("stage") if isinstance(data.get("stage"), str) else None
    if kind == "result" and step is None and desk == data.get("from_stage"):
        return None
    if kind == "stage" and step is None:
        return None
    if step is not None and step == data.get("from_step") and desk == data.get("from_stage"):
        return None
    stage = journey.resolve(desk or "", step)
    return stage.key if stage else None


# ----- collecting -----------------------------------------------------------------------


def _with_meta_on() -> Any:
    """Organisations whose Lead Desk settings may have a platform on (cheap prefilter)."""
    config = cast(LeadDeskSettings.config, JSONB)
    return or_(
        config.has_key(mapping.KEY),
        func.jsonb_extract_path_text(config, mapping.LEGACY_META, "on") == "true",
    )


async def collect(
    sessions: async_sessionmaker[AsyncSession], *, environment: str, now: datetime
) -> int:
    made = 0
    async with sessions() as db, db.begin():
        rows = (
            await db.scalars(
                select(LeadDeskSettings).where(_with_meta_on()).with_for_update(skip_locked=True)
            )
        ).all()
        for row in rows:
            config = dict(row.config or {})
            if not mapping.any_on(config):
                continue
            config = await adopt_meta(db, row.tenant_id, config, now)
            journey = await journeys.read(db, row.tenant_id)
            made_now, config = await _collect_one(
                db, row.tenant_id, config, journey, environment=environment, now=now
            )
            made += made_now
            if config != (row.config or {}):
                row.config = config
    return made


async def _collect_one(
    db: AsyncSession,
    tenant_id: UUID,
    config: dict[str, Any],
    journey: Journey,
    *,
    environment: str,
    now: datetime,
) -> tuple[int, dict[str, Any]]:
    targets = [
        (provider, mapping.read(config, provider), mapping.module(provider))
        for provider in mapping.available()
    ]
    targets = [item for item in targets if item[1].ready]
    if not targets:
        return 0, config
    earliest = min(datetime.fromtimestamp(settings.since, UTC) for _, settings, _ in targets)
    floor = max(earliest, now - MAX_AGE)
    query = (
        select(LeadEvent, Lead)
        .join(Lead, and_(Lead.tenant_id == LeadEvent.tenant_id, Lead.id == LeadEvent.lead_id))
        .where(
            LeadEvent.tenant_id == tenant_id,
            LeadEvent.kind.in_(KINDS),
            LeadEvent.created_at >= floor,
            LeadEvent.created_at <= now - SETTLE,
        )
        .order_by(LeadEvent.created_at, LeadEvent.id)
        .limit(COLLECT_LIMIT)
    )
    position = mapping.cursor(config)
    if position is not None:
        at, after = position
        query = query.where(
            or_(LeadEvent.created_at > at, and_(LeadEvent.created_at == at, LeadEvent.id > after))
        )
    if environment == "production":
        query = query.where(Lead.test_data.is_(False))
    made = 0
    last: tuple[datetime, UUID] | None = None
    for event, lead in (await db.execute(query)).tuples():
        last = (event.created_at, event.id)
        data = event.data if isinstance(event.data, dict) else {}
        # Ad platforms learn from the main pipeline's stages (its matches are the ones
        # saved); a lead moving between pipelines reached no stage.
        if journeys.pipeline_of(lead) != journey.pipeline or "pipeline" in data:
            continue
        key = reached(journey, event.kind, data)
        if key is None:
            continue
        for provider, settings, adapter in targets:
            if event.created_at < datetime.fromtimestamp(settings.since, UTC):
                continue
            who = adapter.identity(lead)
            if who is None:
                continue
            for stage_key in journey.with_earlier(key):
                name = settings.events.get(stage_key)
                if not name:
                    continue
                payload = adapter.body(who, event_name=name, at=event.created_at, settings=settings)
                inserted = await db.execute(
                    insert(LeadConversion)
                    .values(
                        id=uuid4(),
                        tenant_id=tenant_id,
                        lead_id=lead.id,
                        source_event_id=event.id,
                        provider=provider,
                        destination=settings.destination_id,
                        stage_key=stage_key,
                        event_name=name,
                        event_time=event.created_at,
                        payload=payload,
                        payload_sha256=digest(payload),
                        status="pending",
                        attempts=0,
                        next_attempt_at=now,
                        test=bool(settings.test_code) or lead.test_data,
                        created_at=now,
                    )
                    .on_conflict_do_nothing(
                        index_elements=[
                            "tenant_id",
                            "provider",
                            "destination",
                            "lead_id",
                            "event_name",
                        ]
                    )
                    .returning(LeadConversion.id)
                )
                made += inserted.first() is not None
    if last is not None:
        config = mapping.with_cursor(config, last[0], last[1])
    return made, config


_ADOPT = """
    INSERT INTO lead_desk_conversions (id, tenant_id, lead_id, source_event_id, provider,
        destination, stage_key, event_name, event_time, payload, payload_sha256, status,
        attempts, next_attempt_at, delivered_at, last_http_status, last_error_code, trace_id,
        test, created_at, erased_at)
    SELECT id, tenant_id, lead_id, source_event_id, 'meta', dataset_id, stage, event_name,
        event_time, payload, payload_sha256, status, attempts, next_attempt_at, delivered_at,
        last_http_status, last_error_code, fbtrace_id, false, created_at, erased_at
    FROM lead_desk_meta_conversions WHERE tenant_id = :tenant
    ON CONFLICT DO NOTHING
"""
_ADOPT_ATTEMPTS = """
    INSERT INTO lead_desk_conversion_attempts (conversion_id, attempt, started_at, finished_at,
        http_status, error_code, trace_id, duration_ms)
    SELECT a.conversion_id, a.attempt, a.started_at, a.finished_at, a.http_status, a.error_code,
        a.fbtrace_id, a.duration_ms
    FROM lead_desk_meta_conversion_attempts a
    JOIN lead_desk_conversions c ON c.id = a.conversion_id AND c.tenant_id = :tenant
    ON CONFLICT DO NOTHING
"""
# The Meta-only sender's waiting events now wait here; there they are marked as moved.
_MOVED = """
    UPDATE lead_desk_meta_conversions SET status = 'dropped', last_error_code = 'moved',
        payload = NULL, erased_at = :now
    WHERE tenant_id = :tenant AND status = 'pending'
"""


async def adopt_meta(
    db: AsyncSession, tenant_id: UUID, config: dict[str, Any], now: datetime
) -> dict[str, Any]:
    """Once per organisation: the Meta-only sender's events and settings move here."""
    box = config.get(mapping.KEY)
    if isinstance(box, Mapping) and box.get("adopted_meta") is True:
        return config
    if isinstance(config.get(mapping.LEGACY_META), Mapping):
        await db.execute(text(_ADOPT), {"tenant": tenant_id})
        await db.execute(text(_ADOPT_ATTEMPTS), {"tenant": tenant_id})
        await db.execute(text(_MOVED), {"tenant": tenant_id, "now": now})
        settings = mapping.read(config, "meta")
        if settings.destination_id:
            config = mapping.destination_saved(
                config,
                "meta",
                destination_id=settings.destination_id,
                destination_name=settings.destination_name or settings.destination_id,
                on=settings.on,
                test_code=settings.test_code,
                now=settings.since or mapping.epoch(now),
            )
    out = dict(config)
    box = dict(out.get(mapping.KEY) or {}) if isinstance(out.get(mapping.KEY), Mapping) else {}
    box["adopted_meta"] = True
    out[mapping.KEY] = box
    return out


# ----- sending ----------------------------------------------------------------------------


async def deliver(
    db: AsyncSession,
    client: httpx.AsyncClient,
    *,
    now: datetime,
    limit: int = SEND_LIMIT,
    clock: Any = None,
) -> list[dict[str, Any]]:
    """Send the events that are due, oldest first, in the caller's transaction."""
    clock = clock or (lambda: datetime.now(UTC))
    due = (
        await db.scalars(
            select(LeadConversion)
            .where(LeadConversion.status == "pending", LeadConversion.next_attempt_at <= now)
            .order_by(LeadConversion.next_attempt_at, LeadConversion.event_time)
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
        line: dict[str, Any] = {"conversion": str(row.id)[:8], "provider": row.provider}
        lines.append(line)
        if row.provider not in mapping.MODULES:
            _drop(row, "not_available", now)
            line["dropped"] = "not_available"
            continue
        settings = mapping.read(config, row.provider)
        if not settings.on or settings.destination_id != row.destination:
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
            await _record(db, row, Answer(None, "payload_integrity", 0, wait="never"), now, now)
            line.update(status=row.status, error="payload_integrity")
            continue
        started = clock()
        answer = await mapping.module(row.provider).send(
            client,
            config=config,
            tenant_id=row.tenant_id,
            destination=row.destination,
            payload=row.payload,
            test_code=settings.test_code,
            db=db,
        )
        await _record(db, row, answer, started, clock())
        line.update(status=row.status, http_status=answer.http_status)
        if answer.error_code:
            line["error"] = answer.error_code
    return lines


def _drop(row: LeadConversion, reason: str, now: datetime) -> None:
    row.status = "dropped"
    row.last_error_code = reason
    row.payload = None
    row.erased_at = now


async def _record(
    db: AsyncSession, row: LeadConversion, answer: Answer, started: datetime, finished: datetime
) -> None:
    attempt = row.attempts + 1
    await db.execute(
        insert(LeadConversionAttempt)
        .values(
            conversion_id=row.id,
            attempt=attempt,
            started_at=started,
            finished_at=max(finished, started),
            http_status=answer.http_status,
            error_code=answer.error_code,
            trace_id=answer.trace_id,
            duration_ms=answer.duration_ms,
        )
        .on_conflict_do_nothing(index_elements=["conversion_id", "attempt"])
    )
    row.attempts = attempt
    row.last_http_status = answer.http_status
    row.last_error_code = answer.error_code
    row.trace_id = answer.trace_id or row.trace_id
    if answer.delivered:
        row.status = "delivered"
        row.delivered_at = max(finished, started)
    elif answer.wait == "never":
        row.status = "rejected"
    elif answer.wait == "customer":
        # Only the customer can fix it (connect again, allow a permission): wait, and
        # let the age limit drop what can no longer go.
        row.next_attempt_at = finished + WAIT_FOR_CUSTOMER
    elif attempt >= MAX_ATTEMPTS:
        row.status = "dead_letter"
    else:
        row.next_attempt_at = finished + retry_delay(attempt)


async def retry(db: AsyncSession, tenant_id: UUID, conversion_id: UUID, now: datetime) -> bool:
    """A manager's "Try again" on an event a platform refused for good, while it is fresh."""
    row = await db.scalar(
        select(LeadConversion)
        .where(LeadConversion.id == conversion_id, LeadConversion.tenant_id == tenant_id)
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
    UPDATE lead_desk_conversions SET payload = NULL, erased_at = :now
    WHERE id IN (
      SELECT id FROM lead_desk_conversions
      WHERE payload IS NOT NULL AND status IN ('delivered', 'rejected', 'dead_letter')
        AND created_at < :before
      ORDER BY created_at LIMIT 500
    )
"""
_GONE = """
    UPDATE lead_desk_conversions c
    SET payload = NULL, erased_at = :now,
        status = CASE WHEN c.status = 'pending' THEN 'dropped' ELSE c.status END,
        last_error_code = CASE WHEN c.status = 'pending' THEN 'lead_gone'
                               ELSE c.last_error_code END
    WHERE c.id IN (
      SELECT x.id FROM lead_desk_conversions x
      WHERE x.payload IS NOT NULL
        AND NOT EXISTS (
          SELECT 1 FROM lead_desk_leads l WHERE l.tenant_id = x.tenant_id AND l.id = x.lead_id
        )
      LIMIT 500
    )
"""
# The Meta-only table keeps its own erasure until its last rows age out.
_LEGACY_SWEEP = """
    UPDATE lead_desk_meta_conversions SET payload = NULL, erased_at = :now
    WHERE id IN (
      SELECT id FROM lead_desk_meta_conversions x
      WHERE x.payload IS NOT NULL AND (
        x.created_at < :before
        OR NOT EXISTS (
          SELECT 1 FROM lead_desk_leads l WHERE l.tenant_id = x.tenant_id AND l.id = x.lead_id
        )
      ) AND x.status <> 'pending'
      LIMIT 500
    )
"""


async def erasure_sweep(db: AsyncSession, now: datetime) -> int:
    """Empty event bodies older than 90 days, and at once those of a lead that is gone;
    ids, digests, results and attempts stay."""
    total = 0
    for sql in (_SWEEP, _GONE, _LEGACY_SWEEP):
        result = await db.execute(text(sql), {"now": now, "before": now - KEEP})
        total += int(getattr(result, "rowcount", 0) or 0)
    return total


async def tick(
    sessions: async_sessionmaker[AsyncSession],
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
            text("SELECT pg_try_advisory_xact_lock(:a, :b)"), {"a": LOCK[0], "b": LOCK[1]}
        ):
            return {"made": made, "sent": 0}
        lines = await deliver(db, client, now=now)
        swept = await erasure_sweep(db, now)
    delivered = sum(1 for line in lines if line.get("status") == "delivered")
    if lines or made:
        events_log.info("lead_desk_conversions", made=made, tried=len(lines), delivered=delivered)
    return {"made": made, "sent": len(lines), "delivered": delivered, "swept": swept}


async def run_sender(
    sessions: async_sessionmaker[AsyncSession],
    stop: asyncio.Event,
    *,
    environment: str,
    first_delay: int = _TICK,
) -> None:
    """Every minute, send lead stages to the platforms businesses set up. Survives a bad tick."""
    with suppress(TimeoutError):
        await asyncio.wait_for(stop.wait(), timeout=first_delay)
    async with httpx.AsyncClient(timeout=TIMEOUT) as client:
        while not stop.is_set():
            try:
                await tick(sessions, client, environment=environment)
            except Exception:  # noqa: BLE001 - the loop must survive a bad tick
                log.warning("lead stage conversions tick failed", exc_info=True)
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
                run_sender(sessions, stop, environment=environment), name="lead-stage-conversions"
            )
            try:
                yield state
            finally:
                stop.set()
                task.cancel()
                with suppress(asyncio.CancelledError):
                    await task

    application.router.lifespan_context = lifespan


# ----- what the page shows ----------------------------------------------------------------


async def summary(db: AsyncSession, tenant_id: UUID, now: datetime) -> dict[str, Any]:
    """Per platform: counts for the last 7 days and the last delivery; the 20 newest
    events across platforms."""
    week = now - timedelta(days=7)
    counts: dict[str, dict[str, int]] = {}
    for provider, status, count in (
        await db.execute(
            select(LeadConversion.provider, LeadConversion.status, func.count())
            .where(LeadConversion.tenant_id == tenant_id, LeadConversion.created_at >= week)
            .group_by(LeadConversion.provider, LeadConversion.status)
        )
    ).tuples():
        counts.setdefault(provider, {})[status] = int(count)
    last = {
        provider: at
        for provider, at in (
            await db.execute(
                select(LeadConversion.provider, func.max(LeadConversion.delivered_at))
                .where(LeadConversion.tenant_id == tenant_id)
                .group_by(LeadConversion.provider)
            )
        ).tuples()
    }
    waiting = {
        provider: code
        for provider, code in (
            await db.execute(
                select(LeadConversion.provider, LeadConversion.last_error_code)
                .where(
                    LeadConversion.tenant_id == tenant_id,
                    LeadConversion.status == "pending",
                    LeadConversion.attempts > 0,
                )
                .order_by(LeadConversion.next_attempt_at)
            )
        ).tuples()
    }
    recent = (
        await db.execute(
            select(LeadConversion, Lead.name)
            .join(
                Lead,
                and_(Lead.tenant_id == LeadConversion.tenant_id, Lead.id == LeadConversion.lead_id),
            )
            .where(LeadConversion.tenant_id == tenant_id)
            .order_by(LeadConversion.created_at.desc(), LeadConversion.event_time.desc())
            .limit(20)
        )
    ).tuples()
    return {
        "counts": counts,
        "last_delivered_at": last,
        "waiting_on": waiting,
        "recent": [
            {
                "id": row.id,
                "provider": row.provider,
                "lead_id": row.lead_id,
                "lead_name": name,
                "stage_key": row.stage_key,
                "event_name": row.event_name,
                "status": row.status,
                "attempts": row.attempts,
                "event_time": row.event_time,
                "delivered_at": row.delivered_at,
                "error": row.last_error_code,
                "test": row.test,
            }
            for row, name in recent
        ],
    }


async def settling(
    db: AsyncSession, tenant_id: UUID, config: Mapping[str, Any], journey: Journey, now: datetime
) -> tuple[int, datetime | None]:
    """Stage changes that will go once they settle (5 minutes), and when the first goes."""
    targets = [
        (mapping.read(config, provider), mapping.module(provider))
        for provider in mapping.available()
    ]
    targets = [item for item in targets if item[0].ready]
    if not targets:
        return 0, None
    floor = max(
        min(datetime.fromtimestamp(settings.since, UTC) for settings, _ in targets),
        now - MAX_AGE,
    )
    query = (
        select(LeadEvent.kind, LeadEvent.data, LeadEvent.created_at, Lead)
        .join(Lead, and_(Lead.tenant_id == LeadEvent.tenant_id, Lead.id == LeadEvent.lead_id))
        .where(
            LeadEvent.tenant_id == tenant_id,
            LeadEvent.kind.in_(KINDS),
            LeadEvent.created_at >= floor,
            LeadEvent.created_at > now - SETTLE,
        )
        .order_by(LeadEvent.created_at, LeadEvent.id)
        .limit(COLLECT_LIMIT)
    )
    waits = 0
    first: datetime | None = None
    for kind, data, at, lead in (await db.execute(query)).tuples():
        key = reached(journey, kind, data if isinstance(data, dict) else {})
        if key is None:
            continue
        if any(
            adapter.identity(lead) is not None
            and any(settings.events.get(k) for k in journey.with_earlier(key))
            for settings, adapter in targets
        ):
            waits += 1
            first = first or at
    return waits, first + SETTLE if first is not None else None
