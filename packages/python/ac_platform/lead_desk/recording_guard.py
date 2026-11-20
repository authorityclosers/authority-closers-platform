"""One recording, one call (Oppo CPH2835 at Wise Life, 19 and 20 Nov 2026).

A seller's phone sent the previous call's recording for the next call, twice in two days: the
same audio (one source_sha256) went on two calls, and the later call's own recording never
came. The phone now refuses such a file itself (sales-xray-apps PR 36); this is the server's
own check, in the same transaction as the attach (LeadDesk.attach_recording):

- the same recording for the same call again changes nothing (the same submission on the same
  lead, or the same audio on the same call);
- audio already on another call in the workspace is not put on this one. The request is refused
  with DUPLICATE (409, try again): the phone looks for this call's own recording. A durable
  audit event ``capture.duplicate_recording`` records it in a transaction of its own
  (``record``), since the refusal rolls the request's back;
- on PostgreSQL the check holds a transaction lock per workspace and audio, so two calls can't
  take one recording at once.

Only the hash's first 12 characters are kept in the audit event.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any
from uuid import UUID

from sqlalchemy import select, text

from ac_platform.audit.service import AuditRepository
from ac_platform.conversation_intelligence.acquisition_models import (
    ConversationAcquisitionUsage,
)
from ac_platform.lead_desk.errors import DeskError
from ac_platform.lead_desk.models import LeadEvent

if TYPE_CHECKING:
    from ac_platform.lead_desk.store import LeadDesk

ACTION = "capture.duplicate_recording"
RESOURCE = "lead_desk.call_recording"
DUPLICATE = (
    "This recording is already on another call. Your phone looks for this call's own "
    "recording; try again."
)
# Uploads of one audio looked at, at most: a file goes up a handful of times at most.
LOOK_AT = 50


class DuplicateRecording(DeskError):
    """The recording's audio is already on another call: retry with this call's own file."""

    def __init__(self) -> None:
        super().__init__(409, DUPLICATE)


async def source_of(desk: LeadDesk, submission_id: UUID) -> str | None:
    """The uploaded audio's hash, or None when this workspace has no such upload."""
    found: str | None = await desk.db.scalar(
        select(ConversationAcquisitionUsage.source_sha256)
        .where(
            ConversationAcquisitionUsage.tenant_id == desk.tenant_id,
            ConversationAcquisitionUsage.submission_id == submission_id,
        )
        .limit(1)
    )
    return found


async def _holding(desk: LeadDesk, source: str) -> list[LeadEvent]:
    """The workspace's calls whose recording has this audio, oldest first."""
    submissions = (
        await desk.db.scalars(
            select(ConversationAcquisitionUsage.submission_id)
            .where(
                ConversationAcquisitionUsage.tenant_id == desk.tenant_id,
                ConversationAcquisitionUsage.source_sha256 == source,
            )
            .limit(LOOK_AT)
        )
    ).all()
    if not submissions:
        return []
    return list(
        (
            await desk.db.scalars(
                select(LeadEvent)
                .where(
                    LeadEvent.tenant_id == desk.tenant_id,
                    LeadEvent.kind == "call",
                    LeadEvent.data["submission_id"]
                    .as_string()
                    .in_([str(submission) for submission in submissions]),
                )
                .order_by(LeadEvent.created_at)
                .limit(LOOK_AT)
            )
        ).all()
    )


def _data(event: LeadEvent) -> dict[str, Any]:
    return event.data if isinstance(event.data, dict) else {}


def call_of(event: LeadEvent) -> str:
    """The call a recording joined: the call it names, or the recording's own row."""
    return str(_data(event).get("for_call") or event.id)


def same_call(
    event: LeadEvent, lead_id: UUID, submission_id: UUID, call_event_id: UUID | None
) -> bool:
    """This upload on this lead already, or this audio on this very call."""
    if event.lead_id == lead_id and str(_data(event).get("submission_id")) == str(submission_id):
        return True
    return call_event_id is not None and call_of(event) == str(call_event_id)


async def already_here(
    desk: LeadDesk, lead_id: UUID, submission_id: UUID, call_event_id: UUID | None
) -> bool:
    """True when this recording is already on this call (nothing to add); False when it may be
    added. Raises DuplicateRecording when its audio is on another call."""
    source = await source_of(desk, submission_id)
    if source is None:
        return False
    if getattr(getattr(desk.db.get_bind(), "dialect", None), "name", None) == "postgresql":
        await desk.db.execute(
            text("SELECT pg_advisory_xact_lock(hashtextextended(:key, 0))"),
            {"key": f"lead-desk-recording:{desk.tenant_id}:{source}"},
        )
    holding = await _holding(desk, source)
    if any(same_call(event, lead_id, submission_id, call_event_id) for event in holding):
        return True
    if holding:
        raise DuplicateRecording()
    return False


async def record(
    desk: LeadDesk, lead_id: UUID, submission_id: UUID, call_event_id: UUID | None
) -> None:
    """The audit event for a refused duplicate, in the caller's (new) transaction."""
    source = await source_of(desk, submission_id)
    holding = await _holding(desk, source) if source else []
    other = next(
        (event for event in holding if not same_call(event, lead_id, submission_id, call_event_id)),
        None,
    )
    await AuditRepository(desk.db).append(
        tenant_id=desk.tenant_id,
        actor_person_id=desk.viewer.person_id,
        session_id=desk.viewer.session_id,
        action=ACTION,
        resource_type=RESOURCE,
        resource_id=str(submission_id),
        payload={
            "lead_id": str(lead_id),
            "call_event_id": str(call_event_id) if call_event_id else None,
            "other_lead_id": str(other.lead_id) if other else None,
            "other_call": call_of(other) if other else None,
            "source_sha256_prefix": (source or "")[:12],
        },
        reason="The same recording was sent for another call",
        now=desk.now,
    )
    await desk.db.flush()
