"""Atomic tenant course creation through real relational HTTP, not lock proof."""

from dataclasses import replace
from uuid import UUID, uuid4

import httpx
import pytest
from sqlalchemy import func, select

from ac_platform.audit.models import AuditEvent
from ac_platform.audit.service import verify_audit_chain_sync
from ac_platform.authorization.policy import CapabilityScope
from ac_platform.catalog.models import (
    CatalogAuthoringCommand,
    LearnerVersionPin,
    Module,
    Program,
    ProgramVersion,
)
from ac_platform.catalog.services import CatalogAccessDeniedError
from ac_platform.http.surfaces import CoachSurfaceMiddleware
from tests.unit.authorization.test_capability_application import assign
from tests.unit.http.test_admin_learning_routes import _settings
from tests.unit.http.test_studio_draft_authoring import (  # noqa: F401 - shared fixture chain
    capability_state,
    catalog_state,
    studio_draft,
)


@pytest.fixture
async def course_creator(studio_draft):  # noqa: F811
    state = studio_draft
    state.tenant_grants = {}
    for permission in ("catalog_read", "catalog_write"):
        state.tenant_grants[permission] = await assign(
            state, permission=permission, scope=CapabilityScope("tenant", state.academy)
        )
    state.application.add_middleware(CoachSurfaceMiddleware, settings=_settings())
    return state


def counts(state):
    return tuple(
        state.db.scalar(select(func.count()).select_from(model))
        for model in (
            Program,
            ProgramVersion,
            Module,
            LearnerVersionPin,
            CatalogAuthoringCommand,
            AuditEvent,
        )
    )


async def create(state, *, body=None, key="new-course", headers=None, query=""):
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(
            app=state.application, raise_app_exceptions=not state.fail_commit
        ),
        base_url=state.origin,
    ) as client:
        return await client.post(
            "/v1/admin/studio/programs" + query,
            json={"title": "New course"} if body is None else body,
            headers=headers
            if headers is not None
            else {"Origin": state.origin, "Idempotency-Key": key},
        )


async def test_creates_one_private_empty_draft_and_replays_without_new_rows(course_creator):
    state = course_creator
    before = counts(state)
    saved = await create(state, body={"title": " New course "})
    assert saved.status_code == 200, saved.text
    payload = saved.json()
    assert saved.headers["cache-control"] == "no-store"
    assert payload["replayed"] is False
    program = payload["program"]
    assert program["title"] == "New course"
    assert program["tenant_id"] == str(state.academy) and program["scope"] == "tenant"
    assert len(program["versions"]) == 1
    version = program["versions"][0]
    assert version["id"] == payload["resource_id"]
    assert version["status"] == "draft" and version["version_number"] == 1
    assert version["modules"] == [] and version["published_at"] is None
    row = state.db.get(ProgramVersion, UUID(version["id"]))
    assert all(
        getattr(row, name) is None
        for name in (
            "content_source_ref",
            "content_digest",
            "content_reviewed_by",
            "content_reviewed_at",
            "release_id",
            "content_seed_kind",
        )
    )
    after = counts(state)
    assert after == (
        before[0] + 1,
        before[1] + 1,
        before[2],
        before[3],
        before[4] + 1,
        before[5] + 1,
    )
    replay = await create(state)
    assert replay.status_code == 200 and replay.json()["replayed"] is True
    assert replay.json()["program"]["id"] == program["id"]
    assert replay.json()["resource_id"] == version["id"] and counts(state) == after
    assert verify_audit_chain_sync(state.db, state.academy).valid
    conflict = await create(state, body={"title": "Changed intent"})
    assert conflict.status_code == 409 and counts(state) == after


async def test_same_title_with_distinct_intent_creates_distinct_courses(course_creator):
    first = await create(course_creator, key="first")
    second = await create(course_creator, key="second")
    assert first.status_code == second.status_code == 200
    assert first.json()["program"]["id"] != second.json()["program"]["id"]
    assert first.json()["program"]["slug"] != second.json()["program"]["slug"]


@pytest.mark.parametrize("permission", ["catalog_read", "catalog_write"])
async def test_program_only_or_revoked_authority_cannot_create_or_replay(
    course_creator, permission
):
    state = course_creator
    assert (await create(state)).status_code == 200
    await state.app.revoke(
        state.actor,
        command_id=uuid4(),
        grant_id=state.tenant_grants[permission].id,
        reason="Test assignment ended",
    )
    before = counts(state)
    assert (await create(state)).status_code == 403
    assert (await create(state, key="another")).status_code == 403
    assert counts(state) == before


async def test_existing_program_assignment_does_not_authorize_new_courses(studio_draft):  # noqa: F811
    before = counts(studio_draft)
    assert (await create(studio_draft)).status_code == 403
    assert counts(studio_draft) == before


@pytest.mark.parametrize(
    "body",
    [
        {},
        {"title": " "},
        {"title": "x" * 201},
        {"title": "X", "slug": "reserved"},
        {"title": "X", "tenant_id": str(uuid4())},
        {"title": "X", "status": "published"},
        {"title": "X", "content_reviewed_by": "Dipak"},
        {"title": "X", "is_free": True},
    ],
)
async def test_rejects_unbounded_or_client_owned_policy_fields(course_creator, body):
    before = counts(course_creator)
    assert (await create(course_creator, body=body)).status_code == 422
    assert counts(course_creator) == before


async def test_origin_key_and_query_rejected_before_writes(course_creator):
    state = course_creator
    before = counts(state)
    assert (await create(state, headers={"Origin": state.origin})).status_code == 428
    assert (
        await create(state, headers={"Origin": "https://evil.test", "Idempotency-Key": "key"})
    ).status_code == 403
    assert (await create(state, query="?tenant=elsewhere")).status_code == 422
    assert counts(state) == before


async def test_outer_commit_refusal_rolls_back_course_version_receipt_and_audit(course_creator):
    state = course_creator
    before = counts(state)
    state.fail_commit = True
    response = await create(state)
    assert response.status_code == 500 and "resource_id" not in response.text
    assert counts(state) == before


async def test_application_rechecks_selected_tenant_before_effects(course_creator):
    state = course_creator
    before = counts(state)
    with pytest.raises(CatalogAccessDeniedError):
        await state.catalog.create_program_draft(
            actor=replace(state.learner_actor, tenant_id=state.other),
            tenant_id=state.academy,
            title="No",
            idempotency_key="wrong-tenant",
        )
    assert counts(state) == before
