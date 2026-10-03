"""Private speaker-map projection and confirmation; no analysis or usage changes."""

from typing import Any
from uuid import UUID

from sqlalchemy import select

from ac_platform.conversation_intelligence.acquisition_reports import AcquisitionReports
from ac_platform.conversation_intelligence.application import (
    ConversationDenied,
    ConversationNotFound,
)
from ac_platform.conversation_intelligence.guest_ownership import GuestOwnership
from ac_platform.conversation_intelligence.speaker_map import resolve_speaker_map
from ac_platform.conversation_intelligence.speaker_map_store import (
    read_speaker_map_revision,
    update_speaker_map,
)
from ac_platform.identity.models import Person
from ac_platform.identity.sales_xray_profile import _resolved_name
from ac_platform.kernel.authz import ActorContext


async def read_speaker_map(
    ownership: GuestOwnership,
    submission_id: UUID,
    *,
    actor: ActorContext | None,
    shared_identity_locks: bool = False,
) -> dict[str, Any]:
    revision = await read_speaker_map_revision(
        ownership, submission_id, actor=actor, shared_identity_locks=shared_identity_locks
    )
    reports = AcquisitionReports(ownership)
    _, recording = await reports.recording(
        submission_id, actor=actor, shared_identity_locks=shared_identity_locks
    )
    # Only a missing transcript becomes unavailable; ownership/retention failures
    # above remain errors. Conflicting or corrupt retained C2 also stays an error.
    try:
        transcript = await reports.render_transcript(recording)
    except ConversationNotFound:
        transcript = None
    if actor is None:
        raise ConversationDenied("A signed-in call owner is required.")
    person = await ownership.database.scalar(select(Person).where(Person.id == actor.person_id))
    result = resolve_speaker_map(
        transcript,
        account_holder_name=_resolved_name(person) if person is not None else None,
        user_revision=revision,
    )
    result.pop("diagnostics", None)
    result["submission_id"] = str(submission_id)
    # A stale transcript choice is not applied, but its ETag still fences the
    # next append. Returning zero here would make every fresh choice conflict.
    result["user_revision"] = 0 if revision is None else revision["revision"]
    return result


async def confirm_speaker_map(
    ownership: GuestOwnership,
    submission_id: UUID,
    *,
    actor: ActorContext | None,
    expected_revision: int,
    transcript_revision: str,
    speakers: object,
    request_id: str | None = None,
    shared_identity_locks: bool = False,
) -> dict[str, Any]:
    await update_speaker_map(
        ownership,
        submission_id,
        actor=actor,
        expected_revision=expected_revision,
        transcript_revision=transcript_revision,
        speakers=speakers,
        request_id=request_id,
        shared_identity_locks=shared_identity_locks,
    )
    # The caller's transaction retains the recording lock through this read.
    return await read_speaker_map(
        ownership, submission_id, actor=actor, shared_identity_locks=shared_identity_locks
    )
