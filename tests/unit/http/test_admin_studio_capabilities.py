"""Real relational Studio scope policy through HTTP; SQLite is not lock evidence."""

from __future__ import annotations

from collections.abc import AsyncIterator, Iterator
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from typing import Any, cast
from uuid import UUID, uuid4

import httpx
import pytest
from fastapi import FastAPI, Request
from sqlalchemy import create_engine, event
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Session

import ac_platform.http.admin_learning as admin_module
from ac_platform.audit.service import AuditRepository
from ac_platform.authorization.models import CapabilityGrant, CapabilityRevocation
from ac_platform.authorization.policy import CapabilityDenied
from ac_platform.catalog.models import Program, ProgramVersion
from ac_platform.db.models import model_metadata
from ac_platform.http.auth import ROLE_PERMISSIONS, AuthenticatedTransaction
from ac_platform.http.problem import register_problem_handlers
from ac_platform.identity.application import ResolvedActorContext
from ac_platform.identity.models import Person
from ac_platform.identity.models import Session as IdentitySession
from ac_platform.kernel.authz import ActorContext
from ac_platform.tenancy.models import Membership, Tenant
from tests.unit.authorization.test_capability_application import AwaitableSession
from tests.unit.http.test_admin_learning_routes import _publish_headers, _settings


class StudioDatabase(AwaitableSession):
    async def run_sync(self, operation: Any) -> Any:
        return operation(self.database)


@pytest.fixture
def studio(monkeypatch: pytest.MonkeyPatch) -> Iterator[SimpleNamespace]:
    engine = create_engine("sqlite:///:memory:")

    @event.listens_for(engine, "connect")
    def foreign_keys(connection: Any, _record: Any) -> None:
        connection.execute("PRAGMA foreign_keys=ON")

    model_metadata().create_all(engine)
    with Session(engine, expire_on_commit=False) as database, database.begin():
        now = datetime.now(UTC)
        tenant_id, other_tenant_id, person_id, session_id = (uuid4() for _ in range(4))
        database.add_all(
            [
                Tenant(id=tenant_id, slug=tenant_id.hex, name="Selected academy"),
                Tenant(id=other_tenant_id, slug=other_tenant_id.hex, name="Other academy"),
                Person(id=person_id, email="studio-fixture@example.test", email_verified_at=now),
            ]
        )
        database.flush()
        database.add(Membership(tenant_id=tenant_id, person_id=person_id, role="learner"))
        database.flush()
        database.add(
            IdentitySession(
                id=session_id,
                person_id=person_id,
                selected_tenant_id=tenant_id,
                token_hash=b"s" * 32,
                created_at=now,
                expires_at=now + timedelta(hours=1),
            )
        )
        programs: dict[str, Program] = {}
        versions: dict[str, ProgramVersion] = {}
        for label, owner, title in (
            ("hidden", tenant_id, "A hidden older draft"),
            ("allowed", tenant_id, "Z assigned course"),
            ("other", other_tenant_id, "Other private course"),
            ("global", None, "Global course"),
        ):
            program = Program(
                id=uuid4(),
                scope="global" if owner is None else "tenant",
                tenant_id=owner,
                slug=uuid4().hex,
                title=title,
            )
            database.add(program)
            database.flush()
            version = ProgramVersion(
                id=uuid4(),
                program_id=program.id,
                scope=program.scope,
                tenant_id=owner,
                version_number=1,
                status="published" if owner is None else "draft",
                published_at=now if owner is None else None,
                created_at=now - timedelta(days=10 if label == "hidden" else 1),
            )
            database.add(version)
            database.flush()
            programs[label], versions[label] = program, version
        global_draft = ProgramVersion(
            id=uuid4(),
            program_id=programs["global"].id,
            scope="global",
            tenant_id=None,
            version_number=2,
        )
        database.add(global_draft)
        database.flush()
        adapter = cast(AsyncSession, StudioDatabase(database))
        actor = ActorContext(person_id, session_id, tenant_id)
        auth = AuthenticatedTransaction(
            database=adapter,
            identity=cast(Any, None),
            resolved=ResolvedActorContext(actor, "learner", 0, 0, 0, 0),
            token="studio-test-fixture-token",  # noqa: S106
        )
        state = SimpleNamespace(
            database=database,
            adapter=adapter,
            actor=actor,
            auth=auth,
            programs=programs,
            versions=versions,
            global_draft=global_draft,
            ledger_calls=[],
            publish_calls=[],
            audit_calls=[],
        )

        async def require_actor(_request: Request) -> AsyncIterator[AuthenticatedTransaction]:
            yield state.auth

        async def reserve(*_args: Any, **kwargs: Any) -> tuple[object, bool]:
            state.ledger_calls.append(kwargs)
            return SimpleNamespace(response_payload=None), False

        async def complete(*_args: Any, **_kwargs: Any) -> None:
            return None

        async def publication_audit(*_args: Any, **kwargs: Any) -> object:
            state.audit_calls.append(kwargs)
            return SimpleNamespace(id=uuid4())

        class CatalogApplication:
            def __init__(self, *_args: Any, **_kwargs: Any) -> None:
                pass

            async def publish_version(self, version_id: UUID, **kwargs: Any) -> object:
                state.publish_calls.append((version_id, kwargs))
                version = database.get(ProgramVersion, version_id)
                assert version is not None
                return SimpleNamespace(
                    id=version_id,
                    program_id=version.program_id,
                    version_number=version.version_number,
                    status="published",
                    supersedes_version_id=None,
                    published_at=now,
                )

        monkeypatch.setattr(admin_module, "_reserve_catalog_publish_command", reserve)
        monkeypatch.setattr(admin_module, "_complete_catalog_publish_command", complete)
        monkeypatch.setattr(admin_module, "_append_admin_audit", publication_audit)
        monkeypatch.setattr(admin_module, "AsyncCatalogApplication", CatalogApplication)
        application = FastAPI()
        register_problem_handlers(application)
        admin_module.install_admin_learning_http(
            application, settings=_settings(), require_actor=require_actor
        )
        state.application = application
        yield state
    engine.dispose()


async def _assign(
    studio: SimpleNamespace, permission: str, *, scope: str = "program"
) -> CapabilityGrant:
    audit = await AuditRepository(studio.adapter).append_for_actor(
        studio.actor,
        action="authorization.http_test_fixture",
        resource_type="capability_grant",
        resource_id=uuid4(),
        reason="Local relational fixture only",
    )
    grant = CapabilityGrant(
        id=uuid4(),
        subject_person_id=studio.actor.person_id,
        permission=permission,
        scope_kind=scope,
        tenant_id=studio.actor.tenant_id,
        program_id=studio.programs["allowed"].id if scope == "program" else None,
        granted_by_person_id=studio.actor.person_id,
        audit_event_id=audit.id,
        reason="Local relational fixture only",
    )
    studio.database.add(grant)
    studio.database.flush()
    return grant


@pytest.mark.parametrize(
    "origin", ["https://admin.authorityclosers.test", "http://coach.localhost:3102"]
)
@pytest.mark.parametrize("scope", ["program", "tenant"])
async def test_assigned_read_filters_before_count_order_limit_and_global_visibility(
    studio: SimpleNamespace, monkeypatch: pytest.MonkeyPatch, scope: str, origin: str
) -> None:
    await _assign(studio, "catalog_read", scope=scope)
    if scope == "program":
        monkeypatch.setattr(admin_module, "STUDIO_COLLECTION_LIMIT", 1)
    expected = {studio.programs["allowed"].id}
    if scope == "tenant":
        expected.add(studio.programs["hidden"].id)
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=studio.application),
        base_url=origin,
    ) as client:
        programs = await client.get("/v1/admin/studio/programs")
        readiness = await client.get("/v1/admin/studio/readiness")
        detail = await client.get(f"/v1/admin/studio/programs/{studio.programs['allowed'].id}")
        assert [response.status_code for response in (programs, readiness, detail)] == [200] * 3
        assert {UUID(row["id"]) for row in programs.json()["programs"]} == expected
        assert programs.json()["truncated"] is False
        assert readiness.json()["draft_backlog_count"] == len(expected)
        assert {UUID(row["program_id"]) for row in readiness.json()["drafts"]} == expected
        assert readiness.json()["truncated"] is False
        assert UUID(detail.json()["versions"][0]["id"]) == studio.versions["allowed"].id
        assert all(
            response.headers["cache-control"] == "no-store"
            for response in (programs, readiness, detail)
        )
        if scope == "program":
            assert datetime.fromisoformat(readiness.json()["oldest_draft_created_at"]).replace(
                tzinfo=UTC
            ) == studio.versions["allowed"].created_at.replace(tzinfo=UTC)
            hidden = await client.get(f"/v1/admin/studio/programs/{studio.programs['hidden'].id}")
            assert hidden.status_code == 404
        for label in ("global", "other"):
            hidden = await client.get(f"/v1/admin/studio/programs/{studio.programs[label].id}")
            assert hidden.status_code == 404
    assert studio.actor.permissions == frozenset()
    assert studio.database.get(
        Membership, (studio.actor.tenant_id, studio.actor.person_id)
    ).role == ("learner")


@pytest.mark.parametrize(
    "origin", ["https://admin.authorityclosers.test", "http://coach.localhost:3102"]
)
async def test_program_publication_uses_real_program_and_rechecks_before_replay(
    studio: SimpleNamespace,
    origin: str,
) -> None:
    granted = await _assign(studio, "catalog_publish")
    version = studio.versions["allowed"]
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=studio.application),
        base_url=origin,
    ) as client:
        request = {
            "json": {"reason": "Reviewed scoped publication"},
            "headers": {
                **{name: value for name, value in _publish_headers().items() if name != "Host"},
                "Origin": origin,
            },
        }
        published = await client.post(f"/v1/admin/program-versions/{version.id}/publish", **request)
        assert published.status_code == 200
        assert len(studio.ledger_calls) == len(studio.publish_calls) == len(studio.audit_calls) == 1
        for label in ("hidden", "other", "global"):
            denied = await client.post(
                f"/v1/admin/program-versions/{studio.versions[label].id}/publish", **request
            )
            assert denied.status_code == 404
        assert (await client.get("/v1/admin/studio/programs")).status_code == 403
        assert len(studio.ledger_calls) == 1
        audit = await AuditRepository(studio.adapter).append_for_actor(
            studio.actor,
            action="authorization.http_test_revocation",
            resource_type="capability_grant",
            resource_id=granted.id,
            reason="Local fixture revocation",
        )
        studio.database.add(
            CapabilityRevocation(
                id=uuid4(),
                grant_id=granted.id,
                revoked_by_person_id=studio.actor.person_id,
                audit_event_id=audit.id,
                reason="Local fixture revocation",
            )
        )
        studio.database.flush()
        replay = await client.post(f"/v1/admin/program-versions/{version.id}/publish", **request)
        assert replay.status_code == 403
        assert len(studio.ledger_calls) == len(studio.publish_calls) == len(studio.audit_calls) == 1


@pytest.mark.parametrize("role", ["owner", "admin", "support"])
async def test_persisted_legacy_roles_retain_their_existing_studio_access(
    studio: SimpleNamespace, role: str
) -> None:
    actor = ActorContext(
        studio.actor.person_id,
        studio.actor.session_id,
        studio.actor.tenant_id,
        ROLE_PERMISSIONS[role],
    )
    studio.auth.resolved = ResolvedActorContext(actor, role, 0, 0, 0, 0)
    membership = studio.database.get(Membership, (actor.tenant_id, actor.person_id))
    membership.role = role
    studio.database.flush()
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=studio.application),
        base_url="https://admin.authorityclosers.test",
    ) as client:
        programs = await client.get("/v1/admin/studio/programs")
        if role == "support":
            assert programs.status_code == 403
            await admin_module._require_named_admin(studio.auth, permission="learning_review")
            return
        assert programs.status_code == 200
        assert {UUID(row["id"]) for row in programs.json()["programs"]} == {
            studio.programs[label].id for label in ("allowed", "hidden", "global")
        }
        detail = await client.get(f"/v1/admin/studio/programs/{studio.programs['global'].id}")
        assert detail.status_code == 200
        assert [UUID(row["id"]) for row in detail.json()["versions"]] == [
            studio.versions["global"].id
        ]
        readiness = await client.get("/v1/admin/studio/readiness")
        assert readiness.status_code == 200
        assert readiness.json()["draft_backlog_count"] == 2


@pytest.mark.parametrize("permission", ["learner_diagnose", "learning_review"])
async def test_program_grant_does_not_open_unfiltered_learner_actions(
    studio: SimpleNamespace, permission: str
) -> None:
    await _assign(studio, permission)
    with pytest.raises(admin_module.AdminAuthorizationDenied, match="academy-wide"):
        await admin_module._require_named_admin(studio.auth, permission=permission)
    await admin_module._require_named_admin(
        studio.auth, permission=permission, program_id=studio.programs["allowed"].id
    )
    for other_permission in ("learning_correct", "enrollment_grant"):
        with pytest.raises(admin_module.AdminAuthorizationDenied):
            await admin_module._require_named_admin(studio.auth, permission=other_permission)


async def test_exact_authorizer_failure_is_not_downgraded_to_collection_access(
    studio: SimpleNamespace, monkeypatch: pytest.MonkeyPatch
) -> None:
    await _assign(studio, "catalog_read", scope="tenant")

    async def denied(*_args: Any, **_kwargs: Any) -> None:
        raise CapabilityDenied("The exact action was denied.")

    monkeypatch.setattr(admin_module.StudioAuthorization, "require", denied)
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=studio.application),
        base_url="https://admin.authorityclosers.test",
    ) as client:
        response = await client.get(f"/v1/admin/studio/programs/{studio.programs['allowed'].id}")
        assert response.status_code == 403
        assert response.json()["code"] == "admin_authorization_denied"
        assert "versions" not in response.json()


async def test_unknown_canonical_actor_keeps_admin_denial_code_before_publication(
    studio: SimpleNamespace,
) -> None:
    actor = ActorContext(uuid4(), uuid4(), studio.actor.tenant_id, ROLE_PERMISSIONS["admin"])
    studio.auth.resolved = ResolvedActorContext(actor, "admin", 0, 0, 0, 0)
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=studio.application),
        base_url="https://admin.authorityclosers.test",
    ) as client:
        response = await client.post(
            f"/v1/admin/program-versions/{studio.versions['allowed'].id}/publish",
            json={"reason": "Unknown actor must be denied"},
            headers=_publish_headers(),
        )
        assert response.status_code == 403
        assert response.json()["code"] == "admin_authorization_denied"
        assert studio.ledger_calls == studio.publish_calls == studio.audit_calls == []


@pytest.mark.parametrize(
    "host", ["admin.authorityclosers.test", "app.authorityclosers.test", "localhost"]
)
async def test_self_projection_is_exact_empty_safe_and_rejects_scope_selectors(
    studio: SimpleNamespace, host: str
) -> None:
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=studio.application), base_url=f"https://{host}"
    ) as client:
        empty = await client.get("/v1/me/studio-access")
        assert empty.status_code == 200
        assert empty.json() == {
            "person_id": str(studio.actor.person_id),
            "session_id": str(studio.actor.session_id),
            "tenant_id": str(studio.actor.tenant_id),
            "studio_capabilities": [],
        }
        await _assign(studio, "catalog_read")
        await _assign(studio, "learning_review", scope="tenant")
        response = await client.get("/v1/me/studio-access")
        assert response.status_code == 200
        assert response.headers["cache-control"] == "no-store"
        assert response.json()["studio_capabilities"] == [
            {
                "permission": "catalog_read",
                "scope_kind": "program",
                "tenant_id": str(studio.actor.tenant_id),
                "program_id": str(studio.programs["allowed"].id),
            },
            {
                "permission": "learning_review",
                "scope_kind": "tenant",
                "tenant_id": str(studio.actor.tenant_id),
                "program_id": None,
            },
        ]
        selected = await client.get(f"/v1/me/studio-access?tenant_id={uuid4()}")
        assert selected.status_code == 422
        if host != "admin.authorityclosers.test":
            assert (await client.get("/v1/admin/studio/programs")).status_code == 403
        assert studio.actor.permissions == frozenset()


async def test_self_projection_does_not_turn_lifecycle_denial_into_empty_access(
    studio: SimpleNamespace,
) -> None:
    studio.database.get(Tenant, studio.actor.tenant_id).status = "suspended"
    studio.database.flush()
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=studio.application),
        base_url="https://app.authorityclosers.test",
    ) as client:
        response = await client.get("/v1/me/studio-access")
        assert response.status_code == 403
        assert "studio_capabilities" not in response.json()
