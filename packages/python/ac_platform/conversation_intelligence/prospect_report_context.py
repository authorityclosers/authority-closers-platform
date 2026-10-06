"""Local report composition from confirmed, currently readable prior sources.

No copied context is persisted or sent to a provider. Source availability is
rechecked on every read; the generated report's creation time bounds revisions.
"""

from datetime import datetime
from typing import Any
from uuid import UUID

from sqlalchemy import and_, select, tuple_

from ac_platform.conversation_intelligence.acquisition_library import _account_library_query
from ac_platform.conversation_intelligence.acquisition_models import ConversationAcquisitionUsage
from ac_platform.conversation_intelligence.application import utc
from ac_platform.conversation_intelligence.guest_models import ConversationGuestSubmission
from ac_platform.conversation_intelligence.guest_ownership import GuestOwnership
from ac_platform.conversation_intelligence.models import ConversationRecording
from ac_platform.conversation_intelligence.prospect_library import ProspectLibrary
from ac_platform.conversation_intelligence.prospect_models import ConversationProspectMembership
from ac_platform.conversation_intelligence.prospect_store import ProspectStore
from ac_platform.conversation_intelligence.sensitive_segments import WITHHELD_MARKER
from ac_platform.kernel.authz import ActorContext

SCHEMA = "ac.sales-xray.previous-call-context/1"
SOURCE_LIMIT = 3


def _withheld(value: Any) -> bool:
    if isinstance(value, str):
        return WITHHELD_MARKER in value
    if isinstance(value, dict):
        return any(_withheld(item) for item in value.values())
    if isinstance(value, list):
        return any(_withheld(item) for item in value)
    return False


async def previous_call_context(
    ownership: GuestOwnership,
    actor: ActorContext,
    submission_id: UUID,
    *,
    report_created_at: datetime,
) -> dict[str, Any]:
    """Called after report/session admission, inside its recording read fence.

    Six batch queries regardless of history size, including empty history.
    Personal Calls scope is intentional even for organisation-wide readers.
    Suggestions, names and voice matches never establish context membership.
    """
    member, usage, link, recording = (
        ConversationProspectMembership,
        ConversationAcquisitionUsage,
        ConversationGuestSubmission,
        ConversationRecording,
    )

    def visible() -> Any:
        return _account_library_query(actor, utc(ownership.clock())).with_only_columns(
            usage.submission_id
        )

    current = (
        await ownership.database.execute(
            select(member.id, member.prospect_id, usage.created_at)
            .join(
                usage,
                and_(
                    usage.tenant_id == member.tenant_id, usage.submission_id == member.submission_id
                ),
            )
            .where(
                member.tenant_id == ownership.tenant_id,
                member.tenant_id == actor.tenant_id,
                member.submission_id == submission_id,
                member.ended_at.is_(None),
                member.submission_id.in_(visible()),
            )
        )
    ).one_or_none()
    query = (
        select(member.id, usage.submission_id, usage.created_at, recording)
        .join(
            link,
            and_(link.tenant_id == member.tenant_id, link.submission_id == member.submission_id),
        )
        .join(usage, and_(usage.id == link.usage_id, usage.tenant_id == link.tenant_id))
        .join(
            recording,
            and_(recording.id == link.recording_id, recording.tenant_id == link.tenant_id),
        )
        .where(
            member.tenant_id == ownership.tenant_id,
            member.tenant_id == actor.tenant_id,
            member.prospect_id == (current.prospect_id if current else None),
            member.ended_at.is_(None),
            usage.submission_id != submission_id,
            usage.submission_id.in_(visible()),
            tuple_(usage.created_at, usage.submission_id)
            < (current.created_at if current else report_created_at, submission_id),
            usage.created_at <= report_created_at,
        )
        .order_by(usage.created_at.desc(), usage.submission_id.desc())
        .limit(SOURCE_LIMIT)
    )
    locked = (
        await ownership.database.execute(query.with_for_update(of=recording, read=True))
    ).all()
    # Never substitute an unlocked source after waiting on an erasure fence.
    rows = (
        await ownership.database.execute(
            query.where(
                member.id.in_([row[0] for row in locked]), usage.submission_id.in_(visible())
            )
        )
    ).all()
    snapshots = await ProspectLibrary(ProspectStore(ownership))._snapshots(
        [row[3] for row in rows], include_context=True, as_of=report_created_at
    )
    sources = []
    for membership_id, submission, created, rec in reversed(rows):
        snapshot = snapshots.get(rec.id)
        if snapshot is None:
            continue
        quotes = [item for item in snapshot["source_quotes"] if not _withheld(item)]
        interpretations = [item for item in snapshot["interpretations"] if not _withheld(item)]
        if not quotes:
            continue
        sources.append(
            {
                "membership_id": str(membership_id),
                "submission_id": str(submission),
                "recording_id": str(rec.id),
                "call_created_at": created.isoformat(),
                "report_url": f"/analysis/calls/{submission}",
                "reference": {
                    key: snapshot[key]
                    for key in (
                        "snapshot_id",
                        "snapshot_kind",
                        "source_revision",
                        "source_sha256",
                        "transcript_revision",
                        "report_sha256",
                        "report_created_at",
                        "transcript_checkpoint_id",
                        "transcript_manifest_sha256",
                    )
                },
                "source_quotes": quotes,
                "report_interpretations": interpretations,
            }
        )
    return {
        "schema": SCHEMA,
        "composition": "local_source_citations",
        "membership_id": str(current.id) if current else None,
        "prospect_id": str(current.prospect_id) if current else None,
        "sources": sources,
    }
