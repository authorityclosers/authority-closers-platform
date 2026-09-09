"""Canonical grants and real relational catalog writes; not PostgreSQL lock proof."""

from __future__ import annotations

from contextlib import asynccontextmanager
from dataclasses import replace
from datetime import UTC, datetime
from types import SimpleNamespace
from typing import cast
from uuid import uuid4

import pytest
from sqlalchemy import delete, func, select, update
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Session

from ac_platform.audit.models import AuditEvent
from ac_platform.audit.service import verify_audit_chain_sync
from ac_platform.authorization.policy import CapabilityScope
from ac_platform.catalog.models import (
    Activity,
    ActivityKind,
    LearnerVersionPin,
    Module,
    ModulePrerequisite,
    Program,
    ProgramVersion,
)
from ac_platform.catalog.services import (
    AsyncCatalogApplication,
    CatalogAccessDeniedError,
    CatalogContentDigestMismatchError,
    CatalogPublicationPreconditionError,
    CatalogPublicationProvenanceError,
    CatalogService,
    CatalogTransactionRequiredError,
    PublishedVersionImmutableError,
    SqlAlchemyCatalogStore,
)
from ac_platform.identity.models import Person
from ac_platform.kernel.authz import ActorContext
from ac_platform.tenancy.models import Membership, Tenant
from tests.unit.authorization.test_capability_application import (
    AwaitableSession,
    assign,
    bootstrap,
)
from tests.unit.authorization.test_capability_application import (
    state as capability_state,  # noqa: F401
)


class CatalogSession(AwaitableSession):
    @asynccontextmanager
    async def begin_nested(self):
        with self.database.begin_nested():
            yield

    async def run_sync(self, operation):
        return operation(self.database)


@pytest.fixture
def catalog_state(capability_state: SimpleNamespace) -> SimpleNamespace:  # noqa: F811 - fixture
    state = capability_state
    state.catalog = AsyncCatalogApplication(cast(AsyncSession, CatalogSession(state.db)))
    state.learner_actor = ActorContext(state.learner, uuid4(), state.academy)
    state.domain = CatalogService(SqlAlchemyCatalogStore(state.db))
    state.foreign = state.domain.create_program(
        tenant_id=state.other, slug="foreign-program", title="Private foreign program"
    ).id
    state.global_program = state.domain.create_program(
        tenant_id=None, slug="global-program", title="Global seed program"
    ).id
    state.resources = {}
    for program_id, tenant_id in (
        (state.program, state.academy),
        (state.second, state.academy),
        (state.foreign, state.other),
        (state.global_program, None),
    ):
        version = state.domain.create_version(program_id, tenant_id=tenant_id)
        first = state.domain.add_module(version.id, tenant_id=tenant_id, title="First")
        second = state.domain.add_module(version.id, tenant_id=tenant_id, title="Second")
        state.domain.add_activity(
            first.id, tenant_id=tenant_id, kind=ActivityKind.REFLECTION, title="Reflect"
        )
        row = state.db.get(ProgramVersion, version.id)
        row.content_digest = state.domain._canonical_content_digest(version)  # noqa: SLF001
        row.content_source_ref = "test:reviewed-catalog"
        row.content_reviewed_by = "Test reviewer"
        row.content_reviewed_at = datetime.now(UTC)
        row.release_id = "d" * 40
        row.content_seed_kind = "reviewed"
        state.db.flush()
        state.resources[program_id] = SimpleNamespace(
            version=version.id, first=first.id, second=second.id
        )
    return state


async def grant(state: SimpleNamespace, permission="catalog_write", scope=None):
    await bootstrap(state)
    return await assign(
        state,
        permission=permission,
        scope=scope or CapabilityScope("program", state.academy, state.program),
    )


async def command(state, operation, *, program_id=None, actor=None):
    program_id = program_id or state.program
    resources = state.resources[program_id]
    arguments = {"actor": actor or state.learner_actor, "tenant_id": state.academy}
    if operation == "version":
        return await state.catalog.create_version(program_id, **arguments)
    if operation == "module":
        return await state.catalog.add_module(resources.version, title="New module", **arguments)
    if operation == "activity":
        return await state.catalog.add_activity(
            resources.first, kind=ActivityKind.REFLECTION, title="New activity", **arguments
        )
    if operation == "prerequisite":
        return await state.catalog.add_module_prerequisite(
            resources.second, resources.first, **arguments
        )
    if operation == "publish":
        return await state.catalog.publish_version(resources.version, **arguments)
    raise AssertionError(operation)


def counts(state):
    return tuple(
        state.db.scalar(select(func.count()).select_from(model))
        for model in (
            Program,
            ProgramVersion,
            Module,
            Activity,
            ModulePrerequisite,
            LearnerVersionPin,
            AuditEvent,
        )
    )


@pytest.mark.parametrize("operation", ["version", "module", "activity", "prerequisite", "publish"])
async def test_program_grant_authorizes_exact_catalog_command_without_role_replacement(
    catalog_state, operation
):
    state = catalog_state
    permission = "catalog_publish" if operation == "publish" else "catalog_write"
    await grant(state, permission)
    result = await command(state, operation)
    assert result.program_id == state.program
    assert state.db.get(Membership, (state.academy, state.learner)).role == "learner"
    assert state.learner_actor.permissions == frozenset()
    assert state.db.in_transaction()
    assert verify_audit_chain_sync(state.db, state.academy).valid


@pytest.mark.parametrize("operation", ["version", "module", "activity", "prerequisite", "publish"])
@pytest.mark.parametrize("target", ["second", "foreign", "global_program"])
async def test_program_grant_never_authorizes_another_program_tenant_or_global_catalog(
    catalog_state, operation, target
):
    state = catalog_state
    await grant(state, "catalog_publish" if operation == "publish" else "catalog_write")
    before = counts(state)
    with pytest.raises(CatalogAccessDeniedError):
        await command(state, operation, program_id=getattr(state, target))
    assert counts(state) == before


@pytest.mark.parametrize("operation", ["version", "module", "activity", "prerequisite", "publish"])
async def test_current_revocation_wins_over_actor_permission_claims(catalog_state, operation):
    state = catalog_state
    permission = "catalog_publish" if operation == "publish" else "catalog_write"
    assignment = await grant(state, permission)
    await state.app.revoke(
        state.actor, command_id=uuid4(), grant_id=assignment.id, reason="Assignment ended"
    )
    stale = replace(state.learner_actor, permissions=frozenset({permission}))
    before = counts(state)
    with pytest.raises(CatalogAccessDeniedError):
        await command(state, operation, actor=stale)
    assert counts(state) == before
    assert verify_audit_chain_sync(state.db, state.academy).valid


@pytest.mark.parametrize(
    "permission", ["catalog_read", "catalog_publish", "platform_catalog_write"]
)
async def test_read_publish_and_platform_grants_do_not_imply_catalog_write(
    catalog_state, permission
):
    state = catalog_state
    scope = CapabilityScope("platform") if permission.startswith("platform_") else None
    await grant(state, permission, scope)
    with pytest.raises(CatalogAccessDeniedError):
        await command(state, "module")


async def test_new_program_requires_tenant_wide_write_not_existing_program_assignment(
    catalog_state,
):
    state = catalog_state
    await grant(state)
    with pytest.raises(CatalogAccessDeniedError):
        await state.catalog.create_program(
            actor=state.learner_actor, tenant_id=state.academy, slug="new", title="New"
        )
    await assign(state, permission="catalog_write", scope=CapabilityScope("tenant", state.academy))
    created = await state.catalog.create_program(
        actor=state.learner_actor, tenant_id=state.academy, slug="new", title="New"
    )
    assert created.tenant_id == state.academy
    assert (await command(state, "module", program_id=state.second)).program_id == state.second


@pytest.mark.parametrize("target", ["second", "foreign", "missing"])
async def test_secondary_references_do_not_expose_unassigned_catalog_identity(
    catalog_state, target
):
    state = catalog_state
    await grant(state)
    resource = state.resources.get(getattr(state, target, None))
    version_id = resource.version if resource else uuid4()
    module_id = resource.first if resource else uuid4()
    for operation in (
        state.catalog.create_version(
            state.program,
            actor=state.learner_actor,
            tenant_id=state.academy,
            supersedes_version_id=version_id,
        ),
        state.catalog.add_module_prerequisite(
            state.resources[state.program].second,
            module_id,
            actor=state.learner_actor,
            tenant_id=state.academy,
        ),
    ):
        with pytest.raises(CatalogAccessDeniedError, match="catalog reference is unavailable"):
            await operation


@pytest.mark.parametrize("operation", ["version", "module", "activity", "prerequisite", "publish"])
async def test_missing_primary_resource_is_denied_without_resource_existence_details(
    catalog_state, operation
):
    state = catalog_state
    await grant(state, "catalog_publish" if operation == "publish" else "catalog_write")
    missing = uuid4()
    state.resources[missing] = SimpleNamespace(version=uuid4(), first=uuid4(), second=uuid4())
    with pytest.raises(CatalogAccessDeniedError):
        await command(state, operation, program_id=missing)


@pytest.mark.parametrize("role", ["owner", "admin"])
async def test_legacy_catalog_admin_requires_canonical_role_and_permission(catalog_state, role):
    state = catalog_state
    membership = state.db.get(Membership, (state.academy, state.learner))
    membership.role = role
    state.db.flush()
    with pytest.raises(CatalogAccessDeniedError):
        await command(state, "module")
    actor = replace(state.learner_actor, permissions=frozenset({"catalog_write"}))
    assert (await command(state, "module", actor=actor)).program_id == state.program
    membership.role = "learner"
    state.db.flush()
    with pytest.raises(CatalogAccessDeniedError):
        await command(state, "activity", actor=actor)


async def test_write_grant_does_not_publish_and_publish_grant_retains_content_checks(catalog_state):
    state = catalog_state
    await grant(state)
    with pytest.raises(CatalogAccessDeniedError):
        await command(state, "publish")
    await assign(
        state,
        permission="catalog_publish",
        scope=CapabilityScope("program", state.academy, state.program),
    )
    await command(state, "activity")
    with pytest.raises(CatalogContentDigestMismatchError):
        await command(state, "publish")
    assert state.db.get(ProgramVersion, state.resources[state.program].version).status == "draft"


@pytest.mark.parametrize("mode", ["provenance", "etag", "technical_validation"])
async def test_publish_grant_never_bypasses_publication_preconditions(catalog_state, mode):
    state = catalog_state
    await grant(state, "catalog_publish")
    version_id = state.resources[state.program].version
    version = state.db.get(ProgramVersion, version_id)
    arguments = {}
    expected = CatalogPublicationProvenanceError
    if mode == "provenance":
        version.content_source_ref = None
    elif mode == "technical_validation":
        version.content_seed_kind = "technical-validation"
    else:
        arguments["expected_etag"] = '"catalog-version-stale"'
        expected = CatalogPublicationPreconditionError
    state.db.flush()
    with pytest.raises(expected):
        await state.catalog.publish_version(
            version_id, actor=state.learner_actor, tenant_id=state.academy, **arguments
        )
    assert state.db.get(ProgramVersion, version_id).status == "draft"


async def test_publication_remains_immutable_for_a_granted_author(catalog_state):
    state = catalog_state
    await grant(state, "catalog_publish")
    await command(state, "publish")
    await assign(
        state,
        permission="catalog_write",
        scope=CapabilityScope("program", state.academy, state.program),
    )
    with pytest.raises(PublishedVersionImmutableError):
        await command(state, "module")


async def test_outer_rollback_undoes_authorized_catalog_write(catalog_state):
    state = catalog_state
    await grant(state)
    module = await command(state, "module")
    assert state.db.get(Module, module.id) is not None
    state.db.rollback()
    with Session(state.db.get_bind()) as database:
        assert database.get(Module, module.id) is None


async def test_catalog_still_requires_explicit_transaction(catalog_state):
    state = catalog_state
    state.db.rollback()
    with pytest.raises(CatalogTransactionRequiredError):
        await command(state, "module")


async def test_global_authoring_legacy_context_is_unchanged(catalog_state):
    state = catalog_state
    actor = ActorContext(state.learner, uuid4(), None, frozenset({"catalog_write"}))
    result = await state.catalog.create_version(state.global_program, actor=actor, tenant_id=None)
    assert result.scope == "global"
    for denied in (
        replace(actor, permissions=frozenset({"platform_catalog_write"})),
        replace(actor, tenant_id=state.academy),
    ):
        with pytest.raises(CatalogAccessDeniedError):
            await state.catalog.create_version(state.global_program, actor=denied, tenant_id=None)


@pytest.mark.parametrize("lifecycle", ["person", "verification", "tenant", "membership", "ended"])
async def test_current_lifecycle_changes_deny_even_with_cached_relational_objects(
    catalog_state, lifecycle
):
    state = catalog_state
    await grant(state)
    # Retain loaded identity-map objects while changing their canonical rows.
    cached = (
        state.db.get(Person, state.learner),
        state.db.get(Tenant, state.academy),
        state.db.get(Membership, (state.academy, state.learner)),
    )
    if lifecycle in {"person", "verification"}:
        values = {"status": "suspended"} if lifecycle == "person" else {"email_verified_at": None}
        statement = update(Person).where(Person.id == state.learner).values(**values)
    elif lifecycle == "tenant":
        statement = update(Tenant).where(Tenant.id == state.academy).values(status="suspended")
    elif lifecycle == "membership":
        statement = delete(Membership).where(
            Membership.person_id == state.learner, Membership.tenant_id == state.academy
        )
    else:
        values = {"status": "inactive", "ended_at": datetime.now(UTC)}
        statement = (
            update(Membership)
            .where(Membership.person_id == state.learner, Membership.tenant_id == state.academy)
            .values(**values)
        )
    state.db.execute(statement.execution_options(synchronize_session=False))
    assert all(row.status == "active" for row in cached)
    with pytest.raises(CatalogAccessDeniedError):
        await command(state, "module")


@pytest.mark.parametrize("context", ["none", "other"])
async def test_studio_grant_cannot_override_selected_tenant(catalog_state, context):
    state = catalog_state
    await grant(state)
    actor = replace(state.learner_actor, tenant_id=None if context == "none" else state.other)
    with pytest.raises(CatalogAccessDeniedError):
        await command(state, "module", actor=actor)


async def test_claimed_generic_permission_without_grant_is_not_studio_authority(catalog_state):
    state = catalog_state
    actor = replace(
        state.learner_actor, permissions=frozenset({"catalog_write", "catalog_publish"})
    )
    for operation in ("module", "publish"):
        with pytest.raises(CatalogAccessDeniedError):
            await command(state, operation, actor=actor)
