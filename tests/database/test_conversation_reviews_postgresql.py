"""PostgreSQL proof for server-managed Sales Xray review assignments.

The report fixture runs the real local C1 worker and synthetic reporting broker
through durable C2/C4/C5/C6 checkpoints.  Review assertions then exercise the
service against that saved report; no provider network, credentials, or mocked
database routes are used.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from uuid import UUID

import pytest
from pydantic import ValidationError
from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from ac_platform.conversation_intelligence.application import (
    ConversationApplication,
    ConversationConflict,
    ConversationDenied,
    ConversationNotFound,
)
from ac_platform.conversation_intelligence.inference_tasks import prepare_fact_inputs
from ac_platform.conversation_intelligence.inference_worker import ConversationInferenceWorker
from ac_platform.conversation_intelligence.models import (
    ConversationCheckpoint,
    ConversationPermission,
    ConversationRecording,
    ConversationReportDraft,
    ConversationReview,
    ConversationReviewFeedback,
)
from ac_platform.conversation_intelligence.provider_admin import CONTROL_ACCOUNT
from ac_platform.conversation_intelligence.report_store import (
    ConversationReports,
    DurableDraftProof,
)
from ac_platform.conversation_intelligence.reporting_pipeline import StageRequest
from ac_platform.conversation_intelligence.review_contracts import (
    REVIEW_FEEDBACK_SCHEMA,
    ReviewAssignment,
    ReviewAssignmentCreateRequest,
    ReviewEvidenceRef,
    ReviewFeedbackRequest,
    ReviewFeedbackSubmission,
    ReviewProposedCorrection,
)
from ac_platform.conversation_intelligence.review_service import ConversationReviewService
from ac_platform.identity.models import Person
from ac_platform.kernel.authz import ActorContext
from tests.database.test_conversation_inference_postgresql import _provider_quote
from tests.database.test_conversation_postgresql import run, seed
from tests.database.test_conversation_reporting_pipeline_postgresql import (
    ReportingBroker,
    completed_checkpoint,
    enqueue,
    text_quote,
)
from tests.database.test_conversation_worker_postgresql import (
    Prepared as WorkerPrepared,
)
from tests.database.test_conversation_worker_postgresql import (
    _postgres_harness,
)
from tests.database.test_conversation_worker_postgresql import (
    _prepare as prepare_local,
)


@pytest.fixture(scope="module")
def postgres_harness() -> Any:
    yield from _postgres_harness.__wrapped__()  # type: ignore[attr-defined]


@dataclass(frozen=True)
class ReviewCase:
    prepared: WorkerPrepared
    engine: AsyncEngine
    sessions: async_sessionmaker[AsyncSession]
    source_actor: ActorContext
    admin_actor: ActorContext
    reviewer_actor: ActorContext
    other_reviewer_actor: ActorContext
    foreign_actor: ActorContext
    operations_tenant_id: UUID
    report_run_id: UUID
    checkpoint_id: UUID
    span_id: str


async def _build_report_case(postgres_harness: Any, scratch_root: Path) -> ReviewCase:
    prepared = await prepare_local(postgres_harness, scratch_root)
    assert await prepared.worker.run_once(), "The durable C1 fixture did not complete."
    engine = create_async_engine(postgres_harness.url)
    sessions = async_sessionmaker(engine, expire_on_commit=False)
    try:
        broker = ReportingBroker(prepared.data)
        worker = ConversationInferenceWorker(sessions, prepared.storage, broker)
        source_sha256 = hashlib.sha256(prepared.data).hexdigest()

        quote_id, quote = await _provider_quote(
            sessions,
            prepared.state,
            prepared.recording_id,
            prepared.scope_id,
            source_sha256,
        )
        transcription = await enqueue(
            sessions, prepared, quote_id, quote, None, "review-report-transcription"
        )
        assert await worker.run_once(), "The durable C2 fixture did not complete."
        c2_id = await completed_checkpoint(sessions, transcription)

        async with sessions() as database, database.begin():
            transcript = await ConversationReports(
                ConversationApplication(database, clock=lambda: prepared.state.now)
            ).transcript(prepared.state.actor, prepared.recording_id)
        facts = StageRequest(stage="C4", transcript_checkpoint_id=c2_id, max_input_chars=512)
        chunks = prepare_fact_inputs(transcript, max_input_chars=512)
        fact_ids: list[UUID] = []
        for index in range(1, len(chunks) + 1):
            fact_request = facts.model_copy(update={"chunk_index": index})
            fact_quote_id, fact_quote = await text_quote(sessions, prepared, fact_request)
            fact_view = await enqueue(
                sessions,
                prepared,
                fact_quote_id,
                fact_quote,
                fact_request,
                f"review-report-facts-{index}",
            )
            assert await worker.run_once(), "The durable C4 fixture did not complete."
            fact_ids.append(await completed_checkpoint(sessions, fact_view))

        coaching = StageRequest(
            stage="C5",
            transcript_checkpoint_id=c2_id,
            fact_checkpoint_ids=tuple(fact_ids),
            max_completion_tokens=1_800,
        )
        coaching_quote_id, coaching_quote = await text_quote(sessions, prepared, coaching)
        coaching_view = await enqueue(
            sessions,
            prepared,
            coaching_quote_id,
            coaching_quote,
            coaching,
            "review-report-coaching",
        )
        assert await worker.run_once(), "The durable C5/C6 report fixture did not complete."
        # The queue task is C5; the report's presentation checkpoint is the
        # separately-created C6 row recorded in its durable evidence receipt.
        _ = await completed_checkpoint(sessions, coaching_view)
        report_run_id = UUID(coaching_view["id"])

        async with sessions() as database:
            draft = await database.scalar(
                select(ConversationReportDraft).where(
                    ConversationReportDraft.run_id == report_run_id,
                    ConversationReportDraft.recording_id == prepared.recording_id,
                )
            )
            assert draft is not None and draft.payload is not None
            assert draft.evidence_receipt is not None
            proof = DurableDraftProof.model_validate(draft.evidence_receipt)
            c6_id = proof.presentation_checkpoint_id
            durable_stages = (
                await database.scalars(
                    select(ConversationCheckpoint.stage).where(
                        ConversationCheckpoint.id.in_((c2_id, c6_id))
                    )
                )
            ).all()
            assert set(durable_stages) == {"C2", "C6"}

        reviewer = await seed(engine, tenant_id=prepared.state.tenant_id, role="learner")
        other_reviewer = await seed(engine, tenant_id=prepared.state.tenant_id, role="learner")
        foreign = await seed(engine, role="learner")
        operations = await seed(engine, role="owner")
        async with sessions() as database, database.begin():
            admin_person = await database.get(Person, operations.person_id)
            assert admin_person is not None
            admin_person.email = CONTROL_ACCOUNT
            admin_person.email_verified_at = prepared.state.now

        async with sessions() as database:
            # The transcript segment ID is the exact server-provided evidence key.
            c2 = await database.get(ConversationCheckpoint, c2_id)
            assert c2 is not None and c2.payload is not None
            segments = c2.payload.get("segments")
            assert isinstance(segments, list) and segments
            span_id = str(segments[0]["id"])

        return ReviewCase(
            prepared,
            engine,
            sessions,
            prepared.state.actor,
            ActorContext(
                operations.person_id,
                operations.session_id,
                operations.tenant_id,
                frozenset({"admin_surface"}),
            ),
            reviewer.actor,
            other_reviewer.actor,
            foreign.actor,
            operations.tenant_id,
            report_run_id,
            c2_id,
            span_id,
        )
    except BaseException:
        await engine.dispose()
        raise


@pytest.fixture(scope="module")
def review_case(postgres_harness: Any, tmp_path_factory: pytest.TempPathFactory) -> ReviewCase:
    case = run(
        _build_report_case(
            postgres_harness,
            tmp_path_factory.mktemp("conversation-review"),
        )
    )
    yield case
    run(case.engine.dispose())


def _service(database: AsyncSession, case: ReviewCase) -> ConversationReviewService:
    return ConversationReviewService(
        ConversationApplication(database, clock=lambda: case.prepared.state.now),
        operations_tenant_id=case.operations_tenant_id,
    )


def _assignment_request(
    case: ReviewCase, *, lenses: tuple[str, ...] = ("sales",)
) -> ReviewAssignmentCreateRequest:
    return ReviewAssignmentCreateRequest(
        schema="ac.sales-xray.review-assignment-create/1",
        run_id=case.report_run_id,
        reviewer_person_id=case.reviewer_actor.person_id,
        allowed_lenses=lenses,  # type: ignore[arg-type]
        expires_at_epoch=int(case.prepared.state.now.timestamp()) + 1_800,
    )


async def _create_assignment(
    case: ReviewCase,
    *,
    key: str,
    lenses: tuple[str, ...] = ("sales",),
) -> dict[str, Any]:
    async with case.sessions() as database, database.begin():
        return await _service(database, case).create(
            case.admin_actor,
            _assignment_request(case, lenses=lenses),
            key,
        )


def _feedback_request(
    case: ReviewCase,
    assignment: ReviewAssignment,
    *,
    key: str,
    lens: str = "sales",
    correction: ReviewProposedCorrection | None = None,
    feedback: str = "The cited span supports this reviewer observation.",
) -> ReviewFeedbackRequest:
    return ReviewFeedbackRequest(
        schema=REVIEW_FEEDBACK_SCHEMA,
        idempotency_key=key,
        lens=lens,  # type: ignore[arg-type]
        evidence_refs=(
            ReviewEvidenceRef(checkpoint_id=assignment.checkpoint.id, span_id=case.span_id),
        ),
        confidence="high",
        feedback=feedback,
        proposed_correction=correction,
    )


def _correction(target: str = "context") -> ReviewProposedCorrection:
    return ReviewProposedCorrection(
        target_layer=target,  # type: ignore[arg-type]
        actual="The saved draft omits the cited context.",
        expected="The saved draft includes the source-bound context.",
        rationale="The reviewer identified a bounded source correction.",
    )


def test_assigned_reviewer_reads_durable_report_submits_and_replays(
    review_case: ReviewCase,
) -> None:
    async def exercise() -> None:
        created = await _create_assignment(
            review_case, key="review-assignment-happy", lenses=("sales", "technical", "ux")
        )
        assignment = ReviewAssignment.model_validate(created)
        assert assignment.run_id == review_case.report_run_id
        async with review_case.sessions() as database, database.begin():
            service = _service(database, review_case)
            view = await service.get(review_case.reviewer_actor, assignment.id)
            assert view["report"]["review_status"] == "draft_not_dipak_adjudicated"
            assert view["transcript"]["source_sha256"] == review_case.prepared.state.source_sha256
            assert view["evidence_spans"][0]["checkpoint_id"] == str(review_case.checkpoint_id)
            assert view["audio_source_url"].endswith(f"/{assignment.id}/source")

            first = await service.submit(
                review_case.reviewer_actor,
                assignment.id,
                _feedback_request(
                    review_case,
                    assignment,
                    key="feedback-1",
                    correction=_correction(),
                ),
            )
            replay = await service.submit(
                review_case.reviewer_actor,
                assignment.id,
                _feedback_request(
                    review_case,
                    assignment,
                    key="feedback-1",
                    correction=_correction(),
                ),
            )
            assert replay == first
            with pytest.raises(ConversationConflict, match="different feedback"):
                await service.submit(
                    review_case.reviewer_actor,
                    assignment.id,
                    _feedback_request(
                        review_case,
                        assignment,
                        key="feedback-1",
                        correction=_correction(),
                        feedback="Changed content must conflict with the same key.",
                    ),
                )
            submissions = await service.submissions(review_case.reviewer_actor, assignment.id)
            assert len(submissions["items"]) == 1
            stored = ReviewFeedbackSubmission.model_validate(submissions["items"][0])
            assert stored.id == UUID(first["id"])
            assert stored.author_person_id == review_case.reviewer_actor.person_id

            canonical = await database.scalars(
                select(ConversationReview).where(
                    ConversationReview.run_id == review_case.report_run_id,
                    ConversationReview.reviewer_id == review_case.reviewer_actor.person_id,
                )
            )
            canonical_rows = canonical.all()
            assert len(canonical_rows) == 1
            assert canonical_rows[0].proposal is not None
            assert canonical_rows[0].proposal["status"] == "proposal_pending_adjudication"

    run(exercise())


def test_unassigned_cross_tenant_and_spoofed_reviewer_are_denied(
    review_case: ReviewCase,
) -> None:
    async def exercise() -> None:
        created = await _create_assignment(review_case, key="review-assignment-acl")
        assignment = ReviewAssignment.model_validate(created)
        async with review_case.sessions() as database, database.begin():
            service = _service(database, review_case)
            with pytest.raises(ConversationNotFound):
                await service.get(review_case.other_reviewer_actor, assignment.id)
            with pytest.raises(ConversationNotFound):
                await service.get(review_case.source_actor, assignment.id)
            with pytest.raises(ConversationNotFound):
                await service.get(review_case.foreign_actor, assignment.id)
            with pytest.raises(ConversationDenied):
                await service.create(
                    review_case.reviewer_actor,
                    _assignment_request(review_case),
                    "review-assignment-non-admin",
                )

        body = _feedback_request(review_case, assignment, key="spoof").model_dump(
            mode="json", by_alias=True
        )
        body["reviewer_person_id"] = str(review_case.other_reviewer_actor.person_id)
        body["author_person_id"] = str(review_case.other_reviewer_actor.person_id)
        with pytest.raises(ValidationError, match="extra_forbidden"):
            ReviewFeedbackRequest.model_validate(body)

    run(exercise())


def test_revoke_expiry_permission_and_generation_fences(
    review_case: ReviewCase,
) -> None:
    async def exercise() -> None:
        revoked = ReviewAssignment.model_validate(
            await _create_assignment(review_case, key="review-assignment-revoke")
        )
        async with review_case.sessions() as database, database.begin():
            await _service(database, review_case).revoke(
                review_case.admin_actor, revoked.id, "review-revoke"
            )
        async with review_case.sessions() as database, database.begin():
            with pytest.raises(ConversationDenied, match="ended"):
                await _service(database, review_case).get(review_case.reviewer_actor, revoked.id)

        expired = ReviewAssignment.model_validate(
            await _create_assignment(review_case, key="review-assignment-expiry")
        )
        async with review_case.sessions() as database, database.begin():
            expired_service = ConversationReviewService(
                ConversationApplication(
                    database,
                    clock=lambda: datetime.fromtimestamp(expired.expires_at_epoch + 1, UTC),
                ),
                operations_tenant_id=review_case.operations_tenant_id,
            )
            with pytest.raises(ConversationDenied, match="ended"):
                await expired_service.get(review_case.reviewer_actor, expired.id)

        permission_fenced = ReviewAssignment.model_validate(
            await _create_assignment(review_case, key="review-assignment-permission")
        )
        try:
            async with review_case.sessions() as database, database.begin():
                await database.execute(
                    update(ConversationPermission)
                    .where(ConversationPermission.id == review_case.prepared.state.permission_id)
                    .values(revoked_at=datetime.now(UTC))
                )
            async with review_case.sessions() as database, database.begin():
                with pytest.raises(ConversationDenied, match="permission"):
                    await _service(database, review_case).get(
                        review_case.reviewer_actor, permission_fenced.id
                    )
        finally:
            async with review_case.sessions() as database, database.begin():
                await database.execute(
                    update(ConversationPermission)
                    .where(ConversationPermission.id == review_case.prepared.state.permission_id)
                    .values(revoked_at=None)
                )

        generation_fenced = ReviewAssignment.model_validate(
            await _create_assignment(review_case, key="review-assignment-generation")
        )
        try:
            async with review_case.sessions() as database, database.begin():
                recording = await database.get(
                    ConversationRecording, review_case.prepared.recording_id
                )
                assert recording is not None
                recording.generation += 1
            async with review_case.sessions() as database, database.begin():
                with pytest.raises(ConversationConflict, match="no longer available"):
                    await _service(database, review_case).get(
                        review_case.reviewer_actor, generation_fenced.id
                    )
        finally:
            async with review_case.sessions() as database, database.begin():
                recording = await database.get(
                    ConversationRecording, review_case.prepared.recording_id
                )
                assert recording is not None
                recording.generation -= 1

    run(exercise())


def test_ux_feedback_is_metadata_only_and_no_canonical_score_is_created(
    review_case: ReviewCase,
) -> None:
    async def exercise() -> None:
        created = await _create_assignment(review_case, key="review-assignment-ux", lenses=("ux",))
        assignment = ReviewAssignment.model_validate(created)
        async with review_case.sessions() as database, database.begin():
            service = _service(database, review_case)
            before = int(
                await database.scalar(
                    select(func.count())
                    .select_from(ConversationReview)
                    .where(ConversationReview.run_id == review_case.report_run_id)
                )
            )
            result = await service.submit(
                review_case.reviewer_actor,
                assignment.id,
                _feedback_request(
                    review_case,
                    assignment,
                    key="ux-feedback-1",
                    lens="ux",
                    correction=_correction("ux_metadata"),
                    feedback="The evidence label should be easier to locate.",
                ),
            )
            assert result["lens"] == "ux"
            assert result["lane"] == "signal"
            after = int(
                await database.scalar(
                    select(func.count())
                    .select_from(ConversationReview)
                    .where(ConversationReview.run_id == review_case.report_run_id)
                )
            )
            assert after == before
            assert "score" not in result and "training_label" not in result

    run(exercise())


def test_z_erasure_clears_feedback_and_canonical_proposal(
    review_case: ReviewCase,
) -> None:
    async def exercise() -> None:
        created = await _create_assignment(review_case, key="review-assignment-erasure")
        assignment = ReviewAssignment.model_validate(created)
        async with review_case.sessions() as database, database.begin():
            await _service(database, review_case).submit(
                review_case.reviewer_actor,
                assignment.id,
                _feedback_request(
                    review_case,
                    assignment,
                    key="erasure-feedback-1",
                    correction=_correction(),
                ),
            )

        async with review_case.sessions() as database, database.begin():
            deletion = await ConversationApplication(
                database, clock=lambda: review_case.prepared.state.now
            ).request_deletion(
                review_case.source_actor,
                review_case.prepared.recording_id,
                key="review-erasure",
            )
            assert deletion["state"] == "deleting"
        eraser = review_case.prepared.worker
        assert await eraser.run_once()

        async with review_case.sessions() as database:
            feedback = await database.scalar(
                select(ConversationReviewFeedback).where(
                    ConversationReviewFeedback.assignment_id == assignment.id
                )
            )
            assert feedback is not None
            assert feedback.erased_at is not None and feedback.payload is None
            canonical = await database.scalar(
                select(ConversationReview).where(ConversationReview.id == assignment.id)
            )
            # ConversationReview uses the submission UUID, so inspect by run and reviewer.
            canonical = await database.scalar(
                select(ConversationReview).where(
                    ConversationReview.run_id == review_case.report_run_id,
                    ConversationReview.reviewer_id == review_case.reviewer_actor.person_id,
                )
            )
            assert canonical is not None
            assert canonical.erased_at is not None and canonical.proposal is None

    run(exercise())
