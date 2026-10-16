"""Admission and the paid-attempt ledger for AI pointer reviews (AUT-2010).

Every provider call for a pointer review goes through ``claim`` and then
``save`` or ``finish``, whichever entrypoint starts it:

- one runner at a time per database (a session advisory lock), and one claim
  per call at a time (a transaction advisory lock);
- the call's consent, retention, account and source are checked
  (``pointer_review.admission_refusal``) when the attempt is claimed and again,
  in the saving transaction, when its answer arrives;
- each paid attempt is an append-only audit event in the call's workspace
  chain, written and committed before the provider is called. Its outcome
  (saved, refused, timeout, provider error, unreadable answer) is a second
  event. A start without an outcome is an uncertain attempt: it counts as
  spent and as a failure, and a call is not tried again after two unsaved
  attempts.

The events carry ids, digests, the model, mode and token counts only: never
transcript text, prompts, answers or credentials. No price, charge, refund or
budget reservation is recorded here; the canonical quote and reservation for
this purpose are not approved yet (AUT-2010 return).
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any
from uuid import UUID, uuid4

from ac_platform.conversation_intelligence.pointer_review import (
    MODEL_ID,
    PROMPT_REVISION,
    VERSION,
    admission_refusal,
    save_review,
)

STARTED = "conversation.pointer_review.dispatch_started"
FINISHED = "conversation.pointer_review.dispatch_finished"
RESOURCE = "conversation_recording"
RUN_LOCK = "ac.pointer_review.run"
IN_FLIGHT = timedelta(minutes=10)
MAX_UNSAVED_ATTEMPTS = 2
MODES = ("automatic", "operator")


@dataclass(frozen=True)
class Claim:
    attempt: UUID | None
    refused: str | None = None


async def try_run_lock(connection: Any) -> bool:
    """Take the database-wide runner lock; False when another runner holds it.

    A session lock on the caller's dedicated connection: it is released by
    ``release_run_lock`` or when that connection closes (also on a crash).
    """
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


async def _lock_call(session: Any, report: dict[str, Any]) -> None:
    from sqlalchemy import text

    await session.execute(
        text("SELECT pg_advisory_xact_lock(hashtextextended(:key, 0))"),
        {"key": f"ac.pointer_review:{report['recording_id']}"},
    )


def history_refusal(
    events: list[dict[str, Any]], now: datetime, *, in_flight: timedelta = IN_FLIGHT
) -> str | None:
    """Judge this report's earlier attempts (oldest first) from the ledger.

    An attempt started within ``in_flight`` without an outcome may still be
    running. An older one without an outcome is uncertain: it may have been
    paid, so it counts like a failure. Saving resets the failure count.
    """
    started: dict[str, datetime] = {}
    outcomes: dict[str, str] = {}
    for event in events:
        attempt = str(event.get("attempt_id") or "")
        if event["action"] == STARTED:
            started[attempt] = event["occurred_at"]
        elif event["action"] == FINISHED:
            outcomes[attempt] = str(event.get("outcome") or "")
    unsaved = 0
    for attempt, when in sorted(started.items(), key=lambda item: item[1]):
        outcome = outcomes.get(attempt)
        if outcome is None and now - when < in_flight:
            return "in_flight"
        unsaved = 0 if outcome == "saved" else unsaved + 1
    return "attempts_exhausted" if unsaved >= MAX_UNSAVED_ATTEMPTS else None


async def _history(session: Any, report: dict[str, Any]) -> list[dict[str, Any]]:
    from sqlalchemy import text

    rows = await session.execute(
        text(
            """
            SELECT action, payload ->> 'attempt_id' AS attempt_id,
                   payload ->> 'outcome' AS outcome, occurred_at
            FROM audit_events
            WHERE tenant_id = :tenant AND resource_type = :resource
              AND resource_id = :recording AND action IN (:started, :finished)
              AND payload ->> 'run_id' = :run
              AND payload ->> 'source_sha256' = :source
              AND payload ->> 'transcript_revision' = :revision
            ORDER BY sequence_no
            """
        ),
        {
            "tenant": report["tenant_id"],
            "resource": RESOURCE,
            "recording": str(report["recording_id"]),
            "started": STARTED,
            "finished": FINISHED,
            "run": str(report["run_id"]),
            "source": report["source_sha256"],
            "revision": report["transcript_revision"],
        },
    )
    return [dict(row) for row in rows.mappings()]


async def attempts_today(session: Any, mode: str, created_by: str, now: datetime) -> int:
    """Paid attempts in the last 24 hours for this mode, uncertain ones included.

    Reviews saved before the ledger existed are counted too, so a release
    that adds the ledger mid-day never resets the daily cap.
    """
    from sqlalchemy import text

    since = now - timedelta(hours=24)
    ledger = await session.scalar(
        text(
            "SELECT count(*) FROM audit_events WHERE action = :started"
            " AND occurred_at > :since AND payload ->> 'mode' = :mode"
        ),
        {"started": STARTED, "since": since, "mode": mode},
    )
    saved = await session.scalar(
        text(
            "SELECT count(*) FROM conversation_pointer_reviews"
            " WHERE created_by = :who AND created_at > :since"
        ),
        {"who": created_by, "since": since},
    )
    return max(int(ledger or 0), int(saved or 0))


async def _already_reviewed(session: Any, report: dict[str, Any]) -> bool:
    from sqlalchemy import text

    return (
        await session.scalar(
            text(
                "SELECT 1 FROM conversation_pointer_reviews WHERE run_id = :run"
                " AND source_sha256 = :source AND transcript_revision = :revision"
                " AND erased_at IS NULL LIMIT 1"
            ),
            {
                "run": report["run_id"],
                "source": report["source_sha256"],
                "revision": report["transcript_revision"],
            },
        )
        is not None
    )


def _actor_type(mode: str) -> str:
    if mode not in MODES:
        raise ValueError("pointer_review_mode_unknown")
    return "system" if mode == "automatic" else "operator"


def _provenance(report: dict[str, Any], attempt: UUID, mode: str) -> dict[str, Any]:
    return {
        "attempt_id": str(attempt),
        "mode": mode,
        "run_id": str(report["run_id"]),
        "report_draft_id": str(report["draft_id"]),
        "source_sha256": report["source_sha256"],
        "transcript_revision": report["transcript_revision"],
        "version": VERSION,
        "prompt_revision": PROMPT_REVISION,
        "model": MODEL_ID,
    }


async def _append(
    session: Any,
    report: dict[str, Any],
    mode: str,
    action: str,
    payload: dict[str, Any],
    now: datetime,
) -> None:
    from ac_platform.audit.service import AuditRepository

    await AuditRepository(session).append(
        tenant_id=report["tenant_id"],
        actor_person_id=None,
        actor_type=_actor_type(mode),
        action=action,
        resource_type=RESOURCE,
        resource_id=str(report["recording_id"]),
        payload=payload,
        now=now,
    )


async def claim(
    session: Any,
    report: dict[str, Any],
    *,
    mode: str,
    created_by: str,
    forced: bool,
    prompt_digest: str,
    daily_cap: int,
    now: datetime,
) -> Claim:
    """Admit one paid attempt and record its start, in the caller's transaction.

    The caller commits before calling the provider, so the start is durable
    whatever happens next. ``forced`` only allows reviewing a report again;
    it never skips consent, erasure, source, in-flight or attempt checks.
    """
    _actor_type(mode)
    await _lock_call(session, report)
    refusal = await session.run_sync(lambda sync: admission_refusal(sync.connection(), report, now))
    if refusal is not None:
        return Claim(None, refusal)
    if not forced and await _already_reviewed(session, report):
        return Claim(None, "already_reviewed")
    refusal = history_refusal(await _history(session, report), now)
    if refusal is not None:
        return Claim(None, refusal)
    if await attempts_today(session, mode, created_by, now) >= daily_cap:
        return Claim(None, "daily_cap")
    attempt = uuid4()
    payload = {**_provenance(report, attempt, mode), "prompt_sha256": prompt_digest}
    payload["forced"] = forced
    await _append(session, report, mode, STARTED, payload, now)
    return Claim(attempt)


def _tokens(usage: dict[str, Any] | None) -> dict[str, int | None]:
    usage = usage or {}

    def count(key: str) -> int | None:
        value = usage.get(key)
        return int(value) if isinstance(value, int) and value >= 0 else None

    return {
        "input_tokens": count("promptTokenCount"),
        "output_tokens": count("candidatesTokenCount"),
    }


async def finish(
    session: Any,
    report: dict[str, Any],
    attempt: UUID,
    *,
    mode: str,
    outcome: str,
    usage: dict[str, Any] | None,
    now: datetime,
    review_id: UUID | None = None,
) -> None:
    """Record one attempt's outcome (append-only) in the caller's transaction."""
    payload = {**_provenance(report, attempt, mode), "outcome": outcome, **_tokens(usage)}
    if review_id is not None:
        payload["review_id"] = str(review_id)
    await _append(session, report, mode, FINISHED, payload, now)


async def save(
    session: Any,
    report: dict[str, Any],
    attempt: UUID,
    *,
    mode: str,
    review: dict[str, Any],
    prompt_digest: str,
    usage: dict[str, Any],
    created_by: str,
    now: datetime,
) -> str:
    """Save a provider answer only if the call still passes admission.

    Returns the recorded outcome: "saved" or "refused_<reason>". Either way
    the outcome event is written in the same transaction as the decision.
    """
    await _lock_call(session, report)
    refusal = await session.run_sync(lambda sync: admission_refusal(sync.connection(), report, now))
    review_id = None
    if refusal is None:
        review_id = await session.run_sync(
            lambda sync: save_review(
                sync.connection(),
                report=report,
                review=review,
                prompt_digest=prompt_digest,
                usage=usage,
                created_by=created_by,
                now=now,
            )
        )
        refusal = None if review_id is not None else "call_erased"
    outcome = "saved" if refusal is None else f"refused_{refusal}"
    await finish(
        session,
        report,
        attempt,
        mode=mode,
        outcome=outcome,
        usage=usage,
        now=now,
        review_id=review_id,
    )
    return outcome
