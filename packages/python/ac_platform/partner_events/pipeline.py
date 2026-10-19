"""From a finished report to a frozen partner event: candidates, quote facts, enqueue.

Only workspaces with an active endpoint are read, and only reports finished
after that endpoint started taking events (``events_since``): nothing is
backfilled. Each call's newest report gets one event row per endpoint:

- a frozen event to send (``pending``), or
- a final ``dropped`` row with a reason code and no payload, when it will
  never be sent: the call is gone, consent was revoked or the account is
  inactive (``DROP_REFUSALS``), the report has no transcript revision, or it
  waited past the recent window (``aged_out``, and the owner is alerted).

Reports of our own test sources (the canary fixture) are filtered out in the
query and get no row. A report that is waiting (an attempt in flight, the
daily cap, a call not ready yet) keeps its place; the runner pages past it, so
it never holds newer reports back.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID, uuid4

from ac_platform.partner_events import extraction as ledger
from ac_platform.partner_events.delivery import DROP_REFUSALS
from ac_platform.partner_events.payload import (
    EVENT_TYPE,
    Extraction,
    body_sha256,
    build_event,
    call_context,
    summary_text,
)
from ac_platform.partner_events.quote_facts import (
    SINGLE_TYPES,
    QuoteFactsError,
    build_prompt,
    decode_gemini,
    gemini_body,
    load_profile,
    parse_facts,
    payload_sha256,
    prompt_sha256,
    speaker_label,
    unknown,
)

# Final rows carry no body; their digest is that of an empty body.
NO_BODY_SHA256 = hashlib.sha256(b"").hexdigest()
REVISION_MISSING = "transcript_revision_missing"
AGED_OUT = "aged_out"
# How far past the recent window an aged-out report is still looked for.
AGE_OUT_LOOKBACK = timedelta(days=30)
_START = (datetime(1970, 1, 1, tzinfo=UTC), UUID(int=0))


@dataclass(frozen=True)
class Candidate:
    endpoint_id: UUID
    events: tuple[str, ...]
    facts_profile: str | None
    draft_id: UUID
    tenant_id: UUID
    recording_id: UUID
    run_id: UUID
    source_sha256: str
    transcript_revision: str
    created_at: datetime
    submission_id: UUID
    skip: str | None = None  # a reason to record a final row without reading the call

    @property
    def report(self) -> dict[str, Any]:
        return {
            "submission_id": self.submission_id,
            "tenant_id": self.tenant_id,
            "recording_id": self.recording_id,
            "draft_id": self.draft_id,
            "run_id": self.run_id,
            "source_sha256": self.source_sha256,
            "transcript_revision": self.transcript_revision,
        }


@dataclass(frozen=True)
class TranscriptView:
    segments: list[dict[str, Any]]  # prompt-safe: withheld segments removed
    speakers: dict[str, str]  # speaker_id -> salesperson | customer | unknown
    withheld_ids: frozenset[str]
    withheld_grams: frozenset[tuple[str, ...]]


class ProviderFailure(RuntimeError):
    def __init__(self, outcome: str, usage: dict[str, Any] | None = None) -> None:
        super().__init__(outcome)
        self.outcome, self.usage = outcome, usage


async def active_endpoints(session: Any) -> int:
    from sqlalchemy import func, select

    from ac_platform.partner_events.models import (
        PartnerHandoverRecipient,
        PartnerWebhookEndpoint,
    )

    count = await session.scalar(
        select(func.count())
        .select_from(PartnerWebhookEndpoint)
        .where(PartnerWebhookEndpoint.status == "active")
    )
    # 0102: a hand-over recipient may be an organisation's only one.
    recipients = await session.scalar(
        select(func.count())
        .select_from(PartnerHandoverRecipient)
        .where(PartnerHandoverRecipient.status == "active")
    )
    return int(count or 0) + int(recipients or 0)


# Newest live report per call, of a workspace with an active endpoint that takes
# analysis.completed, not one of our test sources, with no event row yet.
_REPORTS = """
    SELECT p.id AS endpoint_id, p.events, p.facts_profile,
           d.id AS draft_id, d.tenant_id, d.recording_id, d.run_id, d.source_sha256,
           d.payload ->> 'transcript_revision' AS transcript_revision, d.created_at,
           s.submission_id
    FROM partner_webhook_endpoints p
    JOIN conversation_report_drafts d
      ON d.tenant_id = p.tenant_id AND d.erased_at IS NULL
     AND d.created_at > p.events_since
     AND d.created_at > :since AND d.created_at <= :until
    JOIN conversation_guest_submissions s
      ON s.recording_id = d.recording_id AND s.tenant_id = d.tenant_id
    WHERE p.status = 'active'
      AND CAST(p.events AS jsonb) @> CAST(:event_types AS jsonb)
      AND NOT (d.source_sha256 = ANY(CAST(:tests AS text[])))
      AND (d.created_at, d.id) > (:after_created, :after_id)
      AND d.created_at = (
        SELECT max(n.created_at) FROM conversation_report_drafts n
        WHERE n.recording_id = d.recording_id AND n.erased_at IS NULL
      )
      AND NOT EXISTS (
        SELECT 1 FROM partner_webhook_events e
        WHERE e.tenant_id = d.tenant_id AND e.report_draft_id = d.id
      )
    ORDER BY d.created_at, d.id
    LIMIT :limit
"""


async def _reports(
    session: Any,
    *,
    since: datetime,
    until: datetime,
    tests: set[str] | frozenset[str],
    after: tuple[datetime, UUID] | None,
    limit: int,
) -> list[Candidate]:
    from sqlalchemy import text

    after_created, after_id = after or _START
    rows = (
        await session.execute(
            text(_REPORTS),
            {
                "since": since,
                "until": until,
                "event_types": json.dumps([EVENT_TYPE]),
                "tests": sorted(tests),
                "after_created": after_created,
                "after_id": after_id,
                "limit": limit,
            },
        )
    ).mappings()
    found = []
    for row in rows:
        events = row["events"] if isinstance(row["events"], list) else []
        revision = row["transcript_revision"]
        found.append(
            Candidate(
                endpoint_id=row["endpoint_id"],
                events=tuple(str(item) for item in events),
                facts_profile=row["facts_profile"],
                draft_id=row["draft_id"],
                tenant_id=row["tenant_id"],
                recording_id=row["recording_id"],
                run_id=row["run_id"],
                source_sha256=row["source_sha256"],
                transcript_revision=str(revision or ""),
                created_at=row["created_at"],
                submission_id=row["submission_id"],
                skip=None if revision else REVISION_MISSING,
            )
        )
    return found


async def candidates(
    session: Any,
    *,
    now: datetime,
    recent_hours: int,
    limit: int,
    tests: set[str] | frozenset[str] = frozenset(),
    after: tuple[datetime, UUID] | None = None,
) -> list[Candidate]:
    """One page of newest reports without an event row, oldest first, after ``after``."""
    return await _reports(
        session,
        since=now - timedelta(hours=recent_hours),
        until=now,
        tests=tests,
        after=after,
        limit=limit,
    )


async def aged_out(
    session: Any,
    *,
    now: datetime,
    recent_hours: int,
    limit: int,
    tests: set[str] | frozenset[str] = frozenset(),
) -> list[Candidate]:
    """Reports that left the recent window without an event row (looked for 30 days back)."""
    since = now - timedelta(hours=recent_hours)
    return await _reports(
        session,
        since=since - AGE_OUT_LOOKBACK,
        until=since,
        tests=tests,
        after=None,
        limit=limit,
    )


async def test_sources(session: Any) -> set[str]:
    """Our own test calls (canary fixture and anything a canary submitted)."""
    from ac_platform.conversation_intelligence.pointer_review_cli import _test_source_shas

    shas: set[str] = await session.run_sync(lambda sync: _test_source_shas(sync.connection()))
    return shas


def final_refusal(line: dict[str, Any]) -> str | None:
    """The refusal in a candidate's line that means its data must never leave, if any."""
    for key in ("facts_wait", "enqueue_refused"):
        value = line.get(key)
        if value in DROP_REFUSALS:
            return str(value)
    outcome = line.get("facts_outcome")
    if isinstance(outcome, str) and outcome.startswith("refused_"):
        reason = outcome.removeprefix("refused_")
        if reason in DROP_REFUSALS:
            return reason
    return None


async def _revision(session: Any, draft_id: UUID, recording_id: UUID, created: datetime) -> int:
    from sqlalchemy import text

    count = await session.scalar(
        text(
            """
            SELECT count(*) FROM conversation_report_drafts
            WHERE recording_id = :recording AND (created_at, id) <= (:created, :id)
            """
        ),
        {"recording": recording_id, "created": created, "id": draft_id},
    )
    return max(1, int(count or 1))


async def record_final(
    sessions: Any, candidate: Candidate, reason: str, *, clock: Callable[[], datetime]
) -> dict[str, Any]:
    """A final ``dropped`` row for (endpoint, report): never sent, no payload, a reason code.

    Idempotent per endpoint and report; the report is no longer a candidate.
    """
    from sqlalchemy.dialects.postgresql import insert

    from ac_platform.partner_events.models import PartnerWebhookEvent

    async with sessions() as session, session.begin():
        now = clock()
        revision = await _revision(
            session, candidate.draft_id, candidate.recording_id, candidate.created_at
        )
        inserted = await session.scalar(
            insert(PartnerWebhookEvent)
            .values(
                id=uuid4(),
                endpoint_id=candidate.endpoint_id,
                tenant_id=candidate.tenant_id,
                recording_id=candidate.recording_id,
                report_draft_id=candidate.draft_id,
                submission_id=candidate.submission_id,
                event_type=EVENT_TYPE,
                analysis_revision=revision,
                supersedes_event_id=None,
                payload=None,
                payload_sha256=NO_BODY_SHA256,
                status="dropped",
                attempts=0,
                replayed_attempts=0,
                next_attempt_at=now,
                leased_until=None,
                delivered_at=None,
                last_http_status=None,
                last_error_code=reason[:64],
                created_at=now,
                erased_at=now,
            )
            .on_conflict_do_nothing(constraint="uq_partner_webhook_event_draft")
            .returning(PartnerWebhookEvent.id)
        )
    return {"final": reason} if inserted is not None else {"event": "exists"}


async def transcript_view(session: Any, candidate: Candidate) -> TranscriptView:
    """The saved transcript as the model may see it, and who each speaker is."""
    from sqlalchemy import select

    from ac_platform.conversation_intelligence.guest_models import ConversationGuestSubmission
    from ac_platform.conversation_intelligence.models import ConversationReportDraft
    from ac_platform.conversation_intelligence.sensitive_segments import grams
    from ac_platform.conversation_intelligence.sensitive_segments_store import (
        withheld_plan_for,
    )
    from ac_platform.conversation_intelligence.speaker_map import resolve_speaker_map
    from ac_platform.conversation_intelligence.speaker_map_models import (
        ConversationSpeakerMapRevision,
    )
    from ac_platform.partner_events.payload import uploader

    draft = await session.get(ConversationReportDraft, candidate.draft_id)
    normalized = (draft.transcript or {}).get("normalized") if draft is not None else None
    if not isinstance(normalized, dict) or not isinstance(normalized.get("segments"), list):
        return TranscriptView([], {}, frozenset(), frozenset())
    plan = await withheld_plan_for(
        session,
        recording_id=candidate.recording_id,
        served_revisions=[candidate.transcript_revision],
    )
    segments = [
        segment
        for segment in normalized["segments"]
        if isinstance(segment, dict)
        and str(segment.get("id")) not in plan.segment_ids
        and not (plan.grams and grams(str(segment.get("text") or "")) & plan.grams)
    ]
    submission = await session.scalar(
        select(ConversationGuestSubmission).where(
            ConversationGuestSubmission.tenant_id == candidate.tenant_id,
            ConversationGuestSubmission.submission_id == candidate.submission_id,
        )
    )
    saved = await session.scalar(
        select(ConversationSpeakerMapRevision)
        .where(
            ConversationSpeakerMapRevision.tenant_id == candidate.tenant_id,
            ConversationSpeakerMapRevision.submission_id == candidate.submission_id,
        )
        .order_by(ConversationSpeakerMapRevision.revision.desc())
        .limit(1)
    )
    person = (
        await uploader(session, candidate.tenant_id, submission.usage_id)
        if submission is not None
        else None
    )
    user_revision: Any = (
        {
            "transcript_revision": saved.transcript_revision,
            "speakers": list(saved.speakers or []),
            "revision": saved.revision,
        }
        if saved is not None
        else None
    )
    try:
        resolved = resolve_speaker_map(
            normalized,
            account_holder_name=person.name if person is not None else None,
            user_revision=user_revision,
        )
        speakers = {
            str(row["speaker_id"]): speaker_label(row.get("role"))
            for row in resolved.get("speakers") or []
        }
    except (KeyError, TypeError, ValueError):
        speakers = {}
    return TranscriptView(segments, speakers, plan.segment_ids, plan.grams)


def _within_withheld(fact: dict[str, Any], view: TranscriptView) -> bool:
    from ac_platform.conversation_intelligence.sensitive_segments import grams, strings

    sources = [fact.get("source")] + [item.get("source") for item in fact.get("alternatives") or []]
    if any(
        isinstance(source, dict) and source.get("segment_id") in view.withheld_ids
        for source in sources
    ):
        return True
    if not view.withheld_grams:
        return False
    return any(grams(value) & view.withheld_grams for value in strings(fact.get("value")))


def withhold_facts(facts: list[dict[str, Any]], view: TranscriptView) -> list[dict[str, Any]]:
    """Facts touching a segment marked sensitive since extraction never leave."""
    kept = []
    for fact in facts:
        if fact.get("status") != "unknown" and _within_withheld(fact, view):
            if fact.get("type") in SINGLE_TYPES:
                kept.append(unknown(str(fact["type"])))
            continue
        kept.append(fact)
    return kept


def _est_paise(usage: dict[str, Any]) -> int:
    from ac_platform.conversation_intelligence.pointer_review_cli import _est_paise

    return _est_paise(usage)


async def extract(
    sessions: Any,
    candidate: Candidate,
    *,
    apply: bool,
    daily_cap: int,
    call_provider: Callable[[dict[str, Any]], dict[str, Any]],
    clock: Callable[[], datetime],
) -> tuple[Extraction | None, dict[str, Any]]:
    """The candidate's extraction when ready (complete, failed or skipped), else None to wait.

    At most one paid provider call per invocation; a failed first attempt is
    retried on a later pass, and a second failure sends the event with
    extraction ``failed``. Waiting (an attempt in flight, the daily cap) is
    decided before the transcript is read.
    """
    if not candidate.facts_profile:
        return Extraction("skipped", None), {}
    profile = load_profile(candidate.facts_profile)
    report = candidate.report
    async with sessions() as session:
        saved = await ledger.complete_facts(session, report, profile.name)
        if (
            saved is not None
            and saved.payload is not None
            and payload_sha256(saved.payload) == saved.payload_sha256
        ):
            return Extraction("complete", profile.name, list(saved.payload["facts"])), {
                "facts": "saved"
            }
        events = await ledger.history(session, report, profile.name)
        left = ledger.attempts_left(events, clock())
        if left == "attempts_exhausted":
            return Extraction("failed", profile.name), {"facts": "failed"}
        if left is not None:
            return None, {"facts_wait": left}
        if await ledger.attempts_today(session, clock()) >= daily_cap:
            return None, {"facts_wait": "daily_cap"}
        view = await transcript_view(session, candidate)
    try:
        system, user = build_prompt(profile, view.segments, view.speakers)
    except QuoteFactsError:
        return Extraction("failed", profile.name), {"facts": "transcript_empty"}
    digest = prompt_sha256(profile, system, user)
    if not apply:
        return None, {"facts": "would_extract", "prompt_chars": len(system) + len(user)}
    async with sessions() as session, session.begin():
        claimed = await ledger.claim(
            session, report, profile, prompt_digest=digest, daily_cap=daily_cap, now=clock()
        )
    if claimed.attempt_id is None:
        if claimed.refused == "attempts_exhausted":
            return Extraction("failed", profile.name), {"facts": "failed"}
        return None, {"facts_wait": claimed.refused}
    line: dict[str, Any] = {"facts_attempt": claimed.attempt}
    usage: dict[str, Any] | None = None
    facts: list[dict[str, Any]] = []
    outcome = "runner_error"
    try:
        response = await asyncio.to_thread(call_provider, gemini_body(profile, system, user))
        usage = dict(response.get("usageMetadata") or {})
        try:
            facts, dropped = parse_facts(decode_gemini(response), view.segments, view.speakers)
        except QuoteFactsError:
            raise ProviderFailure("parse_failed", usage) from None
        line["facts_dropped"] = dropped
        async with sessions() as session, session.begin():
            outcome = await ledger.save_complete(
                session,
                report,
                profile,
                claimed,
                facts=facts,
                prompt_digest=digest,
                usage=usage,
                now=clock(),
            )
    except ProviderFailure as failure:
        outcome, usage = failure.outcome, failure.usage or usage
    finally:
        if outcome != "saved" and not outcome.startswith("refused_"):
            # A provider or runner failure. If this write fails too, the start
            # without an outcome stays an uncertain attempt, counted as spent.
            async with sessions() as session, session.begin():
                await ledger.save_failed(
                    session,
                    report,
                    profile,
                    claimed,
                    error_code=outcome,
                    prompt_digest=digest,
                    usage=usage,
                    now=clock(),
                )
    line["facts_outcome"] = outcome
    if usage:
        line["tokens"] = [usage.get("promptTokenCount"), usage.get("candidatesTokenCount")]
        line["est_paise"] = _est_paise(usage)
    if outcome == "saved":
        return Extraction("complete", profile.name, facts), line
    if outcome.startswith("refused_") or claimed.attempt < ledger.MAX_ATTEMPTS:
        return None, line
    return Extraction("failed", profile.name), line


async def endpoint_chain(session: Any, endpoint_id: UUID) -> list[UUID]:
    """This endpoint and the ones it superseded (a URL change or a secret rotation)."""
    from sqlalchemy import select

    from ac_platform.partner_events.models import PartnerWebhookEndpoint

    chain: list[UUID] = []
    current: UUID | None = endpoint_id
    while current is not None and current not in chain and len(chain) < 64:
        chain.append(current)
        current = await session.scalar(
            select(PartnerWebhookEndpoint.supersedes_endpoint_id).where(
                PartnerWebhookEndpoint.id == current
            )
        )
    return chain


async def enqueue(
    sessions: Any,
    candidate: Candidate,
    extraction: Extraction,
    *,
    app_url: str,
    clock: Callable[[], datetime],
) -> dict[str, Any]:
    """Freeze one event for the candidate's endpoint (idempotent per endpoint and report)."""
    from sqlalchemy import select
    from sqlalchemy.dialects.postgresql import insert

    from ac_platform.conversation_intelligence.models import ConversationReportDraft
    from ac_platform.conversation_intelligence.pointer_review import admission_refusal
    from ac_platform.conversation_intelligence.sensitive_segments import WithheldPlan, withhold
    from ac_platform.partner_events.models import PartnerWebhookEvent

    report = candidate.report
    async with sessions() as session, session.begin():
        now = clock()
        refusal = await session.run_sync(
            lambda sync: admission_refusal(sync.connection(), report, now)
        )
        if refusal is not None:
            return {"enqueue_refused": refusal}
        view = await transcript_view(session, candidate)
        draft = await session.get(ConversationReportDraft, candidate.draft_id)
        assert draft is not None and draft.payload is not None
        raw = draft.payload.get("summary")
        # Withheld words first (on the words as written), then every number as "[n]", cut.
        summary = summary_text(
            withhold(
                raw if isinstance(raw, str) else "",
                WithheldPlan(view.withheld_ids, view.withheld_grams),
            )
        )
        # The newest event this partner may have for the call: same endpoint chain
        # (a URL change or rotation keeps it), never one that was dropped unsent.
        chain = await endpoint_chain(session, candidate.endpoint_id)
        previous = await session.scalar(
            select(PartnerWebhookEvent.id)
            .where(
                PartnerWebhookEvent.tenant_id == candidate.tenant_id,
                PartnerWebhookEvent.recording_id == candidate.recording_id,
                PartnerWebhookEvent.report_draft_id != candidate.draft_id,
                PartnerWebhookEvent.endpoint_id.in_(chain),
                PartnerWebhookEvent.status != "dropped",
            )
            .order_by(PartnerWebhookEvent.created_at.desc(), PartnerWebhookEvent.id.desc())
            .limit(1)
        )
        context = await call_context(
            session,
            draft_id=candidate.draft_id,
            submission_id=candidate.submission_id,
            summary=summary,
            supersedes_event_id=previous,
        )
        if extraction.status == "complete":
            extraction = Extraction(
                "complete", extraction.profile, withhold_facts(extraction.facts, view)
            )
        event_id = uuid4()
        payload = build_event(event_id, context, extraction, app_url=app_url)
        inserted = await session.scalar(
            insert(PartnerWebhookEvent)
            .values(
                id=event_id,
                endpoint_id=candidate.endpoint_id,
                tenant_id=candidate.tenant_id,
                recording_id=candidate.recording_id,
                report_draft_id=candidate.draft_id,
                submission_id=candidate.submission_id,
                event_type=EVENT_TYPE,
                analysis_revision=context.analysis_revision,
                supersedes_event_id=previous,
                payload=payload,
                payload_sha256=body_sha256(payload),
                status="pending",
                attempts=0,
                replayed_attempts=0,
                next_attempt_at=now,
                created_at=now,
            )
            .on_conflict_do_nothing(constraint="uq_partner_webhook_event_draft")
            .returning(PartnerWebhookEvent.id)
        )
    if inserted is None:
        return {"event": "exists"}
    return {
        "event": str(event_id),
        "revision": context.analysis_revision,
        "extraction": payload["extraction"]["status"],
        "facts": len(payload["facts"]),
    }
