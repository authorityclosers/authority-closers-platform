from __future__ import annotations

from dataclasses import replace
from uuid import uuid4

import pytest

from ac_platform.learning.models import ActivityKind, ActivityState, EvidenceType, ReviewDecision
from ac_platform.learning.services import (
    CompletedActivityMutationError,
    CorrectionRequiresNewEvidenceError,
    CorrectionRevisionConflict,
    DuplicateHeartbeatError,
    EvidenceVersionMismatch,
    InsufficientCoverageError,
    InvalidEvidence,
    ReplayResistanceError,
    ReviewerAuthorizationError,
    SeekOnlyEvidenceError,
    SessionTokenError,
)

from .conftest import make_fixture


def _video_session(fixture: object) -> object:
    item = fixture  # type: ignore[assignment]
    return item.service.playback.start_session(
        actor=item.actor,
        tenant_id=item.tenant_id,
        enrollment_id=item.enrollment_id,
        program_version_id=item.program_version_id,
        activity_id=item.activity.id,
        expected_revision=0,
        idempotency_key="session-start",
    )


def _record_watch(fixture: object, session: object, *, end: float, key: str = "event-1") -> object:
    item = fixture  # type: ignore[assignment]
    position = 0.0
    sequence = 1
    result = None
    while position < end:
        next_position = min(position + item.policy.max_event_seconds, end)
        item.clock.advance(next_position - position)
        event_id = key if end <= item.policy.max_event_seconds else f"{key}-{sequence}"
        result = item.service.playback.record_event(
            actor=item.actor,
            tenant_id=item.tenant_id,
            enrollment_id=item.enrollment_id,
            program_version_id=item.program_version_id,
            activity_id=item.activity.id,
            session_id=session.id,
            session_token=session.session_token,
            event_id=event_id,
            sequence=sequence,
            start_seconds=position,
            end_seconds=next_position,
            kind="watch",
            idempotency_key=f"command-{event_id}",
        )
        position = next_position
        sequence += 1
    assert result is not None
    return result


def test_video_completion_uses_real_same_scope_coverage_and_hash_only_session_storage() -> None:
    fixture = make_fixture(kind=ActivityKind.VIDEO)
    session = _video_session(fixture)
    token = session.session_token
    assert token
    assert session.session_token_hash.hex() != token
    assert fixture.store.get_playback_session(session.id).session_token is None

    _record_watch(fixture, session, end=90)
    evidence, submission = fixture.service.evidence.submit(
        actor=fixture.actor,
        tenant_id=fixture.tenant_id,
        enrollment_id=fixture.enrollment_id,
        program_version_id=fixture.program_version_id,
        activity_id=fixture.activity.id,
        evidence_type=EvidenceType.VIDEO_WATCH,
        idempotency_key="video-evidence-1",
        expected_revision=1,
        payload={},
        playback_session_id=session.id,
        session_token=token,
    )

    progress = fixture.store.get_progress(
        fixture.tenant_id,
        fixture.enrollment_id,
        fixture.learner_id,
        fixture.program_version_id,
        fixture.activity.id,
    )
    assert submission.status.value == "recorded"
    assert evidence.playback_session_id == session.id
    assert progress.state is ActivityState.COMPLETED
    assert progress.completion_evidence_id == evidence.id


def test_video_below_threshold_rolls_back_evidence_and_rejects_fake_completion() -> None:
    fixture = make_fixture(kind=ActivityKind.VIDEO)
    session = _video_session(fixture)
    _record_watch(fixture, session, end=89)

    with pytest.raises(InsufficientCoverageError):
        fixture.service.evidence.submit(
            actor=fixture.actor,
            tenant_id=fixture.tenant_id,
            enrollment_id=fixture.enrollment_id,
            program_version_id=fixture.program_version_id,
            activity_id=fixture.activity.id,
            evidence_type=EvidenceType.VIDEO_WATCH,
            idempotency_key="video-evidence-low",
            expected_revision=1,
            payload={},
            playback_session_id=session.id,
            session_token=session.session_token,
        )

    assert fixture.store.evidence == {}
    assert fixture.store.submissions == {}
    progress = fixture.store.get_progress(
        fixture.tenant_id,
        fixture.enrollment_id,
        fixture.learner_id,
        fixture.program_version_id,
        fixture.activity.id,
    )
    assert progress.state is ActivityState.IN_PROGRESS
    with pytest.raises(InvalidEvidence):
        fixture.service.activities.transition(
            actor=fixture.actor,
            tenant_id=fixture.tenant_id,
            enrollment_id=fixture.enrollment_id,
            program_version_id=fixture.program_version_id,
            activity_id=fixture.activity.id,
            state=ActivityState.COMPLETED,
            expected_revision=1,
            idempotency_key="fake-completion",
            completion_evidence_id=uuid4(),
        )


def test_waiting_then_posting_one_large_watch_interval_cannot_complete_video() -> None:
    fixture = make_fixture(kind=ActivityKind.VIDEO)
    session = _video_session(fixture)
    fixture.clock.advance(90)

    with pytest.raises(ReplayResistanceError, match="heartbeat gap"):
        fixture.service.playback.record_event(
            actor=fixture.actor,
            tenant_id=fixture.tenant_id,
            enrollment_id=fixture.enrollment_id,
            program_version_id=fixture.program_version_id,
            activity_id=fixture.activity.id,
            session_id=session.id,
            session_token=session.session_token,
            event_id="one-large-event",
            sequence=1,
            start_seconds=0,
            end_seconds=90,
            kind="watch",
            idempotency_key="one-large-event-command",
        )

    assert fixture.store.intervals_for_session(session.id) == ()
    with pytest.raises(InsufficientCoverageError):
        fixture.service.evidence.submit(
            actor=fixture.actor,
            tenant_id=fixture.tenant_id,
            enrollment_id=fixture.enrollment_id,
            program_version_id=fixture.program_version_id,
            activity_id=fixture.activity.id,
            evidence_type=EvidenceType.VIDEO_WATCH,
            idempotency_key="one-large-evidence",
            expected_revision=1,
            payload={},
            playback_session_id=session.id,
            session_token=session.session_token,
        )


def test_video_token_sequence_clock_and_duplicate_event_replay_are_enforced() -> None:
    fixture = make_fixture(kind=ActivityKind.VIDEO)
    session = _video_session(fixture)

    with pytest.raises(SessionTokenError):
        fixture.service.playback.record_event(
            actor=fixture.actor,
            tenant_id=fixture.tenant_id,
            enrollment_id=fixture.enrollment_id,
            program_version_id=fixture.program_version_id,
            activity_id=fixture.activity.id,
            session_id=session.id,
            session_token=str(uuid4()),
            event_id="forged",
            sequence=1,
            start_seconds=0,
            end_seconds=1,
            kind="watch",
            idempotency_key="forged-command",
        )

    fixture.clock.advance(2)
    with pytest.raises(ReplayResistanceError):
        fixture.service.playback.record_event(
            actor=fixture.actor,
            tenant_id=fixture.tenant_id,
            enrollment_id=fixture.enrollment_id,
            program_version_id=fixture.program_version_id,
            activity_id=fixture.activity.id,
            session_id=session.id,
            session_token=session.session_token,
            event_id="too-far",
            sequence=1,
            start_seconds=0,
            end_seconds=3,
            kind="watch",
            idempotency_key="too-far-command",
        )

    event = _record_watch(fixture, session, end=2, key="event-1")
    replay = fixture.service.playback.record_event(
        actor=fixture.actor,
        tenant_id=fixture.tenant_id,
        enrollment_id=fixture.enrollment_id,
        program_version_id=fixture.program_version_id,
        activity_id=fixture.activity.id,
        session_id=session.id,
        session_token=session.session_token,
        event_id="event-1",
        sequence=1,
        start_seconds=0,
        end_seconds=2,
        kind="watch",
        idempotency_key="command-event-1",
    )
    assert replay == event

    fixture.clock.advance(1)
    with pytest.raises(DuplicateHeartbeatError):
        fixture.service.playback.record_event(
            actor=fixture.actor,
            tenant_id=fixture.tenant_id,
            enrollment_id=fixture.enrollment_id,
            program_version_id=fixture.program_version_id,
            activity_id=fixture.activity.id,
            session_id=session.id,
            session_token=session.session_token,
            event_id="event-1",
            sequence=1,
            start_seconds=0,
            end_seconds=1,
            kind="watch",
            idempotency_key="command-event-changed",
        )


def test_seek_only_events_and_activity_version_changes_cannot_create_video_evidence() -> None:
    fixture = make_fixture(kind=ActivityKind.VIDEO)
    session = _video_session(fixture)
    fixture.clock.advance(1)
    with pytest.raises(SeekOnlyEvidenceError):
        fixture.service.playback.record_event(
            actor=fixture.actor,
            tenant_id=fixture.tenant_id,
            enrollment_id=fixture.enrollment_id,
            program_version_id=fixture.program_version_id,
            activity_id=fixture.activity.id,
            session_id=session.id,
            session_token=session.session_token,
            event_id="seek",
            sequence=1,
            start_seconds=1,
            end_seconds=1,
            kind="watch",
            idempotency_key="seek-command",
        )

    changed = replace(
        fixture.activity,
        version="activity-v2",
    )
    scope = (
        fixture.tenant_id,
        fixture.enrollment_id,
        fixture.learner_id,
        fixture.program_version_id,
        fixture.activity.id,
    )
    changed_program = replace(
        fixture.program,
        modules=(replace(fixture.program.modules[0], activities=(changed,)),),
    )
    fixture.store.access_contexts[scope] = replace(
        fixture.store.access_contexts[scope],
        activity=changed,
        program=changed_program,
    )
    with pytest.raises(EvidenceVersionMismatch):
        fixture.service.playback.record_event(
            actor=fixture.actor,
            tenant_id=fixture.tenant_id,
            enrollment_id=fixture.enrollment_id,
            program_version_id=fixture.program_version_id,
            activity_id=fixture.activity.id,
            session_id=session.id,
            session_token=session.session_token,
            event_id="version-change",
            sequence=1,
            start_seconds=0,
            end_seconds=1,
            kind="watch",
            idempotency_key="version-change-command",
        )


def test_subjective_review_is_append_only_requires_new_evidence_after_revision_request() -> None:
    fixture = make_fixture()
    evidence, submission = fixture.service.evidence.submit(
        actor=fixture.actor,
        tenant_id=fixture.tenant_id,
        enrollment_id=fixture.enrollment_id,
        program_version_id=fixture.program_version_id,
        activity_id=fixture.activity.id,
        evidence_type=EvidenceType.REFLECTION,
        idempotency_key="reflection-1",
        expected_revision=0,
        payload={"answer": "first"},
    )
    course_projection = next(
        item for item in fixture.store.projections.values() if item.scope_type == "course"
    )
    assert course_projection.completed_count == 0
    fixture.store.register_reviewer(fixture.reviewer_authorization(submission.id))
    correction = fixture.service.evidence.review_submission(
        actor=fixture.reviewer_actor,
        tenant_id=fixture.tenant_id,
        submission_id=submission.id,
        decision=ReviewDecision.NEEDS_REVISION,
        reason="Please add one concrete example.",
        expected_revision=0,
        idempotency_key="review-1",
    )
    assert correction.correction_sequence == 1
    replayed_correction = fixture.service.evidence.review_submission(
        actor=fixture.reviewer_actor,
        tenant_id=fixture.tenant_id,
        submission_id=submission.id,
        decision=ReviewDecision.NEEDS_REVISION,
        reason="Please add one concrete example.",
        expected_revision=0,
        idempotency_key="review-1",
    )
    assert replayed_correction == correction
    with pytest.raises(CorrectionRevisionConflict):
        fixture.service.evidence.review_submission(
            actor=fixture.reviewer_actor,
            tenant_id=fixture.tenant_id,
            submission_id=submission.id,
            decision=ReviewDecision.NEEDS_REVISION,
            reason="stale concurrent review",
            expected_revision=0,
            idempotency_key="review-stale",
        )
    assert (
        fixture.store.get_progress(
            fixture.tenant_id,
            fixture.enrollment_id,
            fixture.learner_id,
            fixture.program_version_id,
            fixture.activity.id,
        ).state
        is ActivityState.IN_PROGRESS
    )
    with pytest.raises(CorrectionRequiresNewEvidenceError):
        fixture.service.evidence.review_submission(
            actor=fixture.reviewer_actor,
            tenant_id=fixture.tenant_id,
            submission_id=submission.id,
            decision=ReviewDecision.APPROVED,
            reason="old evidence is now approved",
            expected_revision=1,
            idempotency_key="review-2",
        )

    evidence2, submission2 = fixture.service.evidence.submit(
        actor=fixture.actor,
        tenant_id=fixture.tenant_id,
        enrollment_id=fixture.enrollment_id,
        program_version_id=fixture.program_version_id,
        activity_id=fixture.activity.id,
        evidence_type=EvidenceType.REFLECTION,
        idempotency_key="reflection-2",
        expected_revision=3,
        payload={"answer": "first, with a concrete example"},
    )
    fixture.store.register_reviewer(fixture.reviewer_authorization(submission2.id))
    approved = fixture.service.evidence.review_submission(
        actor=fixture.reviewer_actor,
        tenant_id=fixture.tenant_id,
        submission_id=submission2.id,
        decision=ReviewDecision.APPROVED,
        reason="Concrete and complete.",
        expected_revision=0,
        idempotency_key="review-3",
    )
    assert approved.evidence_id == evidence2.id
    assert evidence.id != evidence2.id
    course_projection = next(
        item for item in fixture.store.projections.values() if item.scope_type == "course"
    )
    assert course_projection.completed_count == 1
    assert (
        fixture.store.get_progress(
            fixture.tenant_id,
            fixture.enrollment_id,
            fixture.learner_id,
            fixture.program_version_id,
            fixture.activity.id,
        ).state
        is ActivityState.COMPLETED
    )
    with pytest.raises(CompletedActivityMutationError):
        fixture.service.evidence.review_submission(
            actor=fixture.reviewer_actor,
            tenant_id=fixture.tenant_id,
            submission_id=submission2.id,
            decision=ReviewDecision.APPROVED,
            reason="attempted reopen",
            expected_revision=1,
            idempotency_key="review-reopen",
        )


def test_subjective_commands_require_assigned_reviewer_and_reject_client_scoring() -> None:
    fixture = make_fixture(assigned_reviewer=False)
    with pytest.raises(ReviewerAuthorizationError):
        fixture.service.evidence.submit(
            actor=fixture.actor,
            tenant_id=fixture.tenant_id,
            enrollment_id=fixture.enrollment_id,
            program_version_id=fixture.program_version_id,
            activity_id=fixture.activity.id,
            evidence_type=EvidenceType.REFLECTION,
            idempotency_key="no-reviewer",
            expected_revision=0,
            payload={"answer": "x"},
        )
    with pytest.raises(InvalidEvidence):
        fixture.service.evidence.submit(
            actor=fixture.actor,
            tenant_id=fixture.tenant_id,
            enrollment_id=fixture.enrollment_id,
            program_version_id=fixture.program_version_id,
            activity_id=fixture.activity.id,
            evidence_type=EvidenceType.REFLECTION,
            idempotency_key="client-score",
            expected_revision=0,
            payload={"answer": "x", "ai_score": 1},
        )
