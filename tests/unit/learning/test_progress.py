from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime
from uuid import uuid4

import pytest

from ac_platform.learning.models import ActivityKind, ActivityState
from ac_platform.learning.services import (
    ActivityDefinition,
    ActivityLockedError,
    ActivityProgressSnapshot,
    ActivityStateError,
    InvalidLearningInput,
    LearningProgressProjectionSnapshot,
    ModuleDefinition,
    ProgramDefinition,
    ProgressProjector,
    authoritative_progress,
    evaluate_prerequisites,
    explain_progress,
)

from .conftest import make_fixture

NOW = datetime(2026, 8, 30, 12, tzinfo=UTC)


def _progress(
    fixture: object, activity: ActivityDefinition, state: ActivityState, *, evidence_id=None
) -> ActivityProgressSnapshot:
    item = fixture  # type: ignore[assignment]
    return ActivityProgressSnapshot(
        tenant_id=item.tenant_id,
        person_id=item.learner_id,
        enrollment_id=item.enrollment_id,
        program_version_id=item.program_version_id,
        program_id=activity.program_id,
        program_scope=activity.program_scope,
        program_owner_key=activity.program_owner_key,
        module_id=activity.module_id,
        activity_id=activity.id,
        state=state,
        activity_version=activity.version,
        policy_version=None,
        revision=1,
        completion_evidence_id=evidence_id,
        updated_at=NOW,
    )


def test_projection_is_deterministic_and_explainable_for_unsorted_versioned_work() -> None:
    fixture = make_fixture()
    first = fixture.activity
    second = ActivityDefinition(
        id=uuid4(),
        kind=ActivityKind.REFLECTION,
        module_id=first.module_id,
        program_version_id=fixture.program_version_id,
        program_id=fixture.program_id,
        program_scope="tenant",
        program_owner_key=fixture.tenant_id,
        tenant_id=fixture.tenant_id,
        order=1,
        version="activity-v1",
    )
    module = ModuleDefinition(
        id=first.module_id,
        program_version_id=fixture.program_version_id,
        program_id=fixture.program_id,
        program_scope="tenant",
        program_owner_key=fixture.tenant_id,
        activities=(second, first),
        order=1,
    )
    program = ProgramDefinition(
        id=fixture.program_id,
        program_version_id=fixture.program_version_id,
        program_scope="tenant",
        program_owner_key=fixture.tenant_id,
        version="program-v1",
        modules=(module,),
    )
    progress = {
        first.id: _progress(fixture, first, ActivityState.IN_PROGRESS),
        second.id: _progress(fixture, second, ActivityState.COMPLETED, evidence_id=uuid4()),
    }

    projection = ProgressProjector().project(program, progress)
    explanation = explain_progress(program, progress)

    assert projection.denominator == 2
    assert projection.completed_count == 1
    assert projection.percentage == 0.5
    assert projection.next_activity_id == first.id
    assert explanation.as_dict()["completed_count"] == 1
    assert [item.activity_id for item in projection.activity_states] == [first.id, second.id]


def test_authoritative_projection_does_not_count_arbitrary_or_cross_scope_evidence() -> None:
    fixture = make_fixture()
    program = fixture.program
    progress = _progress(fixture, fixture.activity, ActivityState.COMPLETED, evidence_id=uuid4())
    projection = ProgressProjector().project_authoritative(
        program, {fixture.activity.id: progress}, {}
    )
    assert projection.completed_count == 0
    assert projection.activity_states[0].state is ActivityState.AVAILABLE


def test_learner_reads_do_not_expose_a_completed_row_without_authoritative_evidence() -> None:
    fixture = make_fixture()
    progress = _progress(
        fixture,
        fixture.activity,
        ActivityState.COMPLETED,
        evidence_id=uuid4(),
    )
    fixture.store.compare_and_swap_progress(None, progress, expected_revision=0)
    access = fixture.store.resolve_scope(
        tenant_id=fixture.tenant_id,
        person_id=fixture.learner_id,
        enrollment_id=fixture.enrollment_id,
        program_version_id=fixture.program_version_id,
        activity_id=fixture.activity.id,
    )

    assert authoritative_progress(fixture.store, access) == {}
    assert (
        fixture.service.activities.current_state(
            actor=fixture.actor,
            tenant_id=fixture.tenant_id,
            enrollment_id=fixture.enrollment_id,
            program_version_id=fixture.program_version_id,
            activity_id=fixture.activity.id,
        )
        is ActivityState.AVAILABLE
    )


def test_prerequisite_evaluation_is_version_aware_and_service_checks_authority() -> None:
    fixture = make_fixture()
    prerequisite = ActivityDefinition(
        id=uuid4(),
        kind=ActivityKind.REFLECTION,
        module_id=fixture.activity.module_id,
        program_version_id=fixture.program_version_id,
        program_id=fixture.program_id,
        program_scope="tenant",
        program_owner_key=fixture.tenant_id,
        tenant_id=fixture.tenant_id,
        version="prerequisite-v1",
    )
    dependent = ActivityDefinition(
        id=fixture.activity.id,
        kind=ActivityKind.REFLECTION,
        module_id=fixture.activity.module_id,
        program_version_id=fixture.program_version_id,
        program_id=fixture.program_id,
        program_scope="tenant",
        program_owner_key=fixture.tenant_id,
        tenant_id=fixture.tenant_id,
        version="activity-v1",
        prerequisites=(prerequisite.id,),
    )
    progress = {
        prerequisite.id: _progress(fixture, prerequisite, ActivityState.COMPLETED),
    }
    current_catalog_definition = ActivityDefinition(
        id=prerequisite.id,
        kind=prerequisite.kind,
        module_id=prerequisite.module_id,
        program_version_id=prerequisite.program_version_id,
        program_id=fixture.program_id,
        program_scope="tenant",
        program_owner_key=fixture.tenant_id,
        tenant_id=prerequisite.tenant_id,
        version="prerequisite-v2",
    )
    result = evaluate_prerequisites(
        dependent,
        progress,
        activities={prerequisite.id: current_catalog_definition},
    )
    assert not result.satisfied
    assert result.missing_activity_ids == (prerequisite.id,)


def test_learning_write_rejects_locked_prerequisite_without_real_completion_evidence() -> None:
    fixture = make_fixture(prerequisites=(uuid4(),))
    with pytest.raises(ActivityLockedError):
        fixture.service.activities.start(
            actor=fixture.actor,
            tenant_id=fixture.tenant_id,
            enrollment_id=fixture.enrollment_id,
            program_version_id=fixture.program_version_id,
            activity_id=fixture.activity.id,
            expected_revision=0,
            idempotency_key="blocked-start",
        )


def test_locked_progress_can_only_start_through_checked_start_command() -> None:
    fixture = make_fixture()
    locked = replace(
        _progress(fixture, fixture.activity, ActivityState.LOCKED),
        revision=0,
    )
    fixture.store.compare_and_swap_progress(None, locked, expected_revision=0)

    with pytest.raises(ActivityStateError, match="checked start command"):
        fixture.service.drafts.save(
            actor=fixture.actor,
            tenant_id=fixture.tenant_id,
            enrollment_id=fixture.enrollment_id,
            program_version_id=fixture.program_version_id,
            activity_id=fixture.activity.id,
            payload={"answer": "must not save"},
            expected_revision=0,
            idempotency_key="locked-draft",
        )
    assert fixture.store.drafts == {}

    with pytest.raises(ActivityStateError, match="checked start command"):
        fixture.service.activities.transition(
            actor=fixture.actor,
            tenant_id=fixture.tenant_id,
            enrollment_id=fixture.enrollment_id,
            program_version_id=fixture.program_version_id,
            activity_id=fixture.activity.id,
            state=ActivityState.IN_PROGRESS,
            expected_revision=0,
            idempotency_key="locked-transition",
        )

    started = fixture.service.activities.start(
        actor=fixture.actor,
        tenant_id=fixture.tenant_id,
        enrollment_id=fixture.enrollment_id,
        program_version_id=fixture.program_version_id,
        activity_id=fixture.activity.id,
        expected_revision=0,
        idempotency_key="checked-locked-start",
    )
    assert started.state is ActivityState.IN_PROGRESS


def test_module_prerequisite_is_enforced_and_writes_materialize_projections() -> None:
    fixture = make_fixture()
    prerequisite_module_id = uuid4()
    prerequisite = ActivityDefinition(
        id=uuid4(),
        kind=ActivityKind.REFLECTION,
        module_id=prerequisite_module_id,
        program_version_id=fixture.program_version_id,
        program_id=fixture.program_id,
        program_scope="tenant",
        program_owner_key=fixture.tenant_id,
        tenant_id=fixture.tenant_id,
    )
    prerequisite_module = ModuleDefinition(
        id=prerequisite_module_id,
        program_version_id=fixture.program_version_id,
        program_id=fixture.program_id,
        program_scope="tenant",
        program_owner_key=fixture.tenant_id,
        activities=(prerequisite,),
    )
    dependent_module = replace(
        fixture.program.modules[0],
        prerequisite_module_ids=(prerequisite_module_id,),
    )
    program = replace(fixture.program, modules=(prerequisite_module, dependent_module))
    scope_key = (
        fixture.tenant_id,
        fixture.enrollment_id,
        fixture.learner_id,
        fixture.program_version_id,
        fixture.activity.id,
    )
    fixture.store.register_access(
        replace(fixture.store.access_contexts[scope_key], program=program)
    )

    with pytest.raises(ActivityLockedError, match="prerequisite"):
        fixture.service.activities.start(
            actor=fixture.actor,
            tenant_id=fixture.tenant_id,
            enrollment_id=fixture.enrollment_id,
            program_version_id=fixture.program_version_id,
            activity_id=fixture.activity.id,
            expected_revision=0,
            idempotency_key="module-prerequisite-start",
        )

    open_fixture = make_fixture()
    open_fixture.service.activities.start(
        actor=open_fixture.actor,
        tenant_id=open_fixture.tenant_id,
        enrollment_id=open_fixture.enrollment_id,
        program_version_id=open_fixture.program_version_id,
        activity_id=open_fixture.activity.id,
        expected_revision=0,
        idempotency_key="projection-start",
    )
    projections = tuple(open_fixture.store.projections.values())
    assert {item.scope_type for item in projections} == {"module", "course"}
    assert all(item.program_id == open_fixture.program_id for item in projections)
    assert all(item.denominator == 1 for item in projections)


def test_projection_snapshot_rejects_nondeterministic_values() -> None:
    tenant_id = uuid4()
    program_id = uuid4()
    module_id = uuid4()
    with pytest.raises(InvalidLearningInput):
        LearningProgressProjectionSnapshot(
            tenant_id=tenant_id,
            person_id=uuid4(),
            enrollment_id=uuid4(),
            program_version_id=uuid4(),
            program_id=program_id,
            program_scope="tenant",
            program_owner_key=tenant_id,
            module_id=module_id,
            scope_type="module",
            scope_id=module_id,
            denominator=2,
            completed_count=1,
            percentage=0.75,
            projection_version="v1",
            explanation={"denominator": 2, "completed_count": 1},
            computed_at=NOW,
        )
