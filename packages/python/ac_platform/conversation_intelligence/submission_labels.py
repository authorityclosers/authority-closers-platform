"""Owner-controlled labels for retained Sales Xray submissions.

Every public read still passes the canonical acquisition ownership and
retention gate. Writes additionally require an authenticated claimed account
and serialize on the recording row so stale concurrent edits cannot fork the
revision sequence. Label contents never enter the audit chain.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import cast
from unicodedata import category
from uuid import UUID, uuid4

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from ac_platform.audit.service import AuditRepository
from ac_platform.conversation_intelligence.application import (
    ConversationConflict,
    ConversationDenied,
    ConversationError,
    ConversationNotFound,
    utc,
)
from ac_platform.conversation_intelligence.guest_models import ConversationGuestSubmission
from ac_platform.conversation_intelligence.guest_ownership import GuestOwnership
from ac_platform.conversation_intelligence.models import ConversationRecording
from ac_platform.conversation_intelligence.submission_label_models import (
    ConversationSubmissionLabelRevision,
)
from ac_platform.kernel.authz import ActorContext

MAX_DISPLAY_NAME_LENGTH = 120
MAX_LABEL_REVISION = 2_147_483_647
_REVISION_ETAG = re.compile(r'"call-label-(0|[1-9][0-9]{0,9})"\Z')
_BIDI_CONTROLS = frozenset("\u202a\u202b\u202c\u202d\u202e\u2066\u2067\u2068\u2069")


@dataclass(frozen=True, slots=True)
class SubmissionLabel:
    display_name: str | None
    revision: int


def normalize_display_name(value: object) -> str | None:
    """Trim a user title and enforce a 120 Unicode-code-point limit.

    Null clears the label. Empty/whitespace-only strings are rejected so a
    caller cannot accidentally clear a value through an ambiguous encoding.
    """

    if value is None:
        return None
    if not isinstance(value, str):
        raise ConversationError("A call name must be text or null.")
    if any(category(character) in {"Cc", "Cs"} for character in value):
        raise ConversationError("A call name cannot contain controls or invalid Unicode.")
    if any(character in _BIDI_CONTROLS for character in value):
        raise ConversationError("A call name cannot contain text-direction controls.")
    normalized = value.strip()
    # Preserve meaningful joiners and marks within multilingual names, but
    # reject names made entirely of invisible formatting, marks or spaces.
    if not any(category(character)[0] in {"L", "N", "P", "S"} for character in normalized):
        raise ConversationError("A call name must contain a visible character.")
    if len(normalized) > MAX_DISPLAY_NAME_LENGTH:
        raise ConversationError("A call name must be at most 120 characters.")
    return normalized


def format_revision_etag(revision: int) -> str:
    if type(revision) is not int or revision < 0 or revision > MAX_LABEL_REVISION:
        raise ValueError("revision must fit a non-negative SQL integer")
    return f'"call-label-{revision}"'


def parse_revision_etag(value: str | None) -> int:
    match = _REVISION_ETAG.fullmatch(value or "")
    if match is None:
        raise ConversationError('If-Match must be one strong "call-label-N" revision tag.')
    revision = int(match.group(1))
    if revision > MAX_LABEL_REVISION:
        raise ConversationError("The call-name revision is invalid.")
    return revision


async def _latest(
    database: AsyncSession, *, tenant_id: UUID, submission_id: UUID
) -> ConversationSubmissionLabelRevision | None:
    return cast(
        ConversationSubmissionLabelRevision | None,
        await database.scalar(
            select(ConversationSubmissionLabelRevision)
            .where(
                ConversationSubmissionLabelRevision.tenant_id == tenant_id,
                ConversationSubmissionLabelRevision.submission_id == submission_id,
            )
            .order_by(ConversationSubmissionLabelRevision.revision.desc())
            .limit(1)
        ),
    )


async def read_submission_label(
    ownership: GuestOwnership,
    submission_id: UUID,
    *,
    token: str | None = None,
    actor: ActorContext | None = None,
    shared_identity_locks: bool = False,
    allow_organisation_read: bool = False,
) -> SubmissionLabel:
    """Read a label only while the underlying submission is currently readable."""

    scope = await ownership.require_submission_owner(
        submission_id,
        token=token,
        actor=actor,
        shared_identity_locks=shared_identity_locks,
        allow_organisation_read=allow_organisation_read,
    )
    row = await _latest(
        ownership.database, tenant_id=scope.tenant_id, submission_id=scope.submission_id
    )
    return SubmissionLabel(
        display_name=None if row is None else row.display_name,
        revision=0 if row is None else row.revision,
    )


async def update_submission_label(
    ownership: GuestOwnership,
    submission_id: UUID,
    *,
    actor: ActorContext | None,
    expected_revision: int,
    display_name: object,
    request_id: str | None = None,
    now: datetime | None = None,
    shared_identity_locks: bool = False,
) -> SubmissionLabel:
    """Append a label revision under current owner/retention authority.

    Retrying with a stale If-Match revision is harmless: if the requested value
    is already the current value, the current revision is returned without a
    second audit event. A stale competing value receives a conflict.
    """

    if actor is None:
        raise ConversationDenied("Sign in and claim this saved call before renaming it.")
    if (
        type(expected_revision) is not int
        or expected_revision < 0
        or expected_revision > MAX_LABEL_REVISION
    ):
        raise ConversationError("A non-negative call-name revision is required.")
    normalized = normalize_display_name(display_name)

    scope = await ownership.require_submission_owner(
        submission_id, actor=actor, shared_identity_locks=shared_identity_locks
    )
    if (
        not scope.claimed_account
        or actor.tenant_id is None
        or actor.tenant_id != scope.tenant_id
        or actor.tenant_id != ownership.tenant_id
    ):
        raise ConversationDenied(
            "Claim this saved call with the same AC account before renaming it."
        )

    # Deletion and retention expiry lock this row before changing its state.
    # Serialize title writes against those transitions, then run the full owner
    # and permission/retention check again inside that lock.
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
    if recording is None:
        raise ConversationNotFound("This upload is unavailable.")
    current_scope = await ownership.require_submission_owner(
        submission_id, actor=actor, shared_identity_locks=shared_identity_locks
    )
    if (
        not current_scope.claimed_account
        or current_scope.tenant_id != scope.tenant_id
        or current_scope.submission_id != scope.submission_id
        or current_scope.recording_id != scope.recording_id
        or current_scope.processing_lease_id != scope.processing_lease_id
        or current_scope.usage_id != scope.usage_id
        or current_scope.source_sha256 != scope.source_sha256
    ):
        raise ConversationNotFound("This upload is unavailable.")

    latest = await _latest(
        ownership.database, tenant_id=scope.tenant_id, submission_id=scope.submission_id
    )
    current_revision = 0 if latest is None else latest.revision
    current_value = None if latest is None else latest.display_name
    if expected_revision != current_revision:
        if normalized == current_value:
            return SubmissionLabel(display_name=current_value, revision=current_revision)
        raise ConversationConflict("The call name changed. Reload it before saving again.")
    if normalized == current_value:
        return SubmissionLabel(display_name=current_value, revision=current_revision)
    if current_revision >= MAX_LABEL_REVISION:
        raise ConversationConflict("This call name has reached its revision limit.")

    created_at = utc(now or datetime.now(UTC))
    next_revision = current_revision + 1
    ownership.database.add(
        ConversationSubmissionLabelRevision(
            id=uuid4(),
            tenant_id=scope.tenant_id,
            submission_id=scope.submission_id,
            revision=next_revision,
            display_name=normalized,
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
        action="conversation.submission_label_changed",
        resource_type="conversation_submission",
        resource_id=scope.submission_id,
        payload={"old_revision": current_revision, "new_revision": next_revision},
        request_id=request_id,
        now=created_at,
    )
    return SubmissionLabel(display_name=normalized, revision=next_revision)


async def erase_submission_labels_for_recording(
    database: AsyncSession, *, tenant_id: UUID, recording_id: UUID
) -> int:
    """Purge all title content when the canonical private recording erasure completes."""

    submission_ids = select(ConversationGuestSubmission.submission_id).where(
        ConversationGuestSubmission.tenant_id == tenant_id,
        ConversationGuestSubmission.recording_id == recording_id,
    )
    result = await database.execute(
        delete(ConversationSubmissionLabelRevision).where(
            ConversationSubmissionLabelRevision.tenant_id == tenant_id,
            ConversationSubmissionLabelRevision.submission_id.in_(submission_ids),
        )
    )
    return int(getattr(result, "rowcount", 0) or 0)


async def erase_submission_labels_for_person(database: AsyncSession, *, person_id: UUID) -> int:
    """Purge a person's title content in the canonical account-deletion transaction."""

    result = await database.execute(
        delete(ConversationSubmissionLabelRevision).where(
            ConversationSubmissionLabelRevision.actor_person_id == person_id,
        )
    )
    return int(getattr(result, "rowcount", 0) or 0)
