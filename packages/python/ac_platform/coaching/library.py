"""Read the signed-in person's retained call history through canonical report access.

Private views never widen to an administrator's readable teammates. Reading this
projection does not renew a claim, write progress, charge credits or call AI.
"""

from typing import Any, Literal
from uuid import UUID

from sqlalchemy import func, select

from ac_platform.coaching.call import CallCoachingCache, CallCoachingView
from ac_platform.coaching.contracts import CallHistory, CallSummary, CoachingView
from ac_platform.coaching.learner import build_learner, recurring_focus
from ac_platform.coaching.report_adapter import _text, from_report
from ac_platform.coaching.sharing_store import member_name, rep_has_shared, shared_reps
from ac_platform.coaching.team import TeamCoachingView, summarize_team
from ac_platform.conversation_intelligence.acquisition_library import (
    _account_library_query,
    _report_columns,
)
from ac_platform.conversation_intelligence.acquisition_reports import AcquisitionReports
from ac_platform.conversation_intelligence.application import (
    ConversationDenied,
    ConversationError,
    ConversationNotFound,
)
from ac_platform.conversation_intelligence.checkpoints import content_hash
from ac_platform.conversation_intelligence.guest_ownership import GuestOwnership
from ac_platform.conversation_intelligence.inference import binding_for, verified_checkpoint
from ac_platform.conversation_intelligence.models import (
    ConversationCheckpoint,
    ConversationRecording,
    ConversationReportDraft,
    ConversationRun,
)
from ac_platform.conversation_intelligence.submission_label_models import (
    ConversationSubmissionLabelRevision as LabelRevision,
)
from ac_platform.kernel.authz import ActorContext

HISTORY_LIMIT = 40


class CoachingLibrary:
    def __init__(self, ownership: GuestOwnership) -> None:
        self.ownership, self.database = ownership, ownership.database

    async def read_call(
        self, actor: ActorContext, submission_id: UUID, cache: CallCoachingCache
    ) -> CallCoachingView:
        now = await self.ownership.sessions._admit()
        await self.ownership.sessions._owner(None, actor, now, shared_identity_locks=True)
        from ac_platform.conversation_intelligence.acquisition_models import (
            ConversationAcquisitionUsage as Usage,
        )

        usage = await self.database.scalar(
            _account_library_query(actor, now).where(Usage.submission_id == submission_id)
        )
        if usage is None:
            raise ConversationNotFound("This call's coaching is unavailable.")
        # Always reauthorize the retained report before consulting the derived
        # cache. Managers/admins have no private-coaching bypass.
        envelope = await AcquisitionReports(self.ownership).report(
            submission_id, actor=actor, shared_identity_locks=True
        )
        return cache.read(
            envelope,
            submission_id=submission_id,
            created_at=usage.created_at,
            person_id=actor.person_id,
            tenant_id=self.ownership.tenant_id,
        )

    async def read_team(self, actor: ActorContext) -> TeamCoachingView:
        now = await self.ownership.sessions._admit()
        await self.ownership.sessions._owner(None, actor, now, shared_identity_locks=True)
        if not await self.ownership.organisation_call_reader(actor):
            raise ConversationDenied("Team coaching needs current organisation owner/admin access.")
        from ac_platform.conversation_intelligence.acquisition_models import (
            ConversationAcquisitionUsage as Usage,
        )
        from ac_platform.conversation_intelligence.acquisition_models import (
            ConversationVisitorClaim as Claim,
        )

        has_report, state = _report_columns()
        rows = (
            await self.database.execute(
                _account_library_query(actor, now, every_owner=True)
                .add_columns(func.coalesce(Usage.person_id, Claim.person_id), has_report, state)
                .order_by(Usage.created_at.desc(), Usage.submission_id.desc())
                .limit(HISTORY_LIMIT + 1)
            )
        ).all()
        history: list[tuple[UUID, CallHistory]] = []
        pending, unavailable = 0, 0
        reports = AcquisitionReports(self.ownership)
        for usage, owner, ready, plan_state in rows[:HISTORY_LIMIT]:
            if not ready:
                pending += int(plan_state == "active")
                unavailable += int(plan_state != "active")
                continue
            try:
                # Existing organisation report access derives only anonymous
                # counts. No private Coaching view or quote is returned.
                envelope = await reports.report(
                    usage.submission_id,
                    actor=actor,
                    shared_identity_locks=True,
                    allow_organisation_read=True,
                )
                call = from_report(
                    envelope,
                    submission_id=usage.submission_id,
                    created_at=usage.created_at,
                    comparison_key=f"unlinked:{usage.submission_id}",
                )
                if call is None:
                    unavailable += 1
                else:
                    history.append((owner, call))
            except (ConversationError, ValueError, KeyError):
                unavailable += 1
        # Named only after a rep shares (owner decision 2); read fresh.
        shared = await shared_reps(self.database, actor=actor, tenant_id=self.ownership.tenant_id)
        return summarize_team(
            tuple(history),
            person_id=actor.person_id,
            tenant_id=self.ownership.tenant_id,
            pending_calls=pending,
            unavailable_calls=unavailable,
            history_limited=len(rows) > HISTORY_LIMIT,
            shared=tuple((rep.person_id, rep.name, rep.shared_at) for rep in shared),
        )

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
        return await self._learner(actor, actor.person_id, rows, organisation=False)

    async def read_shared(self, actor: ActorContext, rep_person_id: UUID) -> CoachingView:
        """A rep's own Coaching, only while they share it with this owner/admin.

        Private by default (owner decision 10 Oct): org role alone never reads
        it. The share, the viewer's role and the rep's membership are all read
        fresh; every report is re-authorized with existing organisation access.
        """
        now = await self.ownership.sessions._admit()
        await self.ownership.sessions._owner(None, actor, now, shared_identity_locks=True)
        tenant_id = self.ownership.tenant_id
        if (
            rep_person_id == actor.person_id
            or not await self.ownership.organisation_call_reader(actor)
            or not await rep_has_shared(
                self.database, tenant_id=tenant_id, rep_person_id=rep_person_id
            )
        ):
            raise ConversationNotFound("This coaching is not shared with you.")
        has_report, state = _report_columns()
        from ac_platform.conversation_intelligence.acquisition_models import (
            ConversationAcquisitionUsage as Usage,
        )
        from ac_platform.conversation_intelligence.acquisition_models import (
            ConversationVisitorClaim as Claim,
        )

        rows = (
            await self.database.execute(
                _account_library_query(actor, now, every_owner=True)
                .where(func.coalesce(Usage.person_id, Claim.person_id) == rep_person_id)
                .add_columns(has_report, state)
                .order_by(Usage.created_at.desc(), Usage.submission_id.desc())
                .limit(HISTORY_LIMIT + 1)
            )
        ).all()
        view = await self._learner(actor, rep_person_id, rows, organisation=True)
        name = await member_name(self.database, person_id=rep_person_id)
        return view.model_copy(update={"person_id": rep_person_id, "person_name": name})

    async def _learner(
        self, actor: ActorContext, person_id: UUID, rows: Any, *, organisation: bool
    ) -> CoachingView:
        reports = AcquisitionReports(self.ownership)
        history: list[CallHistory] = []
        summaries: list[CallSummary] = []
        pending, unavailable = 0, 0
        names = await self._display_names(
            [usage.submission_id for usage, *_ in rows[:HISTORY_LIMIT]]
        )

        def summary(
            usage: Any,
            state: Literal["ready", "pending", "unavailable"],
            label: str | None = None,
            focus: str | None = None,
        ) -> None:
            summaries.append(
                CallSummary(
                    submission_id=usage.submission_id,
                    call_label=names.get(usage.submission_id) or label or "Sales call",
                    created_at=usage.created_at,
                    state=state,
                    focus_label=focus,
                )
            )

        # Authorize and read every report first (fresh access/withholding on
        # each), then resolve evaluator receipts for all calls in a few queries.
        readable: list[tuple[Any, dict[str, Any]]] = []
        for usage, ready, plan_state in reversed(rows[:HISTORY_LIMIT]):
            if not ready:
                pending += int(plan_state == "active")
                unavailable += int(plan_state != "active")
                summary(usage, "pending" if plan_state == "active" else "unavailable")
                continue
            try:
                envelope = await reports.report(
                    usage.submission_id,
                    actor=actor,
                    shared_identity_locks=True,
                    allow_organisation_read=organisation,
                )
                UUID(envelope["recording_id"]), UUID(envelope["run_id"])
                readable.append((usage, envelope))
            except (ConversationError, ValueError, KeyError):
                unavailable += 1
                summary(usage, "unavailable")
        keys = await self._comparison_keys(actor, [envelope for _, envelope in readable])
        for usage, envelope in readable:
            try:
                call = from_report(
                    envelope,
                    submission_id=usage.submission_id,
                    created_at=usage.created_at,
                    comparison_key=keys.get(
                        (UUID(envelope["recording_id"]), UUID(envelope["run_id"])),
                        f"unlinked:{usage.submission_id}",
                    ),
                )
                if call is None:
                    unavailable += 1
                else:
                    history.append(call)
                # A readable report always has its own call coaching, even
                # when it adds nothing comparable to the learner history.
                summary(
                    usage,
                    "ready",
                    _text(envelope.get("source_label"), 256),
                    next((row.label for row in call.skills if row.mission), None) if call else None,
                )
            except (ConversationError, ValueError, KeyError):
                unavailable += 1
                summary(usage, "unavailable")
        # Summaries were appended oldest first within each pass; show newest first.
        summaries.sort(key=lambda row: (row.created_at, str(row.submission_id)))
        recurring = recurring_focus(tuple(history))
        summaries = [
            row.model_copy(update={"recurring": recurring.get(row.submission_id)})
            for row in summaries
        ]
        view = build_learner(
            tuple(history),
            person_id=person_id,
            tenant_id=self.ownership.tenant_id,
            pending_calls=pending,
            unavailable_calls=unavailable,
            history_limited=len(rows) > HISTORY_LIMIT,
        )
        return view.model_copy(update={"calls": tuple(reversed(summaries))})

    async def _comparison_keys(
        self, actor: ActorContext, envelopes: list[dict[str, Any]]
    ) -> dict[tuple[UUID, UUID], str]:
        """Evaluator comparison keys for authorized reports, in three queries.

        Comparable suggestions need the canonical evaluator receipt; a shared
        candidate profile alone does not link revisions. Only receipt columns
        are loaded, never report or transcript content.
        """
        wanted = {
            (UUID(envelope["recording_id"]), UUID(envelope["run_id"]))
            for envelope in envelopes
            if envelope.get("recovery") is None
        }
        if not wanted:
            return {}
        rows = (
            await self.database.execute(
                select(
                    ConversationReportDraft.recording_id,
                    ConversationReportDraft.run_id,
                    ConversationReportDraft.evidence_receipt,
                    ConversationRun.recipe_revision,
                )
                .join(ConversationRun, ConversationRun.id == ConversationReportDraft.run_id)
                .join(
                    ConversationRecording,
                    ConversationRecording.id == ConversationReportDraft.recording_id,
                )
                .where(
                    ConversationReportDraft.recording_id.in_({key[0] for key in wanted}),
                    ConversationReportDraft.run_id.in_({key[1] for key in wanted}),
                    ConversationReportDraft.tenant_id == actor.tenant_id,
                    ConversationReportDraft.erased_at.is_(None),
                    ConversationReportDraft.payload.is_not(None),
                    ConversationRun.generation == ConversationRecording.generation,
                    ConversationRun.state == "completed",
                )
                .order_by(ConversationReportDraft.created_at.desc())
            )
        ).all()
        receipts: dict[tuple[UUID, UUID], tuple[Any, str | None]] = {}
        for recording_id, run_id, receipt, recipe in rows:
            if (recording_id, run_id) in wanted:
                # The newest draft for an exact recording/run pair wins.
                receipts.setdefault((recording_id, run_id), (receipt, recipe))
        durable: dict[tuple[UUID, UUID], tuple[UUID, str]] = {}
        for key, (proof, recipe) in receipts.items():
            try:
                if (
                    isinstance(proof, dict)
                    and proof.get("schema_id") == "ac.sales-xray.durable-draft-proof/1"
                    and recipe
                ):
                    durable[key] = (UUID(proof["coaching_checkpoint_id"]), recipe)
            except (KeyError, TypeError, ValueError):
                continue  # A malformed receipt stays unlinked, never comparable.
        if not durable:
            return {}
        checkpoints = {
            row.id: row
            for row in (
                await self.database.scalars(
                    select(ConversationCheckpoint).where(
                        ConversationCheckpoint.id.in_({value[0] for value in durable.values()})
                    )
                )
            )
        }
        recordings = {
            row.id: row
            for row in (
                await self.database.scalars(
                    select(ConversationRecording).where(
                        ConversationRecording.id.in_({key[0] for key in durable})
                    )
                )
            )
        }
        keys: dict[tuple[UUID, UUID], str] = {}
        for key, (checkpoint_id, recipe) in durable.items():
            checkpoint, recording = checkpoints.get(checkpoint_id), recordings.get(key[0])
            if checkpoint is None or recording is None:
                continue
            try:
                verified = verified_checkpoint(checkpoint, binding_for(recording))
                keys[key] = evaluator_key(verified.as_dict(), recipe)
            except (ConversationError, KeyError, TypeError, ValueError):
                continue  # Unverifiable lineage stays unlinked, never comparable.
        return keys

    async def _display_names(self, submission_ids: list[UUID]) -> dict[UUID, str]:
        """Owner-chosen call names in one query, for rows already in library scope."""
        if not submission_ids:
            return {}
        rows = (
            await self.database.execute(
                select(LabelRevision.submission_id, LabelRevision.display_name)
                .where(
                    LabelRevision.tenant_id == self.ownership.tenant_id,
                    LabelRevision.submission_id.in_(submission_ids),
                )
                .order_by(LabelRevision.submission_id, LabelRevision.revision.desc())
            )
        ).all()
        names: dict[UUID, str] = {}
        seen: set[UUID] = set()
        for submission_id, display_name in rows:
            if submission_id in seen:
                continue
            seen.add(submission_id)
            # The latest revision wins; a cleared name falls back to the report.
            if display_name:
                names[submission_id] = display_name
        return names


def evaluator_key(manifest: dict[str, Any], recipe: str) -> str:
    """Exclude only the call input hash; retain all evaluator/version boundaries.

    Caller supplies a verified canonical C5, never an arbitrary saved manifest.
    Different prompts, models, languages, qualitative packs, repair conditions
    and one-off benchmark approvals therefore stay separate (AC-SVAL §16).
    This links provisional suggestions, never validates latent skill scores.
    """
    config = {key: value for key, value in manifest["config"].items() if key != "input_sha256"}
    return content_hash([recipe, manifest["revision"], config])
