"""Admission and the paid-attempt ledger for partner quote facts.

Every provider call goes through ``claim`` and then ``save_complete`` or
``save_failed`` (the same pattern as AI pointer reviews, AUT-2010):

- one runner per database (``delivery.try_run_lock``) and one claim per call
  at a time (a transaction advisory lock);
- the call's consent, retention, account, erasure and source are checked
  (``pointer_review.admission_refusal``) when the attempt is claimed and
  again, in the saving transaction, when the answer arrives;
- each paid attempt is an append-only audit event in the call's workspace
  chain, committed before the provider is called; its outcome is a second
  event. A start without an outcome counts as spent and as a failure. At
  most two attempts per report and profile (also a database constraint),
  and a rolling 24-hour cap per database.

Events carry ids, digests, the model and token counts only: never transcript
text, prompts, answers or credentials.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any
from uuid import UUID, uuid4

from ac_platform.conversation_intelligence.pointer_review import admission_refusal
from ac_platform.partner_events.quote_facts import Profile, payload_sha256

STARTED = "partner_events.quote_facts.dispatch_started"
FINISHED = "partner_events.quote_facts.dispatch_finished"
RESOURCE = "conversation_recording"
MAX_ATTEMPTS = 2
IN_FLIGHT = timedelta(minutes=10)


@dataclass(frozen=True)
class Claim:
    attempt_id: UUID | None
    attempt: int = 0
    refused: str | None = None


async def _lock_call(session: Any, report: dict[str, Any]) -> None:
    from sqlalchemy import text

    await session.execute(
        text("SELECT pg_advisory_xact_lock(hashtextextended(:key, 0))"),
        {"key": f"ac.partner_quote_facts:{report['recording_id']}"},
    )


async def _admission(session: Any, report: dict[str, Any], now: datetime) -> str | None:
    refusal: str | None = await session.run_sync(
        lambda sync: admission_refusal(sync.connection(), report, now)
    )
    return refusal


async def complete_facts(session: Any, report: dict[str, Any], profile: str) -> Any:
    """The saved, unerased complete facts row for this exact report and profile."""
    from sqlalchemy import select

    from ac_platform.partner_events.models import PartnerQuoteFacts

    return await session.scalar(
        select(PartnerQuoteFacts)
        .where(
            PartnerQuoteFacts.report_draft_id == report["draft_id"],
            PartnerQuoteFacts.run_id == report["run_id"],
            PartnerQuoteFacts.source_sha256 == report["source_sha256"],
            PartnerQuoteFacts.transcript_revision == report["transcript_revision"],
            PartnerQuoteFacts.profile == profile,
            PartnerQuoteFacts.status == "complete",
            PartnerQuoteFacts.erased_at.is_(None),
        )
        .order_by(PartnerQuoteFacts.created_at.desc())
        .limit(1)
    )


async def history(session: Any, report: dict[str, Any], profile: str) -> list[dict[str, Any]]:
    from sqlalchemy import text

    rows = await session.execute(
        text(
            """
            SELECT action, payload ->> 'attempt_id' AS attempt_id,
                   payload ->> 'outcome' AS outcome, occurred_at
            FROM audit_events
            WHERE tenant_id = :tenant AND resource_type = :resource
              AND resource_id = :recording AND action IN (:started, :finished)
              AND payload ->> 'report_draft_id' = :draft
              AND payload ->> 'profile' = :profile
            ORDER BY sequence_no
            """
        ),
        {
            "tenant": report["tenant_id"],
            "resource": RESOURCE,
            "recording": str(report["recording_id"]),
            "started": STARTED,
            "finished": FINISHED,
            "draft": str(report["draft_id"]),
            "profile": profile,
        },
    )
    return [dict(row) for row in rows.mappings()]


def attempts_left(events: list[dict[str, Any]], now: datetime) -> str | None:
    """None when another attempt may start; else in_flight or attempts_exhausted.

    An attempt started within ``IN_FLIGHT`` without an outcome may still be
    running. Every started attempt counts, whatever its outcome: a start
    without an outcome may have been paid.
    """
    started: dict[str, datetime] = {}
    finished: set[str] = set()
    for event in events:
        attempt = str(event.get("attempt_id") or "")
        if event["action"] == STARTED:
            started[attempt] = event["occurred_at"]
        elif event["action"] == FINISHED:
            finished.add(attempt)
    if any(attempt not in finished and now - when < IN_FLIGHT for attempt, when in started.items()):
        return "in_flight"
    return "attempts_exhausted" if len(started) >= MAX_ATTEMPTS else None


async def attempts_today(session: Any, now: datetime) -> int:
    """Paid attempts in the last 24 hours in this database, uncertain ones included."""
    from sqlalchemy import text

    count = await session.scalar(
        text("SELECT count(*) FROM audit_events WHERE action = :started AND occurred_at > :since"),
        {"started": STARTED, "since": now - timedelta(hours=24)},
    )
    return int(count or 0)


def _provenance(
    report: dict[str, Any], profile: Profile, attempt_id: UUID, attempt: int
) -> dict[str, Any]:
    return {
        "attempt_id": str(attempt_id),
        "attempt": attempt,
        "run_id": str(report["run_id"]),
        "report_draft_id": str(report["draft_id"]),
        "source_sha256": report["source_sha256"],
        "transcript_revision": report["transcript_revision"],
        "profile": profile.name,
        "prompt_revision": profile.prompt_revision,
        "model": profile.model_id,
    }


async def _append(
    session: Any, report: dict[str, Any], action: str, payload: dict[str, Any], now: datetime
) -> None:
    from ac_platform.audit.service import append_audit_event

    await append_audit_event(
        session,
        tenant_id=report["tenant_id"],
        actor_person_id=None,
        actor_type="system",
        action=action,
        resource_type=RESOURCE,
        resource_id=str(report["recording_id"]),
        payload=payload,
        now=now,
    )


async def claim(
    session: Any,
    report: dict[str, Any],
    profile: Profile,
    *,
    prompt_digest: str,
    daily_cap: int,
    now: datetime,
) -> Claim:
    """Admit one paid attempt and record its start, in the caller's transaction.

    The caller commits before calling the provider, so the start is durable
    whatever happens next.
    """
    await _lock_call(session, report)
    refusal = await _admission(session, report, now)
    if refusal is not None:
        return Claim(None, refused=refusal)
    if await complete_facts(session, report, profile.name) is not None:
        return Claim(None, refused="already_extracted")
    events = await history(session, report, profile.name)
    refusal = attempts_left(events, now)
    if refusal is not None:
        return Claim(None, refused=refusal)
    if await attempts_today(session, now) >= daily_cap:
        return Claim(None, refused="daily_cap")
    attempt_id = uuid4()
    attempt = 1 + sum(1 for event in events if event["action"] == STARTED)
    payload = {**_provenance(report, profile, attempt_id, attempt), "prompt_sha256": prompt_digest}
    await _append(session, report, STARTED, payload, now)
    return Claim(attempt_id, attempt)


def _tokens(usage: dict[str, Any] | None) -> dict[str, int | None]:
    usage = usage or {}

    def count(key: str) -> int | None:
        value = usage.get(key)
        return int(value) if isinstance(value, int) and value >= 0 else None

    return {
        "input_tokens": count("promptTokenCount"),
        "output_tokens": count("candidatesTokenCount"),
    }


async def _finish(
    session: Any,
    report: dict[str, Any],
    profile: Profile,
    claimed: Claim,
    *,
    outcome: str,
    usage: dict[str, Any] | None,
    now: datetime,
    facts_id: UUID | None = None,
) -> None:
    assert claimed.attempt_id is not None
    payload = {
        **_provenance(report, profile, claimed.attempt_id, claimed.attempt),
        "outcome": outcome,
        **_tokens(usage),
    }
    if facts_id is not None:
        payload["facts_id"] = str(facts_id)
    await _append(session, report, FINISHED, payload, now)


def _row(
    report: dict[str, Any],
    profile: Profile,
    claimed: Claim,
    *,
    prompt_digest: str,
    usage: dict[str, Any] | None,
    now: datetime,
) -> dict[str, Any]:
    return {
        "id": uuid4(),
        "tenant_id": report["tenant_id"],
        "recording_id": report["recording_id"],
        "run_id": report["run_id"],
        "report_draft_id": report["draft_id"],
        "source_sha256": report["source_sha256"],
        "transcript_revision": report["transcript_revision"],
        "profile": profile.name,
        "attempt": claimed.attempt,
        "model_id": profile.model_id,
        "prompt_sha256": prompt_digest,
        **_tokens(usage),
        "created_at": now,
    }


async def save_complete(
    session: Any,
    report: dict[str, Any],
    profile: Profile,
    claimed: Claim,
    *,
    facts: list[dict[str, Any]],
    prompt_digest: str,
    usage: dict[str, Any] | None,
    now: datetime,
) -> str:
    """Save a validated answer only if the call still passes admission.

    Returns "saved" or "refused_<reason>"; the outcome event is written in
    the same transaction either way.
    """
    from sqlalchemy import insert

    from ac_platform.partner_events.models import PartnerQuoteFacts

    await _lock_call(session, report)
    refusal = await _admission(session, report, now)
    facts_id = None
    if refusal is None:
        payload = {"profile": profile.name, "facts": facts}
        row = _row(report, profile, claimed, prompt_digest=prompt_digest, usage=usage, now=now)
        facts_id = row["id"]
        await session.execute(
            insert(PartnerQuoteFacts).values(
                **row,
                status="complete",
                error_code=None,
                payload=payload,
                payload_sha256=payload_sha256(payload),
            )
        )
    outcome = "saved" if refusal is None else f"refused_{refusal}"
    await _finish(
        session, report, profile, claimed, outcome=outcome, usage=usage, now=now, facts_id=facts_id
    )
    return outcome


async def save_failed(
    session: Any,
    report: dict[str, Any],
    profile: Profile,
    claimed: Claim,
    *,
    error_code: str,
    prompt_digest: str,
    usage: dict[str, Any] | None,
    now: datetime,
) -> None:
    """Record a failed attempt (no content) and its outcome event."""
    from sqlalchemy import insert

    from ac_platform.partner_events.models import PartnerQuoteFacts

    row = _row(report, profile, claimed, prompt_digest=prompt_digest, usage=usage, now=now)
    await session.execute(
        insert(PartnerQuoteFacts).values(
            **row, status="failed", error_code=error_code[:64], payload=None, payload_sha256=None
        )
    )
    await _finish(session, report, profile, claimed, outcome=error_code, usage=usage, now=now)
