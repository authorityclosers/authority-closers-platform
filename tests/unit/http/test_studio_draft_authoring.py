"""Real relational draft commands through HTTP; SQLite is not lock proof."""

from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta
from typing import Any, cast
from uuid import UUID, uuid4

import httpx
import pytest
from fastapi import FastAPI, Request
from sqlalchemy import func, select

from ac_platform.audit.models import AuditEvent
from ac_platform.audit.service import verify_audit_chain_sync
from ac_platform.authorization.policy import CapabilityScope
from ac_platform.catalog.models import Activity, CatalogAuthoringCommand, Module, ProgramVersion
from ac_platform.catalog.services import CatalogService, SqlAlchemyCatalogStore
from ac_platform.http.admin_learning import install_admin_learning_http
from ac_platform.http.auth import AuthenticatedTransaction
from ac_platform.http.problem import register_problem_handlers
from ac_platform.identity.application import ResolvedActorContext
from ac_platform.identity.models import Session as IdentitySession
from ac_platform.tenancy.models import Membership
from tests.unit.authorization.test_capability_application import assign
from tests.unit.catalog.test_studio_capabilities import (
    capability_state,  # noqa: F401 - dependency of imported fixture
    catalog_state,  # noqa: F401 - shared real relational fixture
    grant,
)
from tests.unit.http.test_admin_learning_routes import _settings


@pytest.fixture(params=["https://admin.authorityclosers.test", "http://coach.localhost:3102"])
async def studio_draft(catalog_state, request):  # noqa: F811
    state = catalog_state
    state.origin = request.param
    state.write_grant = await grant(state)
    state.read_grant = await assign(
        state,
        permission="catalog_read",
        scope=CapabilityScope("program", state.academy, state.program),
    )
    state.version = state.resources[state.program].version
    state.module = state.resources[state.program].first
    state.activity = state.db.scalar(select(Activity.id).where(Activity.module_id == state.module))
    state.db.add(
        IdentitySession(
            id=state.learner_actor.session_id,
            person_id=state.learner,
            selected_tenant_id=state.academy,
            token_hash=b"y" * 32,
            created_at=datetime.now(UTC),
            expires_at=datetime.now(UTC) + timedelta(hours=1),
        )
    )
    state.db.flush()
    state.fail_commit = False

    async def require_actor(_request: Request) -> AsyncIterator[AuthenticatedTransaction]:
        # The savepoint models the caller-owned transaction so a failed dependency
        # finalizer can prove the ASGI commit-before-response barrier.
        with state.db.begin_nested():
            yield AuthenticatedTransaction(
                database=state.catalog._session,  # noqa: SLF001 - real test adapter
                identity=cast(Any, None),
                resolved=ResolvedActorContext(state.learner_actor, "learner", 0, 0, 0, 0),
                token="test-only",  # noqa: S106 - synthetic in-process fixture
            )
            if state.fail_commit:
                raise RuntimeError("simulated commit refusal")

    state.application = FastAPI()
    register_problem_handlers(state.application)
    install_admin_learning_http(
        state.application, settings=_settings(), require_actor=require_actor
    )
    yield state


def etag(state):
    service = CatalogService(SqlAlchemyCatalogStore(state.db))
    version = service.get_version(state.version, tenant_id=state.academy)
    return service.publication_etag(version)


def counts(state):
    return tuple(
        state.db.scalar(select(func.count()).select_from(model))
        for model in (Module, Activity, CatalogAuthoringCommand, AuditEvent)
    )


async def send(state, path, body, *, method="POST", key=None, expected=None, headers=None):
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(
            app=state.application, raise_app_exceptions=not state.fail_commit
        ),
        base_url=state.origin,
    ) as client:
        return await client.request(
            method,
            f"/v1/admin/studio/program-versions/{state.version}/{path}",
            json=body,
            headers=headers
            if headers is not None
            else {
                "Origin": state.origin,
                "If-Match": expected or etag(state),
                "Idempotency-Key": key or str(uuid4()),
            },
        )


async def test_save_append_reload_and_exact_retry_are_canonical(studio_draft):
    state = studio_draft
    provenance = state.db.get(ProgramVersion, state.version).content_digest
    expected, key = etag(state), str(uuid4())
    before = counts(state)
    saved = await send(state, "modules", {"title": " A new module "}, key=key, expected=expected)
    assert saved.status_code == 200, saved.text
    payload = saved.json()
    assert payload["replayed"] is False
    module_id = UUID(payload["resource_id"])
    assert state.db.get(Module, module_id).title == "A new module"
    assert state.db.get(Module, module_id).position == 3
    assert saved.headers["cache-control"] == "no-store"
    assert counts(state) == (before[0] + 1, before[1], before[2] + 1, before[3] + 1)
    replay = await send(state, "modules", {"title": "A new module"}, key=key, expected=expected)
    assert replay.status_code == 200 and replay.json()["replayed"] is True
    assert replay.json()["resource_id"] == str(module_id)
    assert counts(state) == (before[0] + 1, before[1], before[2] + 1, before[3] + 1)
    changed = await send(state, "modules", {"title": "Different"}, key=key, expected=expected)
    assert changed.status_code == 409 and changed.json()["code"] == "studio_draft_conflict"
    stale = await send(state, "modules", {"title": "Lost update"}, expected=expected)
    assert stale.status_code == 412
    activity = await send(
        state,
        f"modules/{module_id}/activities",
        {
            "title": "Optional reflection",
            "prompt": " Write a draft. ",
            "kind": "REFLECTION",
            "is_required": False,
        },
    )
    assert activity.status_code == 200, activity.text
    activity_id = UUID(activity.json()["resource_id"])
    assert state.db.get(Activity, activity_id).is_required is False
    assert state.db.get(Activity, activity_id).position == 1
    edited = await send(
        state,
        f"activities/{activity_id}",
        {"title": "Revised reflection", "prompt": None},
        method="PATCH",
    )
    assert edited.status_code == 200, edited.text
    row = state.db.get(Activity, activity_id)
    assert (row.title, row.prompt, row.kind, row.is_required, row.position) == (
        "Revised reflection",
        None,
        "REFLECTION",
        False,
        1,
    )
    renamed = await send(state, f"modules/{module_id}", {"title": "Renamed"}, method="PATCH")
    assert renamed.status_code == 200
    version = next(
        v for v in renamed.json()["program"]["versions"] if v["id"] == str(state.version)
    )
    assert version["etag"] == etag(state)
    assert "content_digest_mismatch" in version["blockers"]
    assert state.db.get(ProgramVersion, state.version).content_digest == provenance
    assert state.db.get(Membership, (state.academy, state.learner)).role == "learner"
    audits = state.db.scalars(
        select(AuditEvent).where(AuditEvent.action == "audit.catalog.draft.authored.v1")
    ).all()
    assert all(set(audit.payload) == {"operation", "program_id", "resource_id"} for audit in audits)
    assert verify_audit_chain_sync(state.db, state.academy).valid


@pytest.mark.parametrize(
    "body",
    [
        {"title": "X", "position": 10},
        {"title": " "},
        {"title": "x" * 201},
        {"title": "X", "tenant_id": str(uuid4())},
    ],
)
async def test_module_rejects_unknown_fields_and_invalid_text(studio_draft, body):
    before = counts(studio_draft)
    assert (await send(studio_draft, "modules", body)).status_code == 422
    assert counts(studio_draft) == before


@pytest.mark.parametrize(
    "field,value", [("kind", "QUIZ"), ("is_required", "false"), ("prompt", " "), ("position", 3)]
)
async def test_activity_creation_is_exact_and_explicit(studio_draft, field, value):
    body = {"kind": "VIDEO", "title": "Clip", "prompt": None, "is_required": True, field: value}
    before = counts(studio_draft)
    response = await send(studio_draft, f"modules/{studio_draft.module}/activities", body)
    assert response.status_code == 422
    assert counts(studio_draft) == before


async def test_scoped_foreign_targets_and_immutable_children_cannot_change(studio_draft):
    state = studio_draft
    before = counts(state)
    foreign_module = state.resources[state.second].first
    assert (
        await send(state, f"modules/{foreign_module}", {"title": "Forbidden"}, method="PATCH")
    ).status_code == 404
    version = state.db.get(ProgramVersion, state.version)
    state.domain.publish_version(state.version, tenant_id=state.academy)
    response = await send(state, f"modules/{state.module}", {"title": "Forbidden"}, method="PATCH")
    assert response.status_code == 409
    assert version.status == "published" and counts(state) == before


async def test_revocation_blocks_even_exact_successful_retry(studio_draft):
    state = studio_draft
    expected, key = etag(state), str(uuid4())
    assert (
        await send(state, "modules", {"title": "Saved"}, expected=expected, key=key)
    ).status_code == 200
    await state.app.revoke(
        state.actor,
        command_id=uuid4(),
        grant_id=state.write_grant.id,
        reason="Fixture assignment ended",
    )
    before = counts(state)
    response = await send(state, "modules", {"title": "Saved"}, expected=expected, key=key)
    assert response.status_code == 403
    assert counts(state) == before


@pytest.mark.parametrize(
    "headers,status",
    [
        ({"Origin": "https://admin.authorityclosers.test"}, 428),
        ({"Origin": "https://evil.example.test"}, 403),
    ],
)
async def test_origin_and_preconditions_precede_effects(studio_draft, headers, status):
    if status == 428:
        headers = {"Origin": studio_draft.origin}
    before = counts(studio_draft)
    assert (
        await send(studio_draft, "modules", {"title": "No"}, headers=headers)
    ).status_code == status
    assert counts(studio_draft) == before


async def test_commit_refusal_never_returns_success_or_preserves_writes(studio_draft):
    state = studio_draft
    before = counts(state)
    state.fail_commit = True
    response = await send(state, "modules", {"title": "Unsaved"})
    assert response.status_code == 500
    assert "resource_id" not in response.text
    assert counts(state) == before


@pytest.mark.parametrize("permission", ["read", "write"])
async def test_read_and_write_are_independent_required_capabilities(studio_draft, permission):
    state = studio_draft
    await state.app.revoke(
        state.actor,
        command_id=uuid4(),
        grant_id=getattr(state, f"{permission}_grant").id,
        reason="Fixture scope ended",
    )
    before = counts(state)
    assert (await send(state, "modules", {"title": "Denied"})).status_code == 403
    assert counts(state) == before


@pytest.mark.parametrize("target", ["second", "foreign", "global_program"])
async def test_command_cannot_select_an_unassigned_program(studio_draft, target):
    state = studio_draft
    expected = etag(state)
    before = counts(state)
    state.version = state.resources[getattr(state, target)].version
    assert (await send(state, "modules", {"title": "Denied"}, expected=expected)).status_code == 404
    assert counts(state) == before


async def test_audit_failure_rolls_back_content_and_receipt(studio_draft, monkeypatch):
    from ac_platform.audit.service import AuditRepository

    state = studio_draft
    before = counts(state)

    async def fail_audit(*_args, **_kwargs):
        assert counts(state)[0] == before[0] + 1  # exercise failure after the actual write
        raise RuntimeError("fixture audit unavailable")

    monkeypatch.setattr(AuditRepository, "append_for_actor", fail_audit)
    with pytest.raises(RuntimeError, match="fixture audit unavailable"):
        await send(state, "modules", {"title": "Must roll back"})
    assert counts(state) == before


async def test_replay_returns_current_resource_after_later_edit_and_publication(
    studio_draft, monkeypatch
):
    import ac_platform.http.admin_learning as routes

    state = studio_draft
    expected, key = etag(state), str(uuid4())
    saved = await send(state, "modules", {"title": "First content"}, expected=expected, key=key)
    resource = UUID(saved.json()["resource_id"])
    await send(state, f"modules/{resource}", {"title": "Later content"}, method="PATCH")
    # Explicit isolated fixture review, not a runtime authoring/publish shortcut.
    version = state.domain.get_version(state.version, tenant_id=state.academy)
    state.db.get(
        ProgramVersion, state.version
    ).content_digest = state.domain._canonical_content_digest(version)  # noqa: SLF001
    state.db.flush()
    state.domain.publish_version(state.version, tenant_id=state.academy)
    monkeypatch.setattr(routes, "STUDIO_IMMUTABLE_VERSION_LIMIT", 0)
    before = counts(state)
    replay = await send(state, "modules", {"title": "First content"}, expected=expected, key=key)
    assert replay.status_code == 200, replay.text
    payload = replay.json()
    assert payload["replayed"] is True and payload["resource_id"] == str(resource)
    assert payload["program"]["versions_truncated"] is True
    current = next(v for v in payload["program"]["versions"] if v["id"] == str(state.version))
    assert current["status"] == "published" and current["etag"] == etag(state)
    assert (
        next(m for m in current["modules"] if m["id"] == str(resource))["title"] == "Later content"
    )
    assert counts(state) == before


@pytest.mark.parametrize(
    "field,value", [("kind", "VIDEO"), ("is_required", False), ("position", 5)]
)
async def test_activity_edit_cannot_change_existing_semantics(studio_draft, field, value):
    state = studio_draft
    before = counts(state)
    response = await send(
        state,
        f"activities/{state.activity}",
        {"title": "Edited", "prompt": None, field: value},
        method="PATCH",
    )
    assert response.status_code == 422
    assert counts(state) == before
