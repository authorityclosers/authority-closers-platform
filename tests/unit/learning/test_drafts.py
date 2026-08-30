from __future__ import annotations

from uuid import uuid4

import pytest

from ac_platform.kernel.authz import ActorContext
from ac_platform.kernel.errors import AuthorizationDenied
from ac_platform.learning.models import ActivityState
from ac_platform.learning.services import (
    MAX_DRAFT_PAYLOAD_BYTES,
    AccessContextRequiredError,
    DraftRevisionConflict,
    DurableRepositoryRequiredError,
    InMemoryLearningUnitOfWork,
    LearningService,
    PayloadTooLargeError,
)

from .conftest import make_fixture


def _draft_kwargs(fixture: object, **overrides: object) -> dict[str, object]:
    item = fixture  # type: ignore[assignment]
    values: dict[str, object] = {
        "actor": item.actor,
        "tenant_id": item.tenant_id,
        "enrollment_id": item.enrollment_id,
        "program_version_id": item.program_version_id,
        "activity_id": item.activity.id,
        "payload": {"answer": "unfinished"},
        "expected_revision": 0,
        "idempotency_key": "draft-1",
    }
    values.update(overrides)
    return values


def test_draft_is_scoped_revisioned_and_separate_from_official_progress() -> None:
    fixture = make_fixture()

    first = fixture.service.drafts.save(**_draft_kwargs(fixture))
    replay = fixture.service.drafts.save(**_draft_kwargs(fixture))

    assert replay == first
    assert first.revision == 1
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


def test_draft_cas_rejects_stale_revision_without_overwrite() -> None:
    fixture = make_fixture()
    first = fixture.service.drafts.save(**_draft_kwargs(fixture))
    second = fixture.service.drafts.save(
        **_draft_kwargs(
            fixture,
            payload={"answer": "device-b"},
            expected_revision=first.revision,
            idempotency_key="draft-2",
        )
    )

    with pytest.raises(DraftRevisionConflict):
        fixture.service.drafts.save(
            **_draft_kwargs(
                fixture,
                payload={"answer": "stale"},
                expected_revision=first.revision,
                idempotency_key="draft-stale",
            )
        )

    current = fixture.service.drafts.get(
        actor=fixture.actor,
        tenant_id=fixture.tenant_id,
        enrollment_id=fixture.enrollment_id,
        program_version_id=fixture.program_version_id,
        activity_id=fixture.activity.id,
    )
    assert current == second


def test_draft_requires_server_resolved_trust_and_rejects_oversize_payload() -> None:
    fixture = make_fixture()
    untrusted = ActorContext(uuid4(), uuid4(), fixture.tenant_id)
    with pytest.raises(AccessContextRequiredError):
        fixture.service.drafts.save(
            **_draft_kwargs(fixture, actor=untrusted, idempotency_key="untrusted")
        )

    with pytest.raises(PayloadTooLargeError):
        fixture.service.drafts.save(
            **_draft_kwargs(
                fixture,
                payload={"answer": "x" * (MAX_DRAFT_PAYLOAD_BYTES + 1)},
                idempotency_key="oversize",
            )
        )


async def test_production_service_rejects_the_explicit_in_memory_uow() -> None:
    fixture = make_fixture()
    service = LearningService(
        lambda: InMemoryLearningUnitOfWork(fixture.store),
        clock=fixture.clock,
        policy_resolver=lambda _access: fixture.policy,
    )

    with pytest.raises(DurableRepositoryRequiredError):
        await service.execute(lambda _commands: None)


def test_missing_tenant_is_denied_before_learning_access_resolution() -> None:
    fixture = make_fixture()
    actor = ActorContext(fixture.learner_id, uuid4(), None)
    with pytest.raises(AuthorizationDenied):
        fixture.service.activities.start(
            actor=actor,
            tenant_id=fixture.tenant_id,
            enrollment_id=fixture.enrollment_id,
            program_version_id=fixture.program_version_id,
            activity_id=fixture.activity.id,
            expected_revision=0,
            idempotency_key="no-tenant",
        )
