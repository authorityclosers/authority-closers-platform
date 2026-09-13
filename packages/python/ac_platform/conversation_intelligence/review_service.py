"""Exact-report learner grants and append-only, source-bound review proposals."""

from __future__ import annotations

import json
import secrets
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any, cast
from uuid import UUID, uuid4

from sqlalchemy import func, select

from ac_platform.identity.models import Person
from ac_platform.identity.services import normalize_email
from ac_platform.kernel.authz import ActorContext
from ac_platform.kernel.events import EventCategory, EventEnvelope
from ac_platform.outbox.repository import OutboxRepository
from ac_platform.tenancy.models import Membership, Tenant

from .application import (
    ConversationApplication,
    ConversationConflict,
    ConversationDenied,
    ConversationError,
    ConversationNotFound,
    utc,
)
from .checkpoints import content_hash
from .inference import ConversationInference
from .models import (
    ConversationPermission,
    ConversationRecording,
    ConversationReportDraft,
    ConversationReview,
    ConversationReviewAssignment,
    ConversationReviewFeedback,
    ConversationReviewInvitation,
    ConversationReviewInvitationAcceptance,
    ConversationReviewInvitationRevocation,
    ConversationReviewRevocation,
    ConversationRun,
)
from .provider_admin import ConversationProviderAdmin
from .report_store import ConversationReports, DurableDraftProof
from .reporting_pipeline import ReportingPipeline
from .review import ReviewAssignment as CanonicalAssignment
from .review import RunBinding
from .review_contracts import (
    ReviewAssignment,
    ReviewAssignmentCreateRequest,
    ReviewCheckpointBinding,
    ReviewFeedbackRequest,
    ReviewFeedbackSubmission,
    ReviewInvitationAcceptRequest,
    ReviewInvitationCreateRequest,
    ReviewLens,
    ReviewSourceBinding,
    build_feedback_submission,
    feedback_request_fingerprint,
    validate_submission_with_review_validator,
)
from .review_invitations import (
    REVIEW_INVITATION_EVENT,
    encrypt_invitation_token,
    hash_invitation_token,
)


@dataclass(frozen=True)
class _Evidence:
    recording: ConversationRecording
    run: ConversationRun
    draft: ConversationReportDraft
    transcript: dict[str, Any]
    checkpoint: ReviewCheckpointBinding
    measurement_revision: str
    retention_until: datetime


class ConversationReviewService:
    def __init__(
        self,
        application: ConversationApplication,
        *,
        operations_tenant_id: UUID,
        token_secret: bytes | str | None = None,
    ) -> None:
        self.application = application
        self.database = application.database
        self.operations_tenant_id = operations_tenant_id
        self.token_secret = token_secret

    async def _admin(self, actor: ActorContext) -> datetime:
        if actor.tenant_id != self.operations_tenant_id:
            raise ConversationDenied("Use the AC operations workspace.")
        await ConversationProviderAdmin(self.application).admit(actor)
        return utc(self.application.clock())

    async def _member(self, tenant_id: UUID, person_id: UUID) -> None:
        person = await self.database.scalar(
            select(Person)
            .where(Person.id == person_id)
            .with_for_update(read=True)
            .execution_options(populate_existing=True)
        )
        tenant = await self.database.scalar(
            select(Tenant)
            .where(Tenant.id == tenant_id)
            .with_for_update(read=True)
            .execution_options(populate_existing=True)
        )
        member = await self.database.scalar(
            select(Membership)
            .where(Membership.tenant_id == tenant_id, Membership.person_id == person_id)
            .with_for_update(read=True)
            .execution_options(populate_existing=True)
        )
        if (
            person is None
            or person.status != "active"
            or person.email_verified_at is None
            or tenant is None
            or tenant.status != "active"
            or member is None
            or member.status != "active"
            or member.ended_at is not None
        ):
            raise ConversationDenied("A current verified AC workspace member is required.")

    async def _evidence(
        self, run_id: UUID, now: datetime, *, report_id: UUID | None = None
    ) -> _Evidence:
        run = await self.database.scalar(
            select(ConversationRun)
            .where(ConversationRun.id == run_id)
            .with_for_update(read=True)
            .execution_options(populate_existing=True)
        )
        if run is None:
            raise ConversationNotFound("Review call not found.")
        recording = await self.database.scalar(
            select(ConversationRecording)
            .where(
                ConversationRecording.id == run.recording_id,
                ConversationRecording.tenant_id == run.tenant_id,
                ConversationRecording.person_id == run.person_id,
            )
            .with_for_update(read=True)
            .execution_options(populate_existing=True)
        )
        if (
            recording is None
            or recording.state != "ready"
            or run.state != "completed"
            or recording.generation != run.generation
        ):
            raise ConversationConflict("The review call is no longer available.")
        await self._member(recording.tenant_id, recording.person_id)
        permission = await self.database.scalar(
            select(ConversationPermission)
            .where(
                ConversationPermission.id == recording.permission_id,
                ConversationPermission.tenant_id == recording.tenant_id,
                ConversationPermission.person_id == recording.person_id,
                ConversationPermission.source_sha256 == recording.source_sha256,
            )
            .with_for_update(read=True)
            .execution_options(populate_existing=True)
        )
        if (
            permission is None
            or permission.revoked_at is not None
            or permission.provider != "local"
            or utc(permission.expires_at) <= now
            or utc(permission.retention_until) <= now
            or not permission.permission_reference
            or not permission.retention_reference
        ):
            raise ConversationDenied("Current permission for this exact recording is required.")
        query = select(ConversationReportDraft).where(
            ConversationReportDraft.run_id == run.id,
            ConversationReportDraft.tenant_id == run.tenant_id,
            ConversationReportDraft.person_id == run.person_id,
        )
        if report_id is not None:
            query = query.where(ConversationReportDraft.id == report_id)
        draft = await self.database.scalar(
            query.order_by(
                ConversationReportDraft.created_at.desc(), ConversationReportDraft.id.desc()
            )
            .limit(1)
            .with_for_update(read=True)
            .execution_options(populate_existing=True)
        )
        if draft is None:
            raise ConversationNotFound("A saved report is required before assigning a reviewer.")
        reports = ConversationReports(self.application)
        _, transcript = reports._validated(draft, recording)
        # A private imported report is not proof of a durable checkpoint.
        try:
            proof = DurableDraftProof.model_validate(draft.evidence_receipt)
            await reports._canonical_draft(draft, recording)
            pipeline = ReportingPipeline(ConversationInference(self.application))
            c2, checkpoint = await pipeline.checkpoint(
                recording, proof.transcript_checkpoint_id, "C2"
            )
            _, c5 = await pipeline.checkpoint(recording, proof.coaching_checkpoint_id, "C5")
            _, c4 = await pipeline.parent(recording, c5, "C4")
            _, c3 = await pipeline.parent(recording, c4, "C3")
            _, c1 = await pipeline.parent(recording, c3, "C1")
            binding = ReviewCheckpointBinding(
                id=c2.id,
                tenant_id=c2.tenant_id,
                recording_id=c2.recording_id,
                source_sha256=recording.source_sha256,
                source_revision=recording.source_revision,
                stage="C2",
                revision=checkpoint.revision,
                cache_key=c2.cache_key,
                manifest_sha256=c2.manifest_sha256,
                payload_sha256=c2.payload_sha256,
            )
        except (ValueError, TypeError, KeyError):
            raise ConversationConflict(
                "A verified saved analysis is required for review."
            ) from None
        return _Evidence(
            recording,
            run,
            draft,
            transcript,
            binding,
            c1.revision,
            min(utc(permission.expires_at), utc(permission.retention_until)),
        )

    async def _assignment(self, identifier: UUID) -> ConversationReviewAssignment:
        row = await self.database.scalar(
            select(ConversationReviewAssignment)
            .where(ConversationReviewAssignment.id == identifier)
            .with_for_update()
            .execution_options(populate_existing=True)
        )
        if row is None:
            raise ConversationNotFound("Review assignment not found.")
        return row

    async def _view(self, row: ConversationReviewAssignment, now: datetime) -> ReviewAssignment:
        try:
            assignment = ReviewAssignment.model_validate(row.assignment)
        except ValueError:
            raise ConversationConflict("The review assignment needs repair.") from None
        if (
            content_hash(row.assignment) != row.assignment_sha256
            or assignment.id != row.id
            or assignment.tenant_id != row.tenant_id
            or assignment.run_id != row.run_id
            or assignment.reviewer_person_id != row.reviewer_id
            or assignment.created_by_person_id != row.creator_id
            or assignment.source.recording_id != row.recording_id
            or assignment.created_at_epoch != int(utc(row.created_at).timestamp())
            or assignment.expires_at_epoch != int(utc(row.expires_at).timestamp())
        ):
            raise ConversationConflict("The review assignment binding differs.")
        if await self.database.get(ConversationReviewRevocation, row.id) is not None:
            return assignment.model_copy(update={"state": "revoked"})
        if utc(row.expires_at) <= now:
            return assignment.model_copy(update={"state": "expired"})
        submitted = await self.database.scalar(
            select(ConversationReviewFeedback.id)
            .where(ConversationReviewFeedback.assignment_id == row.id)
            .limit(1)
        )
        return assignment.model_copy(update={"state": "submitted" if submitted else "assigned"})

    async def _persist_assignment(
        self,
        *,
        reviewer_person_id: UUID,
        creator_id: UUID,
        allowed_lenses: tuple[ReviewLens, ...],
        expires_at_epoch: int,
        evidence: _Evidence,
        now: datetime,
    ) -> tuple[dict[str, Any], ConversationReviewAssignment]:
        source = evidence.recording
        await self._member(source.tenant_id, reviewer_person_id)
        expires = datetime.fromtimestamp(expires_at_epoch, UTC)
        if expires > evidence.retention_until:
            raise ConversationError(
                "Review expiry must fit the recording permission and retention."
            )
        assignment = ReviewAssignment(
            id=uuid4(),
            tenant_id=source.tenant_id,
            run_id=evidence.run.id,
            run_generation=evidence.run.generation,
            recipe_revision=evidence.run.recipe_revision,
            source=ReviewSourceBinding(
                tenant_id=source.tenant_id,
                recording_id=source.id,
                source_sha256=source.source_sha256,
                source_revision=source.source_revision,
                permission_id=source.permission_id,
                provenance_ref=f"ref:conversation-permission:{source.permission_id}",
            ),
            checkpoint=evidence.checkpoint,
            reviewer_person_id=reviewer_person_id,
            allowed_lenses=allowed_lenses,
            state="assigned",
            created_at_epoch=int(now.timestamp()),
            expires_at_epoch=expires_at_epoch,
            created_by_person_id=creator_id,
        )
        body = assignment.model_dump(mode="json", by_alias=True)
        row = ConversationReviewAssignment(
            id=assignment.id,
            tenant_id=source.tenant_id,
            person_id=source.person_id,
            recording_id=source.id,
            run_id=evidence.run.id,
            reviewer_id=reviewer_person_id,
            creator_id=creator_id,
            report_id=evidence.draft.id,
            assignment=body,
            assignment_sha256=content_hash(body),
            created_at=now,
            expires_at=expires,
        )
        self.database.add(row)
        await self.database.flush()
        return body, row

    async def create(
        self, actor: ActorContext, intent: ReviewAssignmentCreateRequest, key: str
    ) -> dict[str, Any]:
        now = await self._admin(actor)
        # Serialize assignment retries with the same current AC command. This
        # prevents two concurrent first requests from racing the unique receipt.
        await self.database.execute(
            select(func.pg_advisory_xact_lock(739001, actor.person_id.int % (2**31)))
        )
        payload = intent.model_dump(mode="json", by_alias=True)
        replay = await self.application._replay(actor, key, "assign_conversation_review", payload)
        if replay is not None and replay.result_id is not None:
            return (await self._view(await self._assignment(replay.result_id), now)).model_dump(
                mode="json"
            )
        if (
            not int(now.timestamp())
            < intent.expires_at_epoch
            <= int((now + timedelta(days=30)).timestamp())
        ):
            raise ConversationError("Choose an expiry within the next 30 days.")
        evidence = await self._evidence(intent.run_id, now)
        body, row = await self._persist_assignment(
            reviewer_person_id=intent.reviewer_person_id,
            creator_id=actor.person_id,
            allowed_lenses=intent.allowed_lenses,
            expires_at_epoch=intent.expires_at_epoch,
            evidence=evidence,
            now=now,
        )
        await self.application._receipt(
            actor,
            key,
            "assign_conversation_review",
            payload,
            row.id,
            now,
            resource_type="conversation_review_assignment",
        )
        return body

    async def _invitation_view(
        self, row: ConversationReviewInvitation, now: datetime
    ) -> dict[str, Any]:
        acceptance = await self.database.get(ConversationReviewInvitationAcceptance, row.id)
        revoked = await self.database.get(ConversationReviewInvitationRevocation, row.id)
        if acceptance is not None:
            state = "accepted"
        elif revoked is not None:
            state = "revoked"
        elif utc(row.expires_at) <= now:
            state = "expired"
        else:
            state = "pending"
        return {
            "id": str(row.id),
            "run_id": str(row.run_id),
            "invited_email": row.invited_email,
            "allowed_lenses": list(row.allowed_lenses),
            "created_at_epoch": int(utc(row.created_at).timestamp()),
            "expires_at_epoch": int(utc(row.expires_at).timestamp()),
            "state": state,
            "assignment_id": str(acceptance.assignment_id) if acceptance else None,
        }

    async def invite(
        self, actor: ActorContext, intent: ReviewInvitationCreateRequest, key: str
    ) -> dict[str, Any]:
        now = await self._admin(actor)
        await self.database.execute(
            select(func.pg_advisory_xact_lock(739002, actor.person_id.int % (2**31)))
        )
        payload = intent.model_dump(mode="json", by_alias=True)
        replay = await self.application._replay(actor, key, "invite_conversation_review", payload)
        if replay is not None and replay.result_id is not None:
            row = await self.database.get(ConversationReviewInvitation, replay.result_id)
            if row is None:
                raise ConversationConflict("The invitation receipt is missing its resource.")
            return await self._invitation_view(row, now)
        if self.token_secret is None:
            raise ConversationError("Review invitation email is not configured.")
        if not (
            int(now.timestamp())
            < intent.expires_at_epoch
            <= int((now + timedelta(days=30)).timestamp())
        ):
            raise ConversationError("Choose an expiry within the next 30 days.")
        evidence = await self._evidence(intent.run_id, now)
        expires = datetime.fromtimestamp(intent.expires_at_epoch, UTC)
        if expires > evidence.retention_until:
            raise ConversationError(
                "Review expiry must fit the recording permission and retention."
            )
        invitation_id = uuid4()
        token = secrets.token_urlsafe(48)
        row = ConversationReviewInvitation(
            id=invitation_id,
            tenant_id=evidence.recording.tenant_id,
            person_id=evidence.recording.person_id,
            recording_id=evidence.recording.id,
            run_id=evidence.run.id,
            report_id=evidence.draft.id,
            invited_email=normalize_email(intent.invited_email, "invited_email"),
            token_hash=hash_invitation_token(self.token_secret, token),
            encrypted_token=encrypt_invitation_token(self.token_secret, token, invitation_id),
            allowed_lenses=list(intent.allowed_lenses),
            creator_id=actor.person_id,
            created_at=now,
            expires_at=expires,
        )
        self.database.add(row)
        await self.database.flush()
        await OutboxRepository(self.database).enqueue(
            EventEnvelope(
                name=REVIEW_INVITATION_EVENT,
                category=EventCategory.OPERATIONAL,
                aggregate_type="conversation_review_invitation",
                aggregate_id=row.id,
                tenant_id=row.tenant_id,
                payload={"invitation_id": str(row.id)},
                occurred_at=now,
            ),
            dedupe_key=f"conversation-review-invitation:{row.id}",
        )
        await self.application._receipt(
            actor,
            key,
            "invite_conversation_review",
            payload,
            row.id,
            now,
            resource_type="conversation_review_invitation",
        )
        return await self._invitation_view(row, now)

    async def revoke_invitation(
        self, actor: ActorContext, invitation_id: UUID, key: str
    ) -> dict[str, Any]:
        now = await self._admin(actor)
        payload = {"invitation_id": str(invitation_id)}
        replay = await self.application._replay(
            actor, key, "revoke_conversation_review_invitation", payload
        )
        row = await self.database.scalar(
            select(ConversationReviewInvitation)
            .where(ConversationReviewInvitation.id == invitation_id)
            .with_for_update()
        )
        if row is None:
            raise ConversationNotFound("Review invitation not found.")
        if (
            replay is None
            and await self.database.get(ConversationReviewInvitationRevocation, row.id) is None
        ):
            self.database.add(
                ConversationReviewInvitationRevocation(
                    invitation_id=row.id, person_id=actor.person_id, created_at=now
                )
            )
            await self.database.flush()
            await self.application._receipt(
                actor,
                key,
                "revoke_conversation_review_invitation",
                payload,
                row.id,
                now,
                resource_type="conversation_review_invitation",
            )
        return await self._invitation_view(row, now)

    async def accept_invitation(
        self, actor: ActorContext, intent: ReviewInvitationAcceptRequest
    ) -> dict[str, Any]:
        now = await self.application.admit(actor)
        if self.token_secret is None:
            raise ConversationError("Review invitation email is not configured.")
        try:
            token_hash = hash_invitation_token(self.token_secret, intent.token)
        except (UnicodeError, TypeError, ValueError):
            # Keep malformed bearer material indistinguishable from an unknown,
            # expired, revoked, or already-consumed invitation.
            raise ConversationNotFound("Review invitation not found.") from None
        row = await self.database.scalar(
            select(ConversationReviewInvitation)
            .where(ConversationReviewInvitation.token_hash == token_hash)
            .with_for_update()
        )
        # All invalid, expired, revoked, consumed, tenant, and email mismatch
        # cases intentionally share this response to prevent invitation probing.
        if row is None or row.tenant_id != actor.tenant_id or utc(row.expires_at) <= now:
            raise ConversationNotFound("Review invitation not found.")
        if await self.database.get(ConversationReviewInvitationRevocation, row.id) is not None:
            raise ConversationNotFound("Review invitation not found.")
        acceptance = await self.database.get(ConversationReviewInvitationAcceptance, row.id)
        if acceptance is not None:
            if acceptance.accepted_person_id != actor.person_id:
                raise ConversationNotFound("Review invitation not found.")
            return (
                await self._view(await self._assignment(acceptance.assignment_id), now)
            ).model_dump(mode="json", by_alias=True)
        person = await self.database.scalar(
            select(Person)
            .where(Person.id == actor.person_id)
            .with_for_update(read=True)
            .execution_options(populate_existing=True)
        )
        if person is None or person.email is None or person.email_verified_at is None:
            raise ConversationNotFound("Review invitation not found.")
        try:
            normalized_actor_email = normalize_email(person.email, "email")
        except ValueError:
            raise ConversationNotFound("Review invitation not found.") from None
        if normalized_actor_email != row.invited_email:
            raise ConversationNotFound("Review invitation not found.")
        await self._member(row.tenant_id, actor.person_id)
        evidence = await self._evidence(row.run_id, now, report_id=row.report_id)
        if (
            evidence.recording.id != row.recording_id
            or evidence.recording.tenant_id != row.tenant_id
            or evidence.recording.person_id != row.person_id
            or evidence.draft.id != row.report_id
        ):
            raise ConversationConflict("The invitation's saved review binding differs.")
        if not isinstance(row.allowed_lenses, list):
            raise ConversationConflict("The invitation's lens binding differs.")
        if not 1 <= len(row.allowed_lenses) <= 3 or any(
            not isinstance(lens, str) for lens in row.allowed_lenses
        ):
            raise ConversationConflict("The invitation's lens binding differs.")
        allowed_lenses = tuple(row.allowed_lenses)
        if len(allowed_lenses) != len(set(allowed_lenses)) or any(
            lens not in {"sales", "technical", "ux"} for lens in allowed_lenses
        ):
            raise ConversationConflict("The invitation's lens binding differs.")
        body, assignment = await self._persist_assignment(
            reviewer_person_id=actor.person_id,
            creator_id=row.creator_id,
            allowed_lenses=cast(tuple[ReviewLens, ...], allowed_lenses),
            expires_at_epoch=int(utc(row.expires_at).timestamp()),
            evidence=evidence,
            now=now,
        )
        self.database.add(
            ConversationReviewInvitationAcceptance(
                invitation_id=row.id,
                accepted_person_id=actor.person_id,
                assignment_id=assignment.id,
                created_at=now,
            )
        )
        await self.database.flush()
        await self.application._receipt(
            actor,
            f"review-invitation:{row.id}",
            "accept_conversation_review_invitation",
            {"invitation_id": str(row.id)},
            assignment.id,
            now,
            resource_type="conversation_review_assignment",
        )
        return body

    async def list_assignments(self, actor: ActorContext, limit: int = 50) -> dict[str, Any]:
        now = await self._admin(actor)
        if type(limit) is not int or not 1 <= limit <= 50:
            raise ConversationError("Choose at most 50 assignments.")
        rows = (
            await self.database.scalars(
                select(ConversationReviewAssignment)
                .order_by(
                    ConversationReviewAssignment.created_at.desc(),
                    ConversationReviewAssignment.id.desc(),
                )
                .limit(limit)
            )
        ).all()
        return {
            "items": [
                (await self._view(row, now)).model_dump(mode="json", by_alias=True) for row in rows
            ]
        }

    async def revoke(self, actor: ActorContext, assignment_id: UUID, key: str) -> dict[str, Any]:
        now = await self._admin(actor)
        payload = {"assignment_id": str(assignment_id)}
        await self.application._replay(actor, key, "revoke_conversation_review", payload)
        row = await self._assignment(assignment_id)
        if await self.database.get(ConversationReviewRevocation, row.id) is None:
            self.database.add(
                ConversationReviewRevocation(
                    assignment_id=row.id, person_id=actor.person_id, created_at=now
                )
            )
            await self.database.flush()
        if (
            await self.application._replay(actor, key, "revoke_conversation_review", payload)
            is None
        ):
            await self.application._receipt(
                actor,
                key,
                "revoke_conversation_review",
                payload,
                row.id,
                now,
                resource_type="conversation_review_assignment",
            )
        return (await self._view(row, now)).model_dump(mode="json", by_alias=True)

    async def _admit(
        self, actor: ActorContext, identifier: UUID
    ) -> tuple[ConversationReviewAssignment, ReviewAssignment, _Evidence, datetime]:
        now = await self.application.admit(actor)
        row = await self._assignment(identifier)
        if row.tenant_id != actor.tenant_id or row.reviewer_id != actor.person_id:
            raise ConversationNotFound("Review assignment not found.")
        assignment = await self._view(row, now)
        if not assignment.is_submittable(int(now.timestamp())):
            raise ConversationDenied("This review assignment has ended.")
        evidence = await self._evidence(row.run_id, now, report_id=row.report_id)
        if (
            assignment.run_generation != evidence.run.generation
            or assignment.recipe_revision != evidence.run.recipe_revision
            or assignment.checkpoint != evidence.checkpoint
            or assignment.source.permission_id != evidence.recording.permission_id
            or row.person_id != evidence.recording.person_id
        ):
            raise ConversationConflict("The assigned call revision differs.")
        return row, assignment, evidence, now

    async def get(self, actor: ActorContext, assignment_id: UUID) -> dict[str, Any]:
        _, assignment, evidence, _ = await self._admit(actor, assignment_id)
        return {
            "assignment": assignment.model_dump(mode="json", by_alias=True),
            "report": evidence.draft.payload,
            "transcript": evidence.transcript,
            "evidence_spans": [
                {
                    "checkpoint_id": str(assignment.checkpoint.id),
                    "span_id": segment["id"],
                    **segment,
                }
                for segment in evidence.transcript["segments"]
            ],
            "audio_source_url": f"/v1/conversation/review-assignments/{assignment_id}/source",
        }

    @staticmethod
    def _feedback_view(row: ConversationReviewFeedback) -> dict[str, Any]:
        if (
            row.erased_at is not None
            or row.payload is None
            or content_hash(row.payload) != row.payload_sha256
        ):
            raise ConversationConflict("Saved feedback is no longer available.")
        try:
            submission = ReviewFeedbackSubmission.model_validate(row.payload)
        except ValueError:
            raise ConversationConflict("Saved feedback needs repair.") from None
        if (
            submission.id != row.id
            or submission.assignment_id != row.assignment_id
            or submission.tenant_id != row.tenant_id
            or submission.reviewer_person_id != row.reviewer_id
            or submission.request_sha256 != row.request_sha256
            or submission.idempotency_key != row.request_key
        ):
            raise ConversationConflict("Saved feedback binding differs.")
        return submission.model_dump(mode="json", by_alias=True)

    async def submissions(self, actor: ActorContext, assignment_id: UUID) -> dict[str, Any]:
        await self._admit(actor, assignment_id)
        rows = (
            await self.database.scalars(
                select(ConversationReviewFeedback)
                .where(ConversationReviewFeedback.assignment_id == assignment_id)
                .order_by(ConversationReviewFeedback.created_at, ConversationReviewFeedback.id)
                .limit(100)
            )
        ).all()
        return {"items": [self._feedback_view(row) for row in rows]}

    async def submit(
        self, actor: ActorContext, assignment_id: UUID, intent: ReviewFeedbackRequest
    ) -> dict[str, Any]:
        row, assignment, evidence, now = await self._admit(actor, assignment_id)
        # A request key is unique per assignment; lock the assignment while
        # checking and appending so concurrent retries return one receipt.
        await self.database.execute(
            select(func.pg_advisory_xact_lock(739002, row.id.int % (2**31)))
        )
        fingerprint = feedback_request_fingerprint(intent)
        prior = await self.database.scalar(
            select(ConversationReviewFeedback).where(
                ConversationReviewFeedback.assignment_id == row.id,
                ConversationReviewFeedback.request_key == intent.idempotency_key,
            )
        )
        if prior is not None:
            if prior.request_sha256 != fingerprint:
                raise ConversationConflict("The request key belongs to different feedback.")
            return self._feedback_view(prior)
        try:
            submission = build_feedback_submission(
                intent,
                assignment=assignment,
                authenticated_reviewer_person_id=actor.person_id,
                existing_span_refs={
                    (assignment.checkpoint.id, segment["id"])
                    for segment in evidence.transcript["segments"]
                },
                now_epoch=int(now.timestamp()),
                submission_id=uuid4(),
            )
            correction = submission.proposed_correction
            if correction is not None and correction.target_layer != "ux_metadata":
                binding = RunBinding(
                    str(row.tenant_id),
                    str(row.run_id),
                    f"{assignment.run_generation}:{assignment.recipe_revision}",
                    str(evidence.transcript["revision"]),
                    evidence.measurement_revision,
                    evidence.draft.profile_sha256,
                )
                proposal = validate_submission_with_review_validator(
                    submission,
                    binding=binding,
                    assignment=CanonicalAssignment(
                        binding, str(actor.person_id), submission.lane, str(row.id)
                    ),
                )
                self.database.add(
                    ConversationReview(
                        id=submission.id,
                        run_id=row.run_id,
                        tenant_id=row.tenant_id,
                        person_id=row.person_id,
                        reviewer_id=actor.person_id,
                        lane=submission.lane,
                        proposal_hash=proposal.proposal_hash,
                        proposal=json.loads(proposal.body_json),
                        created_at=now,
                    )
                )
        except (ValueError, TypeError, KeyError):
            raise ConversationError(
                "Choose evidence and a correction allowed by this assignment."
            ) from None
        body = submission.model_dump(mode="json", by_alias=True)
        self.database.add(
            ConversationReviewFeedback(
                id=submission.id,
                assignment_id=row.id,
                tenant_id=row.tenant_id,
                person_id=row.person_id,
                reviewer_id=actor.person_id,
                recording_id=row.recording_id,
                request_key=intent.idempotency_key,
                request_sha256=fingerprint,
                payload_sha256=content_hash(body),
                payload=body,
                created_at=now,
            )
        )
        await self.database.flush()
        # The envelope is erasable; the audit contains only immutable fingerprints.
        await self.application._receipt(
            actor,
            f"review:{submission.id}",
            "submit_conversation_review",
            {"assignment_id": str(row.id), "feedback_sha256": content_hash(body)},
            submission.id,
            now,
            resource_type="conversation_review_feedback",
        )
        return body

    async def playback(self, actor: ActorContext, assignment_id: UUID) -> dict[str, Any]:
        _, _, evidence, _ = await self._admit(actor, assignment_id)
        recording = evidence.recording
        return {
            "id": str(recording.id),
            "tenant_id": str(recording.tenant_id),
            "source_bytes": recording.source_bytes,
            "source_sha256": recording.source_sha256,
            "content_type": recording.content_type,
        }
