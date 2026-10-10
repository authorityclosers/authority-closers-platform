"""Read the signed-in person's retained call history through canonical report access.

Never widen to an organisation administrator's readable teammates. Reading this
projection does not renew a claim, write progress, charge credits or call AI.
"""

from typing import Any
from uuid import UUID

from sqlalchemy import select

from ac_platform.coaching.contracts import CallHistory, CoachingView
from ac_platform.coaching.learner import build_learner
from ac_platform.coaching.report_adapter import from_report
from ac_platform.conversation_intelligence.acquisition_library import (
    _account_library_query,
    _report_columns,
)
from ac_platform.conversation_intelligence.acquisition_reports import AcquisitionReports
from ac_platform.conversation_intelligence.application import ConversationError
from ac_platform.conversation_intelligence.checkpoints import content_hash
from ac_platform.conversation_intelligence.guest_ownership import GuestOwnership
from ac_platform.conversation_intelligence.inference import binding_for, verified_checkpoint
from ac_platform.conversation_intelligence.models import (
    ConversationCheckpoint,
    ConversationRecording,
    ConversationReportDraft,
    ConversationRun,
)
from ac_platform.kernel.authz import ActorContext

HISTORY_LIMIT = 40


class CoachingLibrary:
    def __init__(self, ownership: GuestOwnership) -> None:
        self.ownership, self.database = ownership, ownership.database

    async def read(self, actor: ActorContext) -> CoachingView:
        now = await self.ownership.sessions._admit()
        await self.ownership.sessions._owner(None, actor, now, shared_identity_locks=True)
        has_report, state = _report_columns()
        from ac_platform.conversation_intelligence.acquisition_models import (
            ConversationAcquisitionUsage as Usage,
        )

        rows = (
            await self.database.execute(
                _account_library_query(
                    actor, now
                )  # Own calls even when actor is an org owner/admin.
                .add_columns(has_report, state)
                .order_by(Usage.created_at.desc(), Usage.submission_id.desc())
                .limit(HISTORY_LIMIT + 1)
            )
        ).all()
        reports = AcquisitionReports(self.ownership)
        history: list[CallHistory] = []
        pending, unavailable = 0, 0
        for usage, ready, plan_state in reversed(rows[:HISTORY_LIMIT]):
            if not ready:
                pending += int(plan_state == "active")
                unavailable += int(plan_state != "active")
                continue
            try:
                envelope = await reports.report(
                    usage.submission_id,
                    actor=actor,
                    shared_identity_locks=True,
                )
                recording_id = UUID(envelope["recording_id"])
                # Comparable suggestions need the canonical evaluator receipt;
                # a shared candidate profile alone does not link revisions.
                draft = await self.database.scalar(
                    select(ConversationReportDraft)
                    .join(ConversationRun, ConversationRun.id == ConversationReportDraft.run_id)
                    .join(
                        ConversationRecording,
                        ConversationRecording.id == ConversationReportDraft.recording_id,
                    )
                    .where(
                        ConversationReportDraft.recording_id == recording_id,
                        ConversationReportDraft.tenant_id == actor.tenant_id,
                        ConversationReportDraft.erased_at.is_(None),
                        ConversationReportDraft.payload.is_not(None),
                        ConversationRun.generation == ConversationRecording.generation,
                        ConversationRun.state == "completed",
                        ConversationReportDraft.run_id == UUID(envelope["run_id"]),
                    )
                    .order_by(ConversationReportDraft.created_at.desc())
                    .limit(1)
                )
                if envelope.get("recovery") is not None:
                    draft = None
                recipe = (
                    await self.database.scalar(
                        select(ConversationRun.recipe_revision).where(
                            ConversationRun.id == UUID(envelope["run_id"])
                        )
                    )
                    if draft is not None
                    else None
                )
                comparison = f"unlinked:{usage.submission_id}"
                proof = draft.evidence_receipt if draft is not None else None
                if (
                    isinstance(proof, dict)
                    and proof.get("schema_id") == "ac.sales-xray.durable-draft-proof/1"
                    and recipe
                ):
                    checkpoint = await self.database.get(
                        ConversationCheckpoint, UUID(proof["coaching_checkpoint_id"])
                    )
                    recording = await self.database.get(ConversationRecording, recording_id)
                    if checkpoint is not None and recording is not None:
                        verified = verified_checkpoint(checkpoint, binding_for(recording))
                        comparison = evaluator_key(verified.as_dict(), recipe)
                call = from_report(
                    envelope,
                    submission_id=usage.submission_id,
                    created_at=usage.created_at,
                    comparison_key=comparison,
                )
                if call is None:
                    unavailable += 1
                else:
                    history.append(call)
            except (ConversationError, ValueError, KeyError):
                unavailable += 1
        return build_learner(
            tuple(history),
            person_id=actor.person_id,
            tenant_id=self.ownership.tenant_id,
            pending_calls=pending,
            unavailable_calls=unavailable,
            history_limited=len(rows) > HISTORY_LIMIT,
        )


def evaluator_key(manifest: dict[str, Any], recipe: str) -> str:
    """Exclude only the call input hash; retain all evaluator/version boundaries.

    Caller supplies a verified canonical C5, never an arbitrary saved manifest.
    Different prompts, models, languages, qualitative packs, repair conditions
    and one-off benchmark approvals therefore stay separate (AC-SVAL §16).
    This links provisional suggestions, never validates latent skill scores.
    """
    config = {key: value for key, value in manifest["config"].items() if key != "input_sha256"}
    return content_hash([recipe, manifest["revision"], config])
