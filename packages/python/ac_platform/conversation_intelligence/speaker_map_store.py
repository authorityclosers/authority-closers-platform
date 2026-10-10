"""Owner-authored speaker revisions within caller-owned transactions."""

import re
from datetime import UTC, datetime
from typing import Any, cast
from uuid import UUID, uuid4

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from ac_platform.audit.service import AuditRepository
from ac_platform.conversation_intelligence.acquisition_reports import AcquisitionReports
from ac_platform.conversation_intelligence.application import (
    ConversationConflict,
    ConversationDenied,
    ConversationError,
    ConversationNotFound,
    utc,
)
from ac_platform.conversation_intelligence.guest_models import ConversationGuestSubmission
from ac_platform.conversation_intelligence.guest_ownership import GuestOwnership, SubmissionScope
from ac_platform.conversation_intelligence.models import ConversationRecording
from ac_platform.conversation_intelligence.speaker_map import (
    Role,
    SpeakerDecision,
    SpeakerMapRevision,
)
from ac_platform.conversation_intelligence.speaker_map_models import (
    ConversationSpeakerMapRevision,
)
from ac_platform.conversation_intelligence.submission_labels import normalize_display_name
from ac_platform.kernel.authz import ActorContext


def normalize_speaker_decisions(
    speakers: object, transcript: dict[str, Any]
) -> list[SpeakerDecision]:
    """Require every current C2 label exactly once; persist only user-editable fields."""
    if not isinstance(speakers, list) or not 1 <= len(speakers) <= 32:
        raise ConversationError("List between 1 and 32 speakers.")
    known = {row["speaker_id"] for row in transcript["segments"] if row["speaker_id"] is not None}
    decisions: dict[str, SpeakerDecision] = {}
    for row in speakers:
        if not isinstance(row, dict) or not {"speaker_id", "role"} <= row.keys() <= {
            "speaker_id",
            "role",
            "display_name",
            "icon",
        }:
            raise ConversationError("Each speaker needs a label, role and optional name.")
        speaker_id, role = row["speaker_id"], row["role"]
        if (
            not isinstance(speaker_id, str)
            or not 1 <= len(speaker_id) <= 128
            or speaker_id not in known
            or speaker_id in decisions
        ):
            raise ConversationError("List each transcript speaker exactly once.")
        if not isinstance(role, str) or role not in ("you", "salesperson", "prospect", "other"):
            raise ConversationError("Choose a supported speaker role.")
        name = normalize_display_name(row.get("display_name"))
        if name is not None and len(name) > 80:
            raise ConversationError("A speaker name must be at most 80 characters.")
        if speaker_id == "unattributed" and (role != "other" or name is not None):
            raise ConversationError("Unattributed speech must use role other with no name.")
        decisions[speaker_id] = {
            "speaker_id": speaker_id,
            "role": cast(Role, role),
            "display_name": name,
        }
        if "icon" in row:
            icon = row["icon"]
            if icon is not None and (
                not isinstance(icon, str) or re.fullmatch(r"[a-z][a-z0-9-]{0,63}", icon) is None
            ):
                raise ConversationError("Choose a valid speaker icon.")
            if speaker_id == "unattributed" and icon is not None:
                raise ConversationError("Unattributed speech cannot have a speaker icon.")
            decisions[speaker_id]["icon"] = icon
    if decisions.keys() != known or sum(row["role"] == "you" for row in decisions.values()) > 1:
        raise ConversationError("List every speaker and choose at most one as you.")
    return [decisions[key] for key in sorted(decisions)]


async def _owner_scope(
    ownership: GuestOwnership,
    submission_id: UUID,
    actor: ActorContext | None,
    shared_identity_locks: bool,
    *,
    allow_organisation_read: bool = False,
) -> SubmissionScope:
    if actor is None:
        raise ConversationDenied("Sign in and claim this saved call before choosing speakers.")
    scope = await ownership.require_submission_owner(
        submission_id,
        actor=actor,
        shared_identity_locks=shared_identity_locks,
        allow_organisation_read=allow_organisation_read,
    )
    if (
        not scope.claimed_account
        or actor.tenant_id != scope.tenant_id
        or (actor.tenant_id != ownership.tenant_id)
    ):
        raise ConversationDenied("Claim this saved call with the same AC account.")
    return scope


async def _latest(database: AsyncSession, scope: SubmissionScope) -> SpeakerMapRevision | None:
    row = await database.scalar(
        select(ConversationSpeakerMapRevision)
        .where(
            ConversationSpeakerMapRevision.tenant_id == scope.tenant_id,
            ConversationSpeakerMapRevision.submission_id == scope.submission_id,
        )
        .order_by(ConversationSpeakerMapRevision.revision.desc())
        .limit(1)
    )
    if row is None:
        return None
    return {
        "revision": row.revision,
        "transcript_revision": row.transcript_revision,
        "speakers": [cast(SpeakerDecision, dict(speaker)) for speaker in row.speakers],
    }


async def read_speaker_map_revision(
    ownership: GuestOwnership,
    submission_id: UUID,
    *,
    actor: ActorContext | None,
    shared_identity_locks: bool = False,
    allow_organisation_read: bool = False,
) -> SpeakerMapRevision | None:
    scope = await _owner_scope(
        ownership,
        submission_id,
        actor,
        shared_identity_locks,
        allow_organisation_read=allow_organisation_read,
    )
    return await _latest(ownership.database, scope)


async def update_speaker_map(
    ownership: GuestOwnership,
    submission_id: UUID,
    *,
    actor: ActorContext | None,
    expected_revision: int,
    transcript_revision: str,
    speakers: object,
    request_id: str | None = None,
    now: datetime | None = None,
    shared_identity_locks: bool = False,
) -> SpeakerMapRevision:
    """Append under the recording lock; identical retries do not write or audit.

    Resolve C2 inside the lock, never from a client-supplied transcript. The
    caller commits choices and the content-free audit together. No plan is changed.
    """
    if type(expected_revision) is not int or not 0 <= expected_revision <= 50:
        raise ConversationError("A speaker revision between 0 and 50 is required.")
    if not isinstance(transcript_revision, str) or not 1 <= len(transcript_revision) <= 256:
        raise ConversationError("A current transcript revision is required.")
    scope = await _owner_scope(ownership, submission_id, actor, shared_identity_locks)
    recording = await ownership.database.scalar(
        select(ConversationRecording)
        .where(
            ConversationRecording.id == scope.recording_id,
            ConversationRecording.tenant_id == scope.tenant_id,
            ConversationRecording.person_id == scope.processing_person_id,
            ConversationRecording.source_sha256 == scope.source_sha256,
            ConversationRecording.state.in_(("awaiting_upload", "ready")),
        )
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    if (
        recording is None
        or await _owner_scope(ownership, submission_id, actor, shared_identity_locks) != scope
    ):
        raise ConversationNotFound("This upload is unavailable.")
    transcript = await AcquisitionReports(ownership).render_transcript(recording)
    if transcript_revision != transcript["revision"]:
        raise ConversationConflict("The transcript changed. Reload before saving again.")
    normalized = normalize_speaker_decisions(speakers, transcript)
    latest = await _latest(ownership.database, scope)
    if latest is not None and latest["transcript_revision"] == transcript_revision:
        previous = {row["speaker_id"]: row for row in latest["speakers"]}
        for decision in normalized:
            old = previous.get(decision["speaker_id"])
            # Older clients omit icons; only an explicit null clears a saved choice.
            if "icon" not in decision and old is not None and "icon" in old:
                decision["icon"] = old["icon"]
    current_revision = 0 if latest is None else latest["revision"]
    if (
        latest is not None
        and latest["transcript_revision"] == transcript_revision
        and (latest["speakers"] == normalized)
    ):
        return latest
    if expected_revision != current_revision:
        raise ConversationConflict("The speakers changed. Reload before saving again.")
    if current_revision >= 50:
        raise ConversationConflict("This call has reached its speaker revision limit.")
    assert actor is not None
    created_at = utc(now or datetime.now(UTC))
    result: SpeakerMapRevision = {
        "revision": current_revision + 1,
        "transcript_revision": transcript_revision,
        "speakers": normalized,
    }
    ownership.database.add(
        ConversationSpeakerMapRevision(
            id=uuid4(),
            tenant_id=scope.tenant_id,
            submission_id=scope.submission_id,
            revision=result["revision"],
            transcript_revision=transcript_revision,
            speakers=cast(list[dict[str, Any]], normalized),
            actor_person_id=actor.person_id,
            created_at=created_at,
        )
    )
    await ownership.database.flush()
    await AuditRepository(ownership.database).append(
        tenant_id=scope.tenant_id,
        actor_person_id=actor.person_id,
        actor_type="person",
        session_id=actor.session_id,
        action="conversation.speaker_map_changed",
        resource_type="conversation_submission",
        resource_id=scope.submission_id,
        payload={"old_revision": current_revision, "new_revision": result["revision"]},
        request_id=request_id,
        now=created_at,
    )
    return result


async def erase_speaker_maps_for_recording(
    database: AsyncSession, *, tenant_id: UUID, recording_id: UUID
) -> int:
    """Called after canonical recording erasure passes its ownership/lease fences."""
    submission_ids = select(ConversationGuestSubmission.submission_id).where(
        ConversationGuestSubmission.tenant_id == tenant_id,
        ConversationGuestSubmission.recording_id == recording_id,
    )
    result = await database.execute(
        delete(ConversationSpeakerMapRevision).where(
            ConversationSpeakerMapRevision.tenant_id == tenant_id,
            ConversationSpeakerMapRevision.submission_id.in_(submission_ids),
        )
    )
    return int(getattr(result, "rowcount", 0) or 0)


async def erase_speaker_maps_for_person(database: AsyncSession, *, person_id: UUID) -> int:
    """Called by canonical account deletion before membership termination."""
    result = await database.execute(
        delete(ConversationSpeakerMapRevision).where(
            ConversationSpeakerMapRevision.actor_person_id == person_id,
        )
    )
    return int(getattr(result, "rowcount", 0) or 0)
