from __future__ import annotations

from datetime import UTC, datetime
from uuid import uuid4

import pytest

from ac_platform.catalog.models import ActivityKind, CatalogScope, ProgramVersionStatus
from ac_platform.catalog.services import (
    CatalogAccessDeniedError,
    CatalogService,
    InMemoryCatalogStore,
    InvalidActivityKindError,
    LearnerMembershipRequiredError,
    LearnerVersionPinningService,
    OrderingConflictError,
    PrerequisiteConflictError,
    PublishedVersionImmutableError,
    SupersessionRequiredError,
)

NOW = datetime(2026, 8, 30, 12, 0, tzinfo=UTC)


def _catalog() -> tuple[CatalogService, InMemoryCatalogStore, object, object]:
    store = InMemoryCatalogStore()
    service = CatalogService(store, clock=lambda: NOW)
    tenant_id = uuid4()
    other_tenant_id = uuid4()
    program = service.create_program(
        tenant_id=tenant_id,
        slug="first-slice",
        title="Program",
        program_id=uuid4(),
        now=NOW,
    )
    return service, store, (tenant_id, other_tenant_id), program


def test_activity_kind_exposure_is_exactly_the_g1_taxonomy() -> None:
    assert tuple(kind.value for kind in ActivityKind) == (
        "VIDEO",
        "REFLECTION",
        "IMPLEMENTATION_CHALLENGE",
        "REVIEW",
        "IMPROVE",
    )


def test_ordering_and_prerequisites_are_deterministic() -> None:
    service, _, tenants, program = _catalog()
    tenant_id, _ = tenants
    version = service.create_version(program.id, tenant_id=tenant_id, version_id=uuid4())
    second = service.add_module(version.id, tenant_id=tenant_id, title="Second", position=2)
    first = service.add_module(version.id, tenant_id=tenant_id, title="First", position=1)

    service.add_activity(
        second.id,
        tenant_id=tenant_id,
        kind=ActivityKind.REFLECTION,
        title="Later",
        position=2,
    )
    service.add_activity(
        second.id,
        tenant_id=tenant_id,
        kind=ActivityKind.VIDEO,
        title="Earlier",
        position=1,
    )
    service.add_module_prerequisite(second.id, first.id, tenant_id=tenant_id)

    assert [module.id for module in service.ordered_modules(version.id, tenant_id=tenant_id)] == [
        first.id,
        second.id,
    ]
    assert [
        activity.kind for activity in service.ordered_activities(second.id, tenant_id=tenant_id)
    ] == [ActivityKind.VIDEO.value, ActivityKind.REFLECTION.value]
    assert (
        service.ordered_prerequisites(second.id, tenant_id=tenant_id)[0].prerequisite_module_id
        == first.id
    )


def test_duplicate_positions_and_forward_prerequisites_are_rejected() -> None:
    service, _, tenants, program = _catalog()
    tenant_id, _ = tenants
    version = service.create_version(program.id, tenant_id=tenant_id)
    first = service.add_module(version.id, tenant_id=tenant_id, title="First", position=1)
    second = service.add_module(version.id, tenant_id=tenant_id, title="Second", position=2)

    with pytest.raises(OrderingConflictError):
        service.add_module(version.id, tenant_id=tenant_id, title="Duplicate", position=1)
    with pytest.raises(PrerequisiteConflictError):
        service.add_module_prerequisite(first.id, second.id, tenant_id=tenant_id)


def test_invalid_activity_kind_is_rejected_without_broadening_the_enum() -> None:
    service, _, tenants, program = _catalog()
    tenant_id, _ = tenants
    version = service.create_version(program.id, tenant_id=tenant_id)
    module = service.add_module(version.id, tenant_id=tenant_id, title="Module")

    with pytest.raises(InvalidActivityKindError):
        service.add_activity(module.id, tenant_id=tenant_id, kind="QUIZ", title="Unsupported")
    with pytest.raises(InvalidActivityKindError):
        service.add_activity(module.id, tenant_id=tenant_id, kind="video", title="Wrong case")


def test_published_content_is_immutable_and_supersession_uses_new_version() -> None:
    service, store, tenants, program = _catalog()
    tenant_id, _ = tenants
    first_version = service.create_version(program.id, tenant_id=tenant_id, version_id=uuid4())
    module = service.add_module(first_version.id, tenant_id=tenant_id, title="Module")
    service.publish_version(first_version.id, tenant_id=tenant_id, now=NOW)

    with pytest.raises(PublishedVersionImmutableError):
        service.add_activity(
            module.id, tenant_id=tenant_id, kind=ActivityKind.VIDEO, title="No edit"
        )

    draft = service.create_version(
        program.id,
        tenant_id=tenant_id,
        supersedes_version_id=first_version.id,
        version_id=uuid4(),
    )
    replacement_module = service.add_module(draft.id, tenant_id=tenant_id, title="Replacement")
    published = service.publish_version(draft.id, tenant_id=tenant_id, now=NOW)

    assert published.id != first_version.id
    assert published.supersedes_version_id == first_version.id
    assert published.status == ProgramVersionStatus.PUBLISHED.value
    assert store.versions[first_version.id].status == ProgramVersionStatus.SUPERSEDED.value
    assert replacement_module.program_version_id == published.id
    assert service.get_published_version(program.id, tenant_id=tenant_id).id == published.id
    assert (
        service.get_version(
            first_version.id,
            tenant_id=tenant_id,
            published_only=True,
        ).id
        == first_version.id
    )


def test_second_publication_requires_an_explicit_superseding_version() -> None:
    service, _, tenants, program = _catalog()
    tenant_id, _ = tenants
    first = service.create_version(program.id, tenant_id=tenant_id)
    service.publish_version(first.id, tenant_id=tenant_id, now=NOW)
    unrelated_draft = service.create_version(program.id, tenant_id=tenant_id)

    with pytest.raises(SupersessionRequiredError):
        service.publish_version(unrelated_draft.id, tenant_id=tenant_id)


def test_cross_tenant_resources_cannot_be_read_or_written() -> None:
    service, _, tenants, program = _catalog()
    tenant_id, other_tenant_id = tenants
    version = service.create_version(program.id, tenant_id=tenant_id)

    with pytest.raises(CatalogAccessDeniedError):
        service.get_program(program.id, tenant_id=other_tenant_id)
    with pytest.raises(CatalogAccessDeniedError):
        service.add_module(version.id, tenant_id=other_tenant_id, title="Other tenant")
    with pytest.raises(CatalogAccessDeniedError):
        service.get_version(version.id, tenant_id=other_tenant_id)


def test_global_program_is_readable_in_any_tenant_but_global_authoring_is_explicit() -> None:
    store = InMemoryCatalogStore()
    service = CatalogService(store, clock=lambda: NOW)
    tenant_id = uuid4()
    other_tenant_id = uuid4()
    program = service.create_program(
        tenant_id=None,
        scope=CatalogScope.GLOBAL,
        slug="global-program",
        title="Global Program",
    )
    version = service.create_version(program.id, tenant_id=None)
    service.publish_version(version.id, tenant_id=None, now=NOW)

    assert service.get_program(program.id, tenant_id=tenant_id).id == program.id
    assert (
        service.get_version(version.id, tenant_id=other_tenant_id, published_only=True).id
        == version.id
    )
    with pytest.raises(CatalogAccessDeniedError):
        service.create_version(program.id, tenant_id=tenant_id)


def test_learner_pinning_is_exact_version_seam_not_enrollment() -> None:
    service, store, tenants, program = _catalog()
    tenant_id, other_tenant_id = tenants
    version = service.create_version(program.id, tenant_id=tenant_id)
    service.publish_version(version.id, tenant_id=tenant_id, now=NOW)
    learner_id = uuid4()

    pinning = LearnerVersionPinningService(
        store,
        active_membership=lambda person_id, selected_tenant_id: (
            person_id == learner_id and selected_tenant_id == tenant_id
        ),
        clock=lambda: NOW,
    )
    pin = pinning.pin_version(
        learner_person_id=learner_id,
        tenant_id=tenant_id,
        program_id=program.id,
        program_version_id=version.id,
    )

    assert pin.program_version_id == version.id
    assert (
        pinning.get_pin(
            learner_person_id=learner_id,
            tenant_id=tenant_id,
            program_id=program.id,
        )
        == pin
    )
    with pytest.raises(LearnerMembershipRequiredError):
        pinning.pin_version(
            learner_person_id=learner_id,
            tenant_id=other_tenant_id,
            program_id=program.id,
            program_version_id=version.id,
        )
