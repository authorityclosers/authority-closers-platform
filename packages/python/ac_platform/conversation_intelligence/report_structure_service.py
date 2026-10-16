"""Compose existing authorized readers for the additive account Report view."""

from copy import deepcopy
from typing import Any
from uuid import UUID

from ac_platform.conversation_intelligence.acquisition_reports import AcquisitionReports
from ac_platform.conversation_intelligence.application import (
    ConversationConflict,
    ConversationNotFound,
)
from ac_platform.conversation_intelligence.guest_ownership import GuestOwnership
from ac_platform.conversation_intelligence.pointer_review import (
    latest_review,
    merge_into_structure,
    project_structure,
)
from ac_platform.conversation_intelligence.prospect_call_outcome_store import CallOutcomeStore
from ac_platform.conversation_intelligence.prospect_store import ProspectStore
from ac_platform.conversation_intelligence.report_structure import (
    project_final_outcome,
    report_statistics,
)
from ac_platform.conversation_intelligence.sensitive_segments_store import withheld_plan_for
from ac_platform.conversation_intelligence.speaker_map_service import read_speaker_map
from ac_platform.kernel.authz import ActorContext


async def enrich_report_structure(
    envelope: dict[str, Any],
    ownership: GuestOwnership,
    submission_id: UUID,
    *,
    actor: ActorContext | None,
    shared_identity_locks: bool = False,
) -> dict[str, Any]:
    """Sequential reads on the existing transaction; no provider calls or writes.

    The report is already authorized and privacy-projected. Optional missing or
    conflicting retained data stays unavailable; access denials still propagate.
    """
    report = envelope.get("report") or {}
    if (
        actor is None
        or report.get("access") != "claimed_account"
        or not (report.get("content") or {}).get("structure")
    ):
        return envelope
    result = deepcopy(envelope)
    structure = result["report"]["content"]["structure"]
    try:
        transcript = await AcquisitionReports(ownership).transcript(
            submission_id,
            actor=actor,
            shared_identity_locks=shared_identity_locks,
            allow_organisation_read=True,
        )
    except (ConversationNotFound, ConversationConflict):
        transcript = None
    if (
        transcript is not None
        and transcript.get("source_sha256") == envelope.get("source_sha256")
        and transcript.get("revision") == envelope.get("transcript_revision")
    ):
        try:
            speakers = await read_speaker_map(
                ownership,
                submission_id,
                actor=actor,
                shared_identity_locks=shared_identity_locks,
                allow_organisation_read=True,
            )
        except (ConversationNotFound, ConversationConflict):
            speakers = None
        structure["overview"]["call_statistics"] = report_statistics(transcript, speakers)
    try:
        outcome = await CallOutcomeStore(ProspectStore(ownership)).read(actor, submission_id)
    except (ConversationNotFound, ConversationConflict):
        outcome = None
    structure["final_call_outcome"] = project_final_outcome(outcome)
    # Owner decision 16 Oct (rulebook 693645b0): a saved AI pointer review for
    # exactly this run, source and transcript overlays its scores as an AI draft.
    database = getattr(ownership, "database", None)
    if database is None:
        return result
    review = await latest_review(database, envelope)
    if review is None:
        return result
    # The envelope arrived privacy-projected; the AI review overlay adds call
    # words after that, so the canonical projection runs again at read time with
    # current marks, later and other-revision marks included (AUT-2010).
    try:
        recording_id = UUID(str(envelope["recording_id"]))
        revision = str(envelope["transcript_revision"])
    except (KeyError, ValueError):
        return result
    plan = await withheld_plan_for(
        database, recording_id=recording_id, served_revisions=(revision,)
    )
    merged = merge_into_structure(structure, review)
    result["report"]["content"]["structure"] = project_structure(merged, plan)
    return result
