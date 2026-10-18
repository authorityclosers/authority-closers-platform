"""Build ``sx.analysis_completed.v1`` (partner contract, 18 Oct 2026).

``build_event`` is pure: it turns one call's context and its extraction into
the event body exactly as the contract defines it. ``call_context`` reads that
context from the database for one report draft:

- summary and ``overview.outcome.kind`` from the saved report;
- call length from the source-bound C1 checkpoint (``media_duration_ms``);
- the uploader through ``conversation_guest_submissions.usage_id`` ->
  ``conversation_acquisition_usage`` (person, or the claimed visitor) ->
  ``persons``;
- the lead only when the call was uploaded on a Sales X-Ray lead of the same
  workspace (a ``call`` event naming this submission, else the lead's
  ``last_submission_id``);
- the report language from the call's processing plan.

Withheld (sensitive) words never leave: the summary passes the canonical
privacy projection. No price leaves in the summary either: every number in it
reads "[n]" (``summary_mask``); sizes, quantities, dates and spoken prices
arrive only as facts. The body is UTF-8 JSON of at most 256 KB; the summary is
cut to 1,500 characters.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any, Literal
from uuid import UUID

from ac_platform.partner_events.quote_facts import FACT_TYPES, VOCABULARIES
from ac_platform.partner_events.summary_mask import mask_numbers

SCHEMA = "sx.analysis_completed.v1"
EVENT_TYPE = "analysis.completed"
MAX_BODY_BYTES = 256 * 1024
MAX_SUMMARY_CHARS = 1500
ExtractionStatus = Literal["complete", "failed", "skipped"]


@dataclass(frozen=True)
class Person:
    id: UUID | None
    name: str | None
    email: str | None


@dataclass(frozen=True)
class Lead:
    id: UUID
    phone_e164: str | None
    name: str | None
    city: str | None


@dataclass(frozen=True)
class CallContext:
    tenant_id: UUID
    recording_id: UUID
    report_draft_id: UUID
    submission_id: UUID
    completed_at: datetime
    uploaded_at: datetime
    duration_ms: int | None
    report_language: str
    summary: str
    outcome_kind: str | None
    salesperson: Person
    lead: Lead | None
    analysis_revision: int
    supersedes_event_id: UUID | None


@dataclass(frozen=True)
class Extraction:
    status: ExtractionStatus
    profile: str | None
    facts: list[dict[str, Any]] = field(default_factory=list)


def iso(value: datetime) -> str:
    """UTC, whole seconds, with a Z: 2026-10-19T05:14:02Z."""
    moment = value if value.tzinfo else value.replace(tzinfo=UTC)
    return moment.astimezone(UTC).replace(microsecond=0).strftime("%Y-%m-%dT%H:%M:%SZ")


def ref(prefix: str, value: UUID) -> str:
    return f"{prefix}_{value.hex}"


def summary_text(value: Any) -> str:
    """The summary as sent: every number masked as "[n]", then cut to 1,500 characters."""
    text = mask_numbers(value).strip() if isinstance(value, str) else ""
    if len(text) <= MAX_SUMMARY_CHARS:
        return text
    return text[: MAX_SUMMARY_CHARS - 1].rstrip() + "…"


def body_bytes(payload: dict[str, Any]) -> bytes:
    """The exact bytes sent and signed; the same stored payload always gives the same bytes."""
    return json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode(
        "utf-8"
    )


def body_sha256(payload: dict[str, Any]) -> str:
    return hashlib.sha256(body_bytes(payload)).hexdigest()


def build_event(
    event_id: UUID, context: CallContext, extraction: Extraction, *, app_url: str
) -> dict[str, Any]:
    """The event body. A body over 256 KB drops its facts and reads extraction failed."""
    outcome = context.outcome_kind if context.outcome_kind in VOCABULARIES["outcome.kind"] else None
    lead = context.lead
    payload: dict[str, Any] = {
        "schema": SCHEMA,
        "event_id": str(event_id),
        "event_type": EVENT_TYPE,
        "occurred_at": iso(context.completed_at),
        "tenant_ref": ref("ten", context.tenant_id),
        "analysis_id": ref("sub", context.submission_id),
        "analysis_revision": context.analysis_revision,
        "supersedes_event_id": (
            str(context.supersedes_event_id) if context.supersedes_event_id else None
        ),
        "analysis_url": f"{app_url.rstrip('/')}/analysis/calls/{context.submission_id}",
        "call": {
            "uploaded_at": iso(context.uploaded_at),
            "duration_sec": (
                round(context.duration_ms / 1000) if context.duration_ms is not None else None
            ),
            "report_language": context.report_language,
        },
        "salesperson": {
            "ref": ref("per", context.salesperson.id) if context.salesperson.id else None,
            "name": context.salesperson.name,
            "email": context.salesperson.email,
        },
        "lead": (
            {
                "ref": ref("lead", lead.id),
                "phone_e164": lead.phone_e164,
                "name": lead.name,
                "city": lead.city,
            }
            if lead is not None
            else None
        ),
        "summary": summary_text(context.summary),
        "outcome": {"kind": outcome},
        "extraction": {
            "profile": extraction.profile,
            "status": extraction.status,
            "looked_for": list(FACT_TYPES) if extraction.status != "skipped" else [],
        },
        "facts": list(extraction.facts) if extraction.status == "complete" else [],
    }
    if len(body_bytes(payload)) > MAX_BODY_BYTES:
        payload["extraction"]["status"] = "failed"
        payload["facts"] = []
    if len(body_bytes(payload)) > MAX_BODY_BYTES:
        raise ValueError("partner_event_body_too_large")
    return payload


# --- database reads ------------------------------------------------------------------


def _safe_duration(payload: Any) -> int | None:
    if not isinstance(payload, dict):
        return None
    value = payload.get("media_duration_ms")
    return value if type(value) is int and 0 < value <= 14_400_000 else None


def _person_name(display_name: str | None, first_name: str | None) -> str | None:
    value = display_name or first_name
    normalized = " ".join(value.split()) if value else ""
    return normalized or None


async def uploader(session: Any, tenant_id: UUID, usage_id: UUID) -> Person:
    """The person who uploaded the call: the usage owner, or the visitor's claimed person."""
    from sqlalchemy import and_, func, select

    from ac_platform.conversation_intelligence.acquisition_models import (
        ConversationAcquisitionUsage,
        ConversationVisitorClaim,
    )
    from ac_platform.identity.models import Person as PersonRow

    usage, claim = ConversationAcquisitionUsage, ConversationVisitorClaim
    row = (
        await session.execute(
            select(PersonRow.id, PersonRow.display_name, PersonRow.first_name, PersonRow.email)
            .select_from(usage)
            .outerjoin(
                claim,
                and_(claim.visitor_id == usage.visitor_id, claim.tenant_id == usage.tenant_id),
            )
            .join(PersonRow, PersonRow.id == func.coalesce(usage.person_id, claim.person_id))
            .where(usage.id == usage_id, usage.tenant_id == tenant_id)
        )
    ).first()
    if row is None:
        return Person(None, None, None)
    return Person(row.id, _person_name(row.display_name, row.first_name), row.email)


async def call_lead(session: Any, tenant_id: UUID, submission_id: UUID) -> Lead | None:
    """The Sales X-Ray lead this call was uploaded on, in the same workspace only."""
    from sqlalchemy import text

    row = (
        await session.execute(
            text(
                """
                SELECT l.id, l.phone, l.name, l.city
                FROM lead_desk_leads l
                WHERE l.tenant_id = :tenant AND l.id = coalesce(
                  (SELECT e.lead_id FROM lead_desk_events e
                   WHERE e.tenant_id = :tenant AND e.kind = 'call'
                     AND e.data ->> 'submission_id' = :submission
                   ORDER BY e.created_at DESC LIMIT 1),
                  (SELECT x.id FROM lead_desk_leads x
                   WHERE x.tenant_id = :tenant AND x.last_submission_id = :submission_id
                   ORDER BY x.updated_at DESC LIMIT 1))
                """
            ),
            {"tenant": tenant_id, "submission": str(submission_id), "submission_id": submission_id},
        )
    ).first()
    if row is None:
        return None
    return Lead(row.id, row.phone, row.name, row.city)


async def call_context(
    session: Any,
    *,
    draft_id: UUID,
    submission_id: UUID,
    summary: str,
    supersedes_event_id: UUID | None,
) -> CallContext:
    """Everything the event needs about one report draft (``summary`` already projected)."""
    from sqlalchemy import select, text

    from ac_platform.conversation_intelligence.guest_models import ConversationGuestSubmission
    from ac_platform.conversation_intelligence.models import ConversationReportDraft

    draft = await session.get(ConversationReportDraft, draft_id)
    if draft is None or draft.payload is None:
        raise ValueError("partner_event_report_missing")
    submission = await session.scalar(
        select(ConversationGuestSubmission).where(
            ConversationGuestSubmission.tenant_id == draft.tenant_id,
            ConversationGuestSubmission.submission_id == submission_id,
            ConversationGuestSubmission.recording_id == draft.recording_id,
        )
    )
    if submission is None:
        raise ValueError("partner_event_submission_missing")
    c1 = await session.scalar(
        text(
            """
            SELECT payload FROM conversation_checkpoints
            WHERE recording_id = :recording AND tenant_id = :tenant AND stage = 'C1'
              AND erased_at IS NULL AND payload ->> 'source_sha256' = :source
            ORDER BY created_at DESC LIMIT 1
            """
        ),
        {"recording": draft.recording_id, "tenant": draft.tenant_id, "source": draft.source_sha256},
    )
    manifest = await session.scalar(
        text(
            """
            SELECT manifest FROM conversation_processing_plans
            WHERE recording_id = :recording AND tenant_id = :tenant AND erased_at IS NULL
            ORDER BY (created_at <= :completed) DESC, created_at DESC, id DESC LIMIT 1
            """
        ),
        {"recording": draft.recording_id, "tenant": draft.tenant_id, "completed": draft.created_at},
    )
    language = manifest.get("report_language") if isinstance(manifest, dict) else None
    revision = await session.scalar(
        text(
            """
            SELECT count(*) FROM conversation_report_drafts
            WHERE recording_id = :recording
              AND (created_at, id) <= (:created, :id)
            """
        ),
        {"recording": draft.recording_id, "created": draft.created_at, "id": draft.id},
    )
    overview = draft.payload.get("overview")
    outcome = overview.get("outcome") if isinstance(overview, dict) else None
    return CallContext(
        tenant_id=draft.tenant_id,
        recording_id=draft.recording_id,
        report_draft_id=draft.id,
        submission_id=submission_id,
        completed_at=draft.created_at,
        uploaded_at=submission.created_at,
        duration_ms=_safe_duration(c1),
        report_language=language if isinstance(language, str) and language else "en",
        summary=summary,
        outcome_kind=outcome.get("kind") if isinstance(outcome, dict) else None,
        salesperson=await uploader(session, draft.tenant_id, submission.usage_id),
        lead=await call_lead(session, draft.tenant_id, submission_id),
        analysis_revision=max(1, int(revision or 1)),
        supersedes_event_id=supersedes_event_id,
    )
