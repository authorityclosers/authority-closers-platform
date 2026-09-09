"""Canonical cookie authentication and real relational workspace filtering."""

from contextlib import asynccontextmanager
from datetime import UTC, datetime, timedelta
from hashlib import sha256
from hmac import digest
from types import SimpleNamespace
from typing import Any, cast
from uuid import uuid4

import httpx
import pytest
from fastapi import FastAPI
from sqlalchemy import create_engine, event, select
from sqlalchemy.orm import Session

from ac_platform.application.settings import Settings
from ac_platform.db.models import model_metadata
from ac_platform.http.auth import install_identity_http
from ac_platform.http.problem import register_problem_handlers
from ac_platform.http.surfaces import CoachSurfaceMiddleware
from ac_platform.identity.models import Person
from ac_platform.identity.models import Session as IdentitySession
from ac_platform.tenancy.models import Membership, Tenant
from tests.unit.authorization.test_capability_application import AwaitableSession

TOKEN = "w" * 43  # noqa: S105 - isolated synthetic cookie
OTHER_TOKEN = "x" * 43  # noqa: S105


class HttpDatabase(AwaitableSession):
    @asynccontextmanager
    async def begin(self):
        with self.database.begin():
            yield

    @asynccontextmanager
    async def begin_nested(self):
        with self.database.begin_nested():
            yield


@pytest.fixture
def workspace_state():
    engine = create_engine("sqlite:///:memory:")

    @event.listens_for(engine, "connect")
    def foreign_keys(connection, _record):
        connection.execute("PRAGMA foreign_keys=ON")

    settings = Settings(
        _env_file=None,
        environment="test",
        public_app_url="https://learner.authorityclosers.test",
        admin_app_url="https://admin.authorityclosers.test",
        coach_app_url="https://coach.authorityclosers.test",
    )
    model_metadata().create_all(engine)
    now = datetime.now(UTC)
    person, other, session, other_session = (uuid4() for _ in range(4))
    names = ("Alpha", "Beta", "Other", "Suspended", "Deleted", "Inactive")
    tenants = {name: uuid4() for name in names}
    with Session(engine) as db, db.begin():
        db.add_all(
            [
                Person(id=person, email="synthetic-owner@example.test", email_verified_at=now),
                Person(id=other, email="synthetic-other@example.test", email_verified_at=now),
            ]
        )
        db.add_all(
            [
                Tenant(
                    id=tenants[name],
                    name=name,
                    slug=name.lower(),
                    status=name.lower() if name in {"Suspended", "Deleted"} else "active",
                )
                for name in names
            ]
        )
        db.flush()
        db.add_all(
            [
                Membership(
                    tenant_id=tenants[name],
                    person_id=other if name == "Other" else person,
                    role="owner" if name == "Other" else "learner",
                    status="inactive" if name == "Inactive" else "active",
                    ended_at=now if name == "Inactive" else None,
                )
                for name in names
            ]
        )
        db.flush()
        pepper = settings.session_token_pepper.get_secret_value().encode("utf-8")
        db.add_all(
            [
                IdentitySession(
                    id=identity,
                    person_id=subject,
                    token_hash=digest(pepper, token.encode("ascii"), sha256),
                    created_at=now - timedelta(days=1),
                    expires_at=now + timedelta(days=1),
                )
                for identity, subject, token in (
                    (session, person, TOKEN),
                    (other_session, other, OTHER_TOKEN),
                )
            ]
        )
    state = SimpleNamespace(
        engine=engine,
        settings=settings,
        person=person,
        other=other,
        session=session,
        tenants=tenants,
        opened=0,
    )

    @asynccontextmanager
    async def sessions():
        state.opened += 1
        with Session(engine) as db:
            yield HttpDatabase(db)

    app = FastAPI()
    register_problem_handlers(app)
    install_identity_http(app, settings=settings, sessions=cast(Any, sessions))
    app.add_middleware(CoachSurfaceMiddleware, settings=settings)
    state.app = app
    yield state
    engine.dispose()


async def get(state, *, token=TOKEN, origin="https://coach.authorityclosers.test", query=""):
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=state.app), base_url=origin
    ) as client:
        return await client.get(
            "/v1/me/workspaces" + query,
            headers={} if token is None else {"cookie": f"ac_session={token}"},
        )


@pytest.mark.parametrize(
    "origin",
    [
        "https://coach.authorityclosers.test",
        "https://admin.authorityclosers.test",
        "https://learner.authorityclosers.test",
    ],
)
async def test_workspaces_are_exact_active_own_choices_without_auto_selection(
    workspace_state, origin
):
    state = workspace_state
    statements = []

    @event.listens_for(state.engine, "before_cursor_execute")
    def capture(_connection, _cursor, statement, _parameters, _context, _many):
        if statement.split()[0].upper() in {"INSERT", "UPDATE", "DELETE"}:
            statements.append(statement)

    response = await get(state, origin=origin)
    assert response.status_code == 200
    assert response.json() == {
        "person_id": str(state.person),
        "session_id": str(state.session),
        "selected_tenant_id": None,
        "workspaces": [
            {"tenant_id": str(state.tenants[name]), "name": name} for name in ("Alpha", "Beta")
        ],
    }
    assert response.headers["cache-control"] == "no-store"
    assert response.headers["pragma"] == "no-cache"
    assert "set-cookie" not in response.headers
    # The standard require_actor dependency retains its existing activity stamp;
    # listing itself cannot select context, grant a role or change domain state.
    assert len(statements) == 1 and statements[0].startswith("UPDATE sessions SET")
    with Session(state.engine) as db:
        identity = db.get(IdentitySession, state.session)
        assert identity.selected_tenant_id is None and identity.revision == 1
        assert set(
            db.scalars(select(Membership.role).where(Membership.person_id == state.person))
        ) == {"learner"}


async def test_another_authenticated_person_sees_only_their_own_workspace(workspace_state):
    state = workspace_state
    response = await get(state, token=OTHER_TOKEN)
    assert response.status_code == 200
    assert response.json()["person_id"] == str(state.other)
    assert response.json()["workspaces"] == [
        {"tenant_id": str(state.tenants["Other"]), "name": "Other"}
    ]


async def test_selected_context_is_reported_not_replaced(workspace_state):
    state = workspace_state
    with Session(state.engine) as db, db.begin():
        db.get(IdentitySession, state.session).selected_tenant_id = state.tenants["Beta"]
    response = await get(state)
    assert response.status_code == 200
    assert response.json()["selected_tenant_id"] == str(state.tenants["Beta"])
    assert len(response.json()["workspaces"]) == 2


async def test_membership_revocation_is_fresh_on_next_read(workspace_state):
    state = workspace_state
    assert len((await get(state)).json()["workspaces"]) == 2
    with Session(state.engine) as db, db.begin():
        row = db.get(Membership, (state.tenants["Alpha"], state.person))
        row.status, row.ended_at = "inactive", datetime.now(UTC)
        db.get(Tenant, state.tenants["Beta"]).status = "suspended"
    response = await get(state)
    assert response.status_code == 200
    assert response.json()["workspaces"] == []
    assert response.json()["selected_tenant_id"] is None


@pytest.mark.parametrize("token", [None, "bad"])
async def test_absent_or_malformed_cookie_never_opens_database(workspace_state, token):
    assert (await get(workspace_state, token=token)).status_code == 401
    assert workspace_state.opened == 0


@pytest.mark.parametrize("failure", ["expired", "revoked", "suspended", "unverified"])
async def test_workspace_list_retains_canonical_authentication_lifecycle(workspace_state, failure):
    state = workspace_state
    with Session(state.engine) as db, db.begin():
        session = db.get(IdentitySession, state.session)
        person = db.get(Person, state.person)
        if failure == "expired":
            session.expires_at = datetime.now(UTC) - timedelta(hours=1)
        elif failure == "revoked":
            session.revoked_at, session.revocation_reason = datetime.now(UTC), "fixture_revocation"
        elif failure == "suspended":
            person.status = "suspended"
        else:
            person.email_verified_at = None
    response = await get(state)
    assert response.status_code == 401
    assert response.json()["code"] == "authentication_rejected"
    assert "workspaces" not in response.json()


@pytest.mark.parametrize("query", ["?person_id=other", "?tenant_id=other", "?role=owner"])
async def test_workspace_query_cannot_select_another_subject(workspace_state, query):
    response = await get(workspace_state, query=query)
    assert response.status_code == 422
    assert "workspaces" not in response.json()
