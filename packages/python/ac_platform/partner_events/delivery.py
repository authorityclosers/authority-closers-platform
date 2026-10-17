"""Signed delivery of frozen partner events, with retries and a dead letter.

- One runner per database (a session advisory lock); each event is claimed
  with ``FOR UPDATE SKIP LOCKED`` and a short lease, so two runners never send
  the same attempt.
- Before each send the call is admitted again: an erased call, revoked
  consent or an inactive account drops the event and empties its payload.
- ``POST`` with a 10 s timeout, no redirects. Headers ``X-SX-Event-Id``,
  ``X-SX-Event-Type`` and ``X-SX-Signature: t=<unix>,v1=<hex>[,v1=<hex>]``,
  where ``v1 = HMAC-SHA256(secret, f"{t}." + raw_body)`` for the current and,
  during a rotation, the next secret. Secrets are read from the environment
  variables the endpoint names; their values are never logged or stored.
- Any 2xx is delivered. Otherwise the same bytes are retried after
  10 s x 2^(n-1), at most 1 h, 25 attempts, then dead letter.
- Every attempt is an append-only row: status code and a content-free error
  code only. Payloads, URLs and secrets are never logged.
"""

from __future__ import annotations

import hashlib
import hmac
import os
import time
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any
from urllib.parse import urlsplit
from uuid import UUID

from ac_platform.partner_events.payload import body_bytes

RUN_LOCK = "ac.partner_events.run"
MAX_ATTEMPTS = 25
FIRST_DELAY_SECONDS = 10
MAX_DELAY_SECONDS = 3600
TIMEOUT_SECONDS = 10.0
LEASE = timedelta(seconds=60)
USER_AGENT = "AuthorityClosers-SalesXray-Webhooks/1"
LOCAL_ENVIRONMENTS = frozenset({"development", "local", "test"})
# Refusals that mean the call's data must not leave: the event is dropped and emptied.
DROP_REFUSALS = frozenset(
    {"call_missing", "call_erased", "permission_inactive", "account_inactive"}
)


def signature(secret: bytes, timestamp: int, body: bytes) -> str:
    return hmac.new(secret, f"{timestamp}.".encode() + body, hashlib.sha256).hexdigest()


def signature_header(timestamp: int, body: bytes, secrets: list[bytes]) -> str:
    parts = [f"t={timestamp}", *(f"v1={signature(secret, timestamp, body)}" for secret in secrets)]
    return ",".join(parts)


def retry_delay(failures: int) -> timedelta:
    """Wait after the n-th failed attempt of this delivery cycle (n >= 1)."""
    exponent = max(0, failures - 1)
    seconds = MAX_DELAY_SECONDS if exponent >= 12 else FIRST_DELAY_SECONDS * 2**exponent
    return timedelta(seconds=min(seconds, MAX_DELAY_SECONDS))


def url_allowed(url: str, environment: str) -> bool:
    """HTTPS anywhere; plain HTTP only to this machine and only in development."""
    try:
        parts = urlsplit(url)
        port = parts.port
    except ValueError:
        return False
    if parts.username or parts.password or not parts.hostname or "#" in url:
        return False
    if port is not None and not 0 < port < 65536:
        return False
    if parts.scheme == "https":
        return True
    return (
        parts.scheme == "http"
        and parts.hostname in {"127.0.0.1", "localhost"}
        and environment in LOCAL_ENVIRONMENTS
    )


def mask_url(url: str) -> str:
    """Scheme, host and port only; paths and queries can carry secrets."""
    try:
        parts = urlsplit(url)
        port = f":{parts.port}" if parts.port else ""
    except ValueError:
        return "<invalid>"
    return f"{parts.scheme}://{parts.hostname}{port}/…"


def read_secrets(secret_ref: str, secret_ref_next: str | None) -> list[bytes] | None:
    names = [secret_ref, *([secret_ref_next] if secret_ref_next else [])]
    values = [os.environ.get(name, "") for name in names]
    if not all(values):
        return None
    return [value.encode() for value in values]


@dataclass(frozen=True)
class Outcome:
    http_status: int | None
    error_code: str | None
    duration_ms: int

    @property
    def delivered(self) -> bool:
        return self.http_status is not None and 200 <= self.http_status < 300


def post(
    client: Any,
    *,
    url: str,
    event_id: str,
    event_type: str,
    body: bytes,
    secrets: list[bytes],
    clock: Callable[[], float] = time.time,
) -> Outcome:
    """One signed POST. Never reads or logs the response body."""
    import httpx

    started = time.monotonic()
    headers = {
        "Content-Type": "application/json; charset=utf-8",
        "User-Agent": USER_AGENT,
        "X-SX-Event-Id": event_id,
        "X-SX-Event-Type": event_type,
        "X-SX-Signature": signature_header(int(clock()), body, secrets),
    }

    def elapsed() -> int:
        return max(0, round((time.monotonic() - started) * 1000))

    try:
        response = client.post(url, content=body, headers=headers)
    except httpx.TimeoutException:
        return Outcome(None, "timeout", elapsed())
    except httpx.ConnectError:
        return Outcome(None, "connect_error", elapsed())
    except httpx.HTTPError:
        return Outcome(None, "transport_error", elapsed())
    status = int(response.status_code)
    response.close()
    if not 100 <= status <= 599:
        return Outcome(None, "http_status_invalid", elapsed())
    return Outcome(status, None if 200 <= status < 300 else "http_status", elapsed())


def http_client() -> Any:
    import httpx

    return httpx.Client(
        timeout=httpx.Timeout(TIMEOUT_SECONDS), follow_redirects=False, trust_env=False
    )


async def try_run_lock(connection: Any) -> bool:
    """The database-wide runner lock (a session lock on a dedicated connection)."""
    from sqlalchemy import text

    held = await connection.scalar(
        text("SELECT pg_try_advisory_lock(hashtextextended(:key, 0))"), {"key": RUN_LOCK}
    )
    await connection.commit()
    return bool(held)


async def release_run_lock(connection: Any) -> None:
    from sqlalchemy import text

    await connection.scalar(
        text("SELECT pg_advisory_unlock(hashtextextended(:key, 0))"), {"key": RUN_LOCK}
    )
    await connection.commit()


@dataclass(frozen=True)
class Claimed:
    event_id: UUID
    attempt: int
    endpoint_url: str
    secret_ref: str
    secret_ref_next: str | None
    event_type: str
    payload: dict[str, Any]
    payload_sha256: str
    report: dict[str, Any]


_CLAIM = """
    SELECT e.id
    FROM partner_webhook_events e
    JOIN partner_webhook_endpoints p ON p.id = e.endpoint_id
    WHERE e.status = 'pending' AND e.next_attempt_at <= :now
      AND (e.leased_until IS NULL OR e.leased_until < :now)
      AND p.status = 'active'
    ORDER BY e.next_attempt_at, e.id
    LIMIT 1
    FOR UPDATE OF e SKIP LOCKED
"""


async def claim_next(session: Any, now: datetime) -> Claimed | None:
    """Lease the next due event in the caller's transaction (commit before sending)."""
    from sqlalchemy import select, text, update

    from ac_platform.partner_events.models import PartnerWebhookEndpoint, PartnerWebhookEvent

    event_id = await session.scalar(text(_CLAIM), {"now": now})
    if event_id is None:
        return None
    await session.execute(
        update(PartnerWebhookEvent)
        .where(PartnerWebhookEvent.id == event_id)
        .values(leased_until=now + LEASE)
    )
    event, endpoint = (
        await session.execute(
            select(PartnerWebhookEvent, PartnerWebhookEndpoint)
            .join(
                PartnerWebhookEndpoint, PartnerWebhookEndpoint.id == PartnerWebhookEvent.endpoint_id
            )
            .where(PartnerWebhookEvent.id == event_id)
        )
    ).one()
    assert event.payload is not None  # pending events are never emptied
    return Claimed(
        event_id=event.id,
        attempt=event.attempts + 1,
        endpoint_url=endpoint.url,
        secret_ref=endpoint.secret_ref,
        secret_ref_next=endpoint.secret_ref_next,
        event_type=event.event_type,
        payload=dict(event.payload),
        payload_sha256=event.payload_sha256,
        report={
            "tenant_id": event.tenant_id,
            "recording_id": event.recording_id,
            "draft_id": event.report_draft_id,
        },
    )


_NEWEST_DRAFT = """
    SELECT (SELECT erased_at IS NULL AND payload IS NOT NULL FROM conversation_report_drafts
            WHERE id = :draft) AS own_live,
           n.id, n.run_id, n.source_sha256, n.payload ->> 'transcript_revision' AS revision
    FROM (SELECT 1) one
    LEFT JOIN LATERAL (
      SELECT id, run_id, source_sha256, payload FROM conversation_report_drafts
      WHERE recording_id = :recording AND erased_at IS NULL
      ORDER BY created_at DESC LIMIT 1
    ) n ON TRUE
"""


def delivery_refusal(connection: Any, report: dict[str, Any], now: datetime) -> str | None:
    """Why this event's call data may not leave now, or None (a re-run of admission).

    The canonical checks (``pointer_review.admission_refusal``) run against the
    call's newest report, so an event for an older revision still respects
    erasure, consent, retention and account state. ``stale_source`` is not a
    refusal here: an older revision may still be delivered, and the partner
    applies the highest ``analysis_revision``.
    """
    from sqlalchemy import text

    from ac_platform.conversation_intelligence.pointer_review import admission_refusal

    row = connection.execute(
        text(_NEWEST_DRAFT), {"draft": report["draft_id"], "recording": report["recording_id"]}
    ).first()
    if row is None or not row.own_live or row.id is None:
        return "call_erased"
    return admission_refusal(
        connection,
        {
            "tenant_id": report["tenant_id"],
            "recording_id": report["recording_id"],
            "draft_id": row.id,
            "run_id": row.run_id,
            "source_sha256": row.source_sha256,
            "transcript_revision": row.revision,
        },
        now,
    )


async def drop(session: Any, event_id: UUID, reason: str, now: datetime) -> None:
    """Drop one undelivered event and empty its payload (the call's data must not leave)."""
    from sqlalchemy import update

    from ac_platform.partner_events.models import PartnerWebhookEvent

    await session.execute(
        update(PartnerWebhookEvent)
        .where(PartnerWebhookEvent.id == event_id, PartnerWebhookEvent.status == "pending")
        .values(
            status="dropped",
            payload=None,
            erased_at=now,
            leased_until=None,
            last_error_code=reason[:64],
        )
    )


async def record(
    session: Any, claimed: Claimed, outcome: Outcome, started: datetime, finished: datetime
) -> str:
    """Write the attempt row and move the event on; returns the event's new status.

    Guarded on the attempt count, so a runner whose lease expired never
    overwrites the result of the runner that took the event over.
    """
    from sqlalchemy import select, update
    from sqlalchemy.dialects.postgresql import insert

    from ac_platform.partner_events.models import PartnerWebhookAttempt, PartnerWebhookEvent

    event = await session.scalar(
        select(PartnerWebhookEvent)
        .where(PartnerWebhookEvent.id == claimed.event_id)
        .with_for_update()
    )
    if event is None or event.status != "pending" or event.attempts + 1 != claimed.attempt:
        return "superseded"
    await session.execute(
        insert(PartnerWebhookAttempt)
        .values(
            event_id=claimed.event_id,
            attempt=claimed.attempt,
            started_at=started,
            finished_at=max(finished, started),
            http_status=outcome.http_status,
            error_code=outcome.error_code,
            duration_ms=outcome.duration_ms,
        )
        .on_conflict_do_nothing(index_elements=["event_id", "attempt"])
    )
    values: dict[str, Any] = {
        "attempts": claimed.attempt,
        "leased_until": None,
        "last_http_status": outcome.http_status,
        "last_error_code": outcome.error_code,
    }
    if outcome.delivered:
        values.update(status="delivered", delivered_at=finished)
    else:
        failures = claimed.attempt - event.replayed_attempts
        if failures >= MAX_ATTEMPTS:
            values.update(status="dead_letter")
        else:
            values.update(next_attempt_at=finished + retry_delay(failures))
    await session.execute(
        update(PartnerWebhookEvent)
        .where(PartnerWebhookEvent.id == claimed.event_id)
        .values(**values)
    )
    return str(values.get("status", "pending"))


async def deliver_one(
    sessions: Any,
    client: Any,
    *,
    environment: str,
    clock: Callable[[], datetime],
) -> dict[str, Any] | None:
    """Claim, admit, send and record one due event; None when nothing is due."""
    async with sessions() as session, session.begin():
        claimed = await claim_next(session, clock())
    if claimed is None:
        return None
    line: dict[str, Any] = {"event": str(claimed.event_id), "attempt": claimed.attempt}
    async with sessions() as session, session.begin():
        now = clock()
        report = claimed.report
        refusal = await session.run_sync(
            lambda sync: delivery_refusal(sync.connection(), report, now)
        )
        if refusal in DROP_REFUSALS:
            assert refusal is not None
            await drop(session, claimed.event_id, refusal, now)
            line["dropped"] = refusal
            return line
    body = body_bytes(claimed.payload)
    started = clock()
    if hashlib.sha256(body).hexdigest() != claimed.payload_sha256:
        outcome = Outcome(None, "payload_integrity", 0)
    elif not url_allowed(claimed.endpoint_url, environment):
        outcome = Outcome(None, "url_refused", 0)
    else:
        secrets = read_secrets(claimed.secret_ref, claimed.secret_ref_next)
        if secrets is None:
            outcome = Outcome(None, "secret_missing", 0)
        else:
            outcome = post(
                client,
                url=claimed.endpoint_url,
                event_id=str(claimed.event_id),
                event_type=claimed.event_type,
                body=body,
                secrets=secrets,
            )
    finished = clock()
    async with sessions() as session, session.begin():
        line["status"] = await record(session, claimed, outcome, started, finished)
    line["http_status"] = outcome.http_status
    if outcome.error_code:
        line["error"] = outcome.error_code
    return line


_SWEEP_FACTS = """
    UPDATE partner_quote_facts SET payload = NULL, erased_at = :now
    WHERE id IN (
      SELECT q.id
      FROM partner_quote_facts q
      JOIN conversation_recordings c ON c.id = q.recording_id
      LEFT JOIN conversation_report_drafts d ON d.id = q.report_draft_id
      WHERE q.erased_at IS NULL
        AND (c.state IN ('deleting', 'deleted') OR c.deleted_at IS NOT NULL
             OR d.erased_at IS NOT NULL OR d.id IS NULL)
    )
"""
_SWEEP_EVENTS = """
    UPDATE partner_webhook_events
    SET payload = NULL, erased_at = :now, leased_until = NULL,
        status = CASE WHEN status IN ('pending', 'dead_letter') THEN 'dropped' ELSE status END,
        last_error_code = CASE WHEN status IN ('pending', 'dead_letter') THEN 'call_erased'
                               ELSE last_error_code END
    WHERE id IN (
      SELECT e.id
      FROM partner_webhook_events e
      JOIN conversation_recordings c ON c.id = e.recording_id
      LEFT JOIN conversation_report_drafts d ON d.id = e.report_draft_id
      WHERE e.erased_at IS NULL
        AND (c.state IN ('deleting', 'deleted') OR c.deleted_at IS NOT NULL
             OR d.erased_at IS NOT NULL OR d.id IS NULL)
    )
"""


async def erasure_sweep(session: Any, now: datetime) -> dict[str, int]:
    """Empty quote facts and events of erased calls (provenance kept); repeat-safe."""
    from sqlalchemy import text

    facts = await session.execute(text(_SWEEP_FACTS), {"now": now})
    events = await session.execute(text(_SWEEP_EVENTS), {"now": now})
    return {"facts_erased": int(facts.rowcount or 0), "events_erased": int(events.rowcount or 0)}
