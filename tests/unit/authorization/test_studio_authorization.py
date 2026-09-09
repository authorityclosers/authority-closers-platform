"""Real relational scope checks; PostgreSQL lock behavior has separate tests."""

from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime
from types import SimpleNamespace
from uuid import uuid4

import pytest

from ac_platform.authorization.policy import CapabilityDenied, CapabilityScope
from ac_platform.authorization.studio import LEGACY_STUDIO_PERMISSIONS, StudioAuthorization
from ac_platform.catalog.models import Program
from ac_platform.http.auth import ROLE_PERMISSIONS
from ac_platform.identity.models import Person
from ac_platform.kernel.authz import ActorContext
from ac_platform.tenancy.models import Membership, Tenant
from tests.unit.authorization.test_capability_application import assign, bootstrap
from tests.unit.authorization.test_capability_application import state as state  # fixture


def learner(state: SimpleNamespace) -> ActorContext:
    return ActorContext(state.learner, uuid4(), state.academy)


def test_existing_role_policy_is_unchanged() -> None:
    for role, permissions in LEGACY_STUDIO_PERMISSIONS.items():
        assert permissions == ROLE_PERMISSIONS[role] & LEGACY_STUDIO_PERMISSIONS["owner"]


async def test_program_assignment_allows_only_exact_course_and_filtered_collection(state) -> None:
    await bootstrap(state)
    await assign(state, scope=CapabilityScope("program", state.academy, state.program))
    actor = learner(state)
    app = StudioAuthorization(state.app.database)
    scope = await app.access(actor, "catalog_read")
    assert scope.tenant_id == state.academy
    assert not scope.all_programs and not scope.include_global
    assert scope.program_ids == frozenset({state.program})
    await app.require(actor, "catalog_read", program_id=state.program)
    for other in (None, state.second, uuid4()):
        with pytest.raises(CapabilityDenied):
            await app.require(actor, "catalog_read", program_id=other)
    with pytest.raises(CapabilityDenied):
        await app.require(actor, "catalog_publish", program_id=state.program)
    assert state.db.get(Membership, (state.academy, state.learner)).role == "learner"


async def test_tenant_assignment_never_includes_global_or_another_academy(state) -> None:
    await bootstrap(state)
    await assign(state)
    global_id, other_id = uuid4(), uuid4()
    state.db.add_all(
        [
            Program(id=global_id, scope="global", slug=global_id.hex, title="Global draft"),
            Program(
                id=other_id,
                scope="tenant",
                tenant_id=state.other,
                slug=other_id.hex,
                title="Other academy draft",
            ),
        ]
    )
    state.db.flush()
    app = StudioAuthorization(state.app.database)
    actor = learner(state)
    scope = await app.access(actor, "catalog_read")
    assert scope.all_programs and not scope.include_global
    await app.require(actor, "catalog_read")
    await app.require(actor, "catalog_read", program_id=state.second)
    for denied in (global_id, other_id):
        with pytest.raises(CapabilityDenied):
            await app.require(actor, "catalog_read", program_id=denied)


async def test_platform_capability_and_forged_actor_permissions_cannot_unlock_studio(state) -> None:
    await bootstrap(state)
    await assign(state, permission="platform_catalog_read", scope=CapabilityScope("platform"))
    actor = replace(learner(state), permissions=ROLE_PERMISSIONS["owner"])
    with pytest.raises(CapabilityDenied):
        await StudioAuthorization(state.app.database).access(actor, "catalog_read")


async def test_legacy_authorized_role_keeps_access_without_grant(state) -> None:
    member = state.db.get(Membership, (state.academy, state.learner))
    member.role = "admin"
    state.db.flush()
    app = StudioAuthorization(state.app.database)
    actor = replace(learner(state), permissions=ROLE_PERMISSIONS["admin"])
    scope = await app.access(actor, "catalog_read")
    assert scope.all_programs and scope.include_global
    global_id = uuid4()
    state.db.add(Program(id=global_id, scope="global", slug=global_id.hex, title="Global"))
    state.db.flush()
    await app.require(actor, "catalog_read", program_id=global_id)
    with pytest.raises(CapabilityDenied):
        await app.require(actor, "catalog_write", program_id=global_id)
    with pytest.raises(CapabilityDenied):
        await app.require(learner(state), "catalog_read")


async def test_revocation_is_observed_in_same_identity_map(state) -> None:
    await bootstrap(state)
    grant = await assign(state)
    app = StudioAuthorization(state.app.database)
    await app.require(learner(state), "catalog_read")
    await state.app.revoke(
        state.actor, command_id=uuid4(), grant_id=grant.id, reason="Responsibility ended"
    )
    with pytest.raises(CapabilityDenied):
        await app.require(learner(state), "catalog_read")


@pytest.mark.parametrize("mode", ["person", "unverified", "tenant", "membership", "role"])
async def test_current_lifecycle_is_required_even_after_successful_access(state, mode) -> None:
    await bootstrap(state)
    await assign(state)
    app = StudioAuthorization(state.app.database)
    actor = learner(state)
    await app.require(actor, "catalog_read")
    if mode == "person":
        state.db.get(Person, state.learner).status = "suspended"
    elif mode == "unverified":
        state.db.get(Person, state.learner).email_verified_at = None
    elif mode == "tenant":
        state.db.get(Tenant, state.academy).status = "suspended"
    elif mode == "role":
        state.db.get(Membership, (state.academy, state.learner)).role = "support"
        actor = replace(actor, permissions=ROLE_PERMISSIONS["owner"])
        # Support still cannot use forged catalog permission; revoke the real
        # grant through canonical history before checking the role boundary.
        grant = (await state.app.active_grants(state.learner))[0]
        await state.app.revoke(
            state.actor, command_id=uuid4(), grant_id=grant.id, reason="End content responsibility"
        )
    else:
        member = state.db.get(Membership, (state.academy, state.learner))
        member.status = "inactive"
        member.ended_at = datetime.now(UTC)
    state.db.flush()
    with pytest.raises(CapabilityDenied):
        await app.require(actor, "catalog_read")


@pytest.mark.parametrize("permission", ["platform_catalog_read", "admin_surface", "finance_refund"])
async def test_cross_namespace_and_unknown_actions_fail_closed(state, permission) -> None:
    with pytest.raises(CapabilityDenied):
        await StudioAuthorization(state.app.database).access(learner(state), permission)


async def test_projection_distinguishes_no_assignments_from_invalid_lifecycle(state) -> None:
    app = StudioAuthorization(state.app.database)
    assert await app.projection(learner(state)) == {}
    state.db.get(Tenant, state.academy).status = "suspended"
    state.db.flush()
    with pytest.raises(CapabilityDenied):
        await app.projection(learner(state))


async def test_projection_keeps_each_permission_and_scope_separate(state) -> None:
    await bootstrap(state)
    await assign(state, permission="catalog_read")
    await assign(
        state,
        permission="catalog_publish",
        scope=CapabilityScope("program", state.academy, state.program),
    )
    await assign(state, permission="platform_catalog_write", scope=CapabilityScope("platform"))
    projection = await StudioAuthorization(state.app.database).projection(learner(state))
    assert set(projection) == {"catalog_read", "catalog_publish"}
    assert projection["catalog_read"].all_programs
    assert not projection["catalog_publish"].all_programs
    assert projection["catalog_publish"].program_ids == frozenset({state.program})
