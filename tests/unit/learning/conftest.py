from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from uuid import UUID, uuid4

from ac_platform.kernel.authz import ActorContext
from ac_platform.learning.models import ActivityKind
from ac_platform.learning.services import (
    ActivityDefinition,
    InMemoryLearningService,
    InMemoryLearningStore,
    LearningAccessContext,
    MembershipResolution,
    ModuleDefinition,
    ProgramDefinition,
    ReviewerAuthorization,
    VideoEvidencePolicy,
)


class MutableClock:
    def __init__(self) -> None:
        self.value = datetime(2026, 8, 30, 12, 0, tzinfo=UTC)

    def __call__(self) -> datetime:
        return self.value

    def advance(self, seconds: float) -> None:
        from datetime import timedelta

        self.value += timedelta(seconds=seconds)


@dataclass(slots=True)
class LearningFixture:
    tenant_id: UUID
    learner_id: UUID
    reviewer_id: UUID
    enrollment_id: UUID
    program_id: UUID
    program_version_id: UUID
    module_id: UUID
    activity: ActivityDefinition
    program: ProgramDefinition
    actor: ActorContext
    reviewer_actor: ActorContext
    clock: MutableClock
    policy: VideoEvidencePolicy
    store: InMemoryLearningStore
    service: InMemoryLearningService

    def reviewer_authorization(self, submission_id: UUID) -> ReviewerAuthorization:
        return ReviewerAuthorization(
            actor=self.reviewer_actor,
            tenant_id=self.tenant_id,
            submission_id=submission_id,
            assigned=True,
            membership_active=True,
            role="support",
            permission_granted=True,
        )


def make_fixture(
    *,
    kind: ActivityKind = ActivityKind.REFLECTION,
    assigned_reviewer: bool = True,
    prerequisites: tuple[UUID, ...] = (),
    threshold: float = 0.90,
    duration: float = 100.0,
) -> LearningFixture:
    tenant_id = uuid4()
    learner_id = uuid4()
    reviewer_id = uuid4()
    enrollment_id = uuid4()
    program_id = uuid4()
    program_version_id = uuid4()
    module_id = uuid4()
    activity = ActivityDefinition(
        id=uuid4(),
        kind=kind,
        module_id=module_id,
        program_version_id=program_version_id,
        program_id=program_id,
        program_scope="tenant",
        program_owner_key=tenant_id,
        tenant_id=tenant_id,
        version="activity-v1",
        prerequisites=prerequisites,
        video_duration_seconds=duration if kind is ActivityKind.VIDEO else None,
        policy_version="video-policy-v1",
        coverage_threshold=threshold,
    )
    program = ProgramDefinition(
        id=program_id,
        program_version_id=program_version_id,
        program_scope="tenant",
        program_owner_key=tenant_id,
        version="program-v1",
        modules=(
            ModuleDefinition(
                id=module_id,
                program_version_id=program_version_id,
                program_id=program_id,
                program_scope="tenant",
                program_owner_key=tenant_id,
                activities=(activity,),
            ),
        ),
    )
    actor = ActorContext(person_id=learner_id, session_id=uuid4(), tenant_id=tenant_id)
    reviewer_actor = ActorContext(
        person_id=reviewer_id,
        session_id=uuid4(),
        tenant_id=tenant_id,
        permissions=frozenset({"learning_review"}),
    )
    access = LearningAccessContext(
        actor=actor,
        tenant_id=tenant_id,
        person_id=learner_id,
        enrollment_id=enrollment_id,
        program_version_id=program_version_id,
        activity=activity,
        program=program,
        membership=MembershipResolution(
            tenant_id=tenant_id,
            person_id=learner_id,
            role="learner",
            active=True,
            tenant_active=True,
        ),
        enrollment_active=True,
        entitlement_active=True,
        catalog_version_active=True,
        catalog_version_immutable=True,
        assigned_reviewer_id=reviewer_id if assigned_reviewer else None,
    )
    clock = MutableClock()
    policy = VideoEvidencePolicy(
        version="video-policy-v1",
        coverage_threshold=threshold,
        session_ttl_seconds=3600,
        future_clock_skew_seconds=0.0,
        minimum_watch_interval_seconds=1.0,
        max_event_seconds=10.0,
        max_heartbeat_gap_seconds=15.0,
        minimum_heartbeats_for_completion=2,
        clock_grace_seconds=0.0,
        max_rewind_seconds=2.0,
    )
    store = InMemoryLearningStore(activities=[activity], access_contexts=[access])
    service = InMemoryLearningService(
        store,
        clock=clock,
        policy_resolver=lambda _access: policy,
    )
    return LearningFixture(
        tenant_id=tenant_id,
        learner_id=learner_id,
        reviewer_id=reviewer_id,
        enrollment_id=enrollment_id,
        program_id=program_id,
        program_version_id=program_version_id,
        module_id=module_id,
        activity=activity,
        program=program,
        actor=actor,
        reviewer_actor=reviewer_actor,
        clock=clock,
        policy=policy,
        store=store,
        service=service,
    )
