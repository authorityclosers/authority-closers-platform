"""Which workspace a Sales X-Ray sign-in opens, and lead counts per workspace (24 Oct 2026).

A tester reinstalled the app, signed in, and landed in an empty Personal workspace,
so she thought her leads in her organisation were wiped. Fictional rows only.
"""

from contextlib import asynccontextmanager
from datetime import UTC, datetime, timedelta
from typing import Any, cast
from uuid import UUID, uuid4

import httpx
import pytest
from fastapi import FastAPI
from sqlalchemy.orm import Session

from ac_platform.conversation_intelligence.models import (
    ConversationPermission,
    ConversationRecording,
)
from ac_platform.http.auth import install_identity_http
from ac_platform.http.problem import register_problem_handlers
from ac_platform.http.sales_xray_home import lead_counts, sales_xray_home
from ac_platform.http.sales_xray_workspaces import install_sales_xray_workspaces_http
from ac_platform.identity.models import Person
from ac_platform.identity.models import Session as IdentitySession
from ac_platform.lead_desk.models import Lead
from ac_platform.tenancy.models import Membership, Organisation, Tenant
from tests.unit.http.test_workspaces import TOKEN, HttpDatabase, workspace_state  # noqa: F401

NOW = datetime.now(UTC)


@pytest.fixture
def world(workspace_state):  # noqa: F811
    """Personal (Beta, a learner), Alpha (a member) and Gamma (an admin) organisations."""
    state = workspace_state
    state.settings = state.settings.model_copy(
        update={
            "public_learner_tenant_id": state.tenants["Beta"],
            "operations_tenant_id": state.tenants["Other"],
        }
    )
    gamma, seller = uuid4(), uuid4()
    with Session(state.engine) as db, db.begin():
        db.add(Tenant(id=gamma, name="Gamma", slug="gamma", status="active"))
        db.add(Person(id=seller, email="synthetic-seller@example.test", email_verified_at=NOW))
        db.flush()
        for tenant in (state.tenants["Alpha"], state.tenants["Other"], gamma):
            db.add(
                Organisation(
                    tenant_id=tenant,
                    creation_command_id=uuid4(),
                    domain_verification_token="f" * 43,
                )
            )
        db.get(Membership, (state.tenants["Alpha"], state.person)).role = "member"
        db.add(
            Membership(
                tenant_id=gamma,
                person_id=state.person,
                role="admin",
                created_at=NOW - timedelta(days=30),
            )
        )
        db.add(Membership(tenant_id=gamma, person_id=seller, role="member"))
    state.tenants["Gamma"] = gamma
    state.seller = seller
    return state


def _lead(tenant: UUID, owner: UUID | None, updated: datetime) -> Lead:
    return Lead(
        id=uuid4(),
        tenant_id=tenant,
        revision=1,
        source="manual",
        payload={},
        name="Fictional Lead",
        stage="new",
        attempts=0,
        calls=0,
        repeats=0,
        test_data=False,
        owner_person_id=owner,
        assigned_at=None if owner is None else updated,
        created_at=updated,
        updated_at=updated,
    )


def _call(world, tenant: UUID, state: str = "ready") -> list[object]:
    """A call she recorded in this workspace (a permission and its recording)."""
    permission = uuid4()
    return [
        ConversationPermission(
            id=permission,
            tenant_id=tenant,
            person_id=world.person,
            source_sha256="a" * 64,
            provider="local",
            permission_reference="synthetic-permission",
            retention_reference="synthetic-retention",
            created_at=NOW - timedelta(hours=2),
            expires_at=NOW + timedelta(days=1),
            retention_until=NOW + timedelta(days=30),
        ),
        ConversationRecording(
            id=uuid4(),
            tenant_id=tenant,
            person_id=world.person,
            permission_id=permission,
            request_key=uuid4().hex,
            intent_sha256="b" * 64,
            source_sha256="a" * 64,
            source_bytes=1024,
            content_type="audio/wav",
            source_revision=1,
            generation=1,
            state=state,
            created_at=NOW - timedelta(hours=2),
        ),
    ]


def _add(world, *rows) -> None:
    with Session(world.engine) as db, db.begin():
        db.add_all(rows)


def _earlier_session(world, tenant: UUID | None, seen: datetime) -> UUID:
    with Session(world.engine) as db, db.begin():
        session = db.get(IdentitySession, world.session)
        session.selected_tenant_id = tenant
        session.last_seen_at = seen
    return world.session


async def _home(world, exclude: UUID | None = None) -> UUID | None:
    with Session(world.engine) as db:
        return await sales_xray_home(
            HttpDatabase(db), world.person, settings=world.settings, exclude_session_id=exclude
        )


async def test_a_reinstall_opens_her_organisation_with_leads_not_empty_personal(world):
    # Her last sign-in opened Personal (the old rule); her leads are in Alpha.
    _earlier_session(world, world.tenants["Beta"], NOW - timedelta(hours=1))
    _add(
        world,
        *(_lead(world.tenants["Alpha"], world.person, NOW - timedelta(hours=5)) for _ in range(3)),
    )
    assert await _home(world) == world.tenants["Alpha"]


async def test_the_workspace_last_used_wins_when_it_holds_her_data(world):
    _earlier_session(world, world.tenants["Gamma"], NOW - timedelta(hours=2))
    _add(
        world,
        _lead(world.tenants["Gamma"], world.seller, NOW - timedelta(days=3)),  # she manages Gamma
        _lead(world.tenants["Alpha"], world.person, NOW - timedelta(minutes=5)),
    )
    assert await _home(world) == world.tenants["Gamma"]
    # The session being signed in now is never "last used".
    assert await _home(world, exclude=world.session) == world.tenants["Alpha"]


async def test_without_an_earlier_choice_the_newest_data_decides(world):
    _add(
        world,
        _lead(world.tenants["Gamma"], world.seller, NOW - timedelta(days=3)),
        _lead(world.tenants["Alpha"], world.person, NOW - timedelta(hours=1)),
        # Someone else's lead in Alpha, where she is a member, is not hers.
        _lead(world.tenants["Alpha"], None, NOW),
    )
    assert await _home(world) == world.tenants["Alpha"]


async def test_a_call_she_recorded_counts_as_her_data(world):
    # Her only data is a call in Personal; her organisations are empty.
    _add(world, *_call(world, world.tenants["Beta"]))
    assert await _home(world) == world.tenants["Beta"]


async def test_a_deleted_call_does_not_count(world):
    _add(world, *_call(world, world.tenants["Beta"], state="deleted"))
    assert await _home(world) in {world.tenants["Alpha"], world.tenants["Gamma"]}


async def test_with_no_data_anywhere_the_newest_organisation_then_personal(world):
    assert await _home(world) in {world.tenants["Alpha"], world.tenants["Gamma"]}
    with Session(world.engine) as db, db.begin():
        for name in ("Alpha", "Gamma"):
            db.get(Membership, (world.tenants[name], world.person)).status = "inactive"
            db.get(Membership, (world.tenants[name], world.person)).ended_at = NOW
    assert await _home(world) == world.tenants["Beta"]
    # Suspended, deleted and ended workspaces never count.
    with Session(world.engine) as db, db.begin():
        db.get(Membership, (world.tenants["Beta"], world.person)).status = "inactive"
        db.get(Membership, (world.tenants["Beta"], world.person)).ended_at = NOW
    assert await _home(world) is None


async def test_counts_her_leads_and_everything_where_she_manages(world):
    _add(
        world,
        *(_lead(world.tenants["Alpha"], world.person, NOW) for _ in range(3)),
        _lead(world.tenants["Alpha"], None, NOW),
        *(_lead(world.tenants["Gamma"], world.seller, NOW) for _ in range(2)),
    )
    with Session(world.engine) as db:
        counts = await lead_counts(HttpDatabase(db), world.person, world.settings)
    assert counts == {
        world.tenants["Alpha"]: 3,
        world.tenants["Gamma"]: 2,
        world.tenants["Beta"]: 0,
    }


async def test_the_leads_route_answers_for_the_signed_in_person_only(world):
    _add(world, *(_lead(world.tenants["Alpha"], world.person, NOW) for _ in range(4)))

    @asynccontextmanager
    async def sessions():
        with Session(world.engine) as db:
            yield HttpDatabase(db)

    app = FastAPI()
    register_problem_handlers(app)
    actor = install_identity_http(app, settings=world.settings, sessions=cast(Any, sessions))
    install_sales_xray_workspaces_http(
        app, settings=world.settings, require_actor=actor, intake=None
    )
    cookie = {"cookie": f"ac_session={TOKEN}"}
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="https://learner.authorityclosers.test"
    ) as client:
        answer = await client.get("/v1/me/sales-xray-workspaces/leads", headers=cookie)
        asked_for_someone = await client.get(
            "/v1/me/sales-xray-workspaces/leads?person=x", headers=cookie
        )
        signed_out = await client.get("/v1/me/sales-xray-workspaces/leads")
    assert answer.status_code == 200, answer.text
    assert "no-store" in answer.headers["cache-control"]
    counts = {item["tenant_id"]: item["leads"] for item in answer.json()["workspaces"]}
    assert counts[str(world.tenants["Alpha"])] == 4
    assert counts[str(world.tenants["Beta"])] == 0
    assert asked_for_someone.status_code != 200
    assert signed_out.status_code == 401
