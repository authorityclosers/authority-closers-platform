"""Fictional HTTP contract evidence using canonical cookies and relational state."""

import json
from contextlib import asynccontextmanager
from datetime import UTC, datetime, timedelta
from typing import Any, cast
from uuid import uuid4

import httpx
import pytest
from fastapi import FastAPI
from pydantic import ValidationError
from sqlalchemy import event
from sqlalchemy.orm import Session

from ac_platform.conversation_intelligence.acquisition_models import (
    ConversationAcquisitionSettlement as Settlement,
)
from ac_platform.conversation_intelligence.acquisition_models import (
    ConversationAcquisitionUsage as Usage,
)
from ac_platform.http.auth import install_identity_http
from ac_platform.http.organisation import (
    MembersResponse,
    OrganisationResponse,
    install_organisation_http,
)
from ac_platform.http.problem import register_problem_handlers
from ac_platform.identity.models import Person
from ac_platform.identity.models import Session as IdentitySession
from ac_platform.organisations.service import OrganisationService
from ac_platform.tenancy.models import (
    Membership,
    Organisation,
    OrganisationDomainSetting,
    OrganisationInvite,
)
from tests.unit.http.test_workspaces import (  # noqa: F401
    OTHER_TOKEN,
    TOKEN,
    HttpDatabase,
    workspace_state,
)


@pytest.fixture
def state(request):
    state = request.getfixturevalue("workspace_state")
    state.tenant = state.tenants["Alpha"]
    state.member = uuid4()
    state.settings = state.settings.model_copy(
        update={
            "public_learner_tenant_id": state.tenants["Beta"],
            "operations_tenant_id": state.tenants["Other"],
        }
    )
    with Session(state.engine) as db, db.begin():
        db.add(
            Organisation(
                tenant_id=state.tenant,
                creation_command_id=uuid4(),
                domain_verification_token="f" * 43,
            )
        )
        db.get(Membership, (state.tenant, state.person)).role = "owner"
        db.add(
            Person(
                id=state.member,
                email="rep@example.test",
                display_name="Fictional Rep",
                email_verified_at=datetime.now(UTC),
            )
        )
        db.flush()
        db.add_all(
            [
                Membership(tenant_id=state.tenant, person_id=state.other, role="admin"),
                Membership(tenant_id=state.tenant, person_id=state.member, role="member"),
            ]
        )
        db.get(IdentitySession, state.session).selected_tenant_id = state.tenant
        db.query(IdentitySession).filter(
            IdentitySession.person_id == state.other
        ).one().selected_tenant_id = state.tenant

    @asynccontextmanager
    async def sessions():
        with Session(state.engine) as db:
            yield HttpDatabase(db)

    state.app = FastAPI()
    register_problem_handlers(state.app)
    actor = install_identity_http(state.app, settings=state.settings, sessions=cast(Any, sessions))
    install_organisation_http(state.app, settings=state.settings, require_actor=actor)
    return state


async def call(state, method="GET", path="", *, body=None, token=TOKEN, key=None):
    headers = {} if token is None else {"cookie": f"ac_session={token}"}
    if key is not None:
        headers["Idempotency-Key"] = str(key)
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=state.app),
        base_url="https://learner.authorityclosers.test",
    ) as client:
        return await client.request(method, "/v1/organisation" + path, headers=headers, json=body)


@pytest.mark.parametrize("token", [None, "bad"])
async def test_session_required(state, token):
    assert (await call(state, token=token)).status_code == 401


@pytest.mark.parametrize("selected", [None, "Beta", "Other", "Inactive"])
async def test_requires_registered_selected_organisation(state, selected):
    with Session(state.engine) as db, db.begin():
        if selected == "Other":
            db.add(
                Membership(tenant_id=state.tenants["Other"], person_id=state.person, role="owner")
            )
            db.flush()
        db.get(IdentitySession, state.session).selected_tenant_id = (
            None if selected is None else state.tenants[selected]
        )
    response = await call(state)
    assert response.status_code == 404
    assert response.json()["detail"] == "No organisation selected."


async def test_profile_latest_settings_and_read_only_directory(state):
    writes = []

    @event.listens_for(state.engine, "before_cursor_execute")
    def capture(_connection, _cursor, statement, _parameters, _many, _context):
        if statement.split()[0].upper() in {"INSERT", "UPDATE", "DELETE"}:
            writes.append(statement)

    response = await call(state)
    assert response.json() == {
        "tenant_id": str(state.tenant),
        "name": "Alpha",
        "role": "owner",
        "verified_domains": [],
        "auto_join": False,
        "member_count": 3,
    }
    assert "no-store" in response.headers["cache-control"]
    assert len((await call(state, path="/members")).json()["members"]) == 3
    assert writes == []
    with Session(state.engine) as db, db.begin():
        db.add_all(
            [
                OrganisationDomainSetting(
                    tenant_id=state.tenant,
                    version=version,
                    verified_domains=[domain],
                    auto_join=auto,
                    proof={},
                    operator_reference="fictional",
                    command_id=uuid4(),
                )
                for version, domain, auto in (
                    (1, "old.example", False),
                    (2, "current.example", True),
                )
            ]
        )
    latest = (await call(state)).json()
    assert latest["verified_domains"] == ["current.example"] and latest["auto_join"] is True
    for model, body in (
        (OrganisationResponse, latest),
        (MembersResponse, (await call(state, path="/members")).json()),
    ):
        model.model_validate_json(json.dumps(body))
        with pytest.raises(ValidationError):
            model.model_validate_json(json.dumps(dict(body, extra="forbidden")))


async def test_member_scope_and_revocation_are_fresh(state):
    with Session(state.engine) as db, db.begin():
        db.get(Membership, (state.tenant, state.person)).role = "member"
    own = (await call(state, path="/members")).json()["members"]
    assert [row["person_id"] for row in own] == [str(state.person)]
    with Session(state.engine) as db, db.begin():
        membership = db.get(Membership, (state.tenant, state.person))
        membership.status, membership.ended_at = "inactive", datetime.now(UTC)
    assert (await call(state, path="/members")).status_code == 404


async def test_usage_window_settlement_personal_isolation_and_last_activity(state):
    now = datetime.now(UTC)
    with Session(state.engine) as db, db.begin():
        usages = [
            Usage(
                id=uuid4(),
                tenant_id=tenant,
                person_id=state.person,
                submission_id=uuid4(),
                source_sha256="a" * 64,
                duration_evidence_sha256="b" * 64,
                reserved_seconds=seconds,
                policy_revision="fictional",
                created_at=created,
            )
            for tenant, seconds, created in (
                (state.tenant, 90, now - timedelta(hours=1)),
                (state.tenant, 120, now - timedelta(hours=2)),
                (state.tenant, 180, now - timedelta(hours=3)),
                (state.tenant, 600, now - timedelta(days=31)),
                (state.tenants["Beta"], 600, now),
            )
        ]
        db.add_all(usages)
        db.flush()
        db.add_all(
            [
                Settlement(
                    usage_id=usages[1].id,
                    charged_seconds=60,
                    kind="completed",
                    receipt_sha256="c" * 64,
                    created_at=now,
                ),
                Settlement(
                    usage_id=usages[2].id,
                    charged_seconds=0,
                    kind="no_work_performed",
                    receipt_sha256="d" * 64,
                    created_at=now,
                ),
            ]
        )
        db.get(IdentitySession, state.session).last_seen_at = now - timedelta(minutes=10)
    rows = (await call(state, path="/members")).json()["members"]
    own = next(row for row in rows if row["person_id"] == str(state.person))
    assert own["minutes_used_30d"] == 2.5 and own["calls_30d"] == 3
    assert datetime.fromisoformat(own["last_active_at"]) == now - timedelta(minutes=10)
    other = next(row for row in rows if row["person_id"] == str(state.member))
    assert other["last_active_at"] is None and other["minutes_used_30d"] == 0


async def test_pending_invites_have_no_person_or_usage(state):
    with Session(state.engine) as db, db.begin():
        db.add(
            OrganisationInvite(
                tenant_id=state.tenant,
                email_normalized="pending@example.test",
                role="member",
                command_id=uuid4(),
                invited_by_person_id=state.person,
            )
        )
    rows = (await call(state, path="/members")).json()["members"]
    invite = next(row for row in rows if row["status"] == "invited")
    assert invite == {
        "person_id": None,
        "invite_id": invite["invite_id"],
        "name": None,
        "email": "pending@example.test",
        "role": "member",
        "status": "invited",
        "joined_at": None,
        "last_active_at": None,
        "minutes_used_30d": 0.0,
        "calls_30d": 0,
    }
    with Session(state.engine) as db, db.begin():
        db.get(Membership, (state.tenant, state.person)).role = "member"
    assert [r["person_id"] for r in (await call(state, path="/members")).json()["members"]] == [
        str(state.person)
    ]


async def test_reactivation_read_keeps_original_join_history(state):
    with Session(state.engine) as db, db.begin():
        membership = db.get(Membership, (state.tenant, state.member))
        original = datetime.now(UTC) - timedelta(days=40)
        membership.created_at, membership.status, membership.ended_at = (
            original,
            "inactive",
            datetime.now(UTC),
        )
        db.flush()
        service = OrganisationService(
            cast(Any, HttpDatabase(db)),
            operations_tenant_id=state.settings.operations_tenant_id,
            public_learner_tenant_id=state.settings.public_learner_tenant_id,
        )
        await service.add_member(state.tenant, state.member, "member", uuid4())
    row = next(
        r
        for r in (await call(state, path="/members")).json()["members"]
        if r["person_id"] == str(state.member)
    )
    assert datetime.fromisoformat(row["joined_at"]) > datetime.now(UTC) - timedelta(minutes=1)
    with Session(state.engine) as db:
        assert (
            db.get(Membership, (state.tenant, state.member)).created_at.replace(tzinfo=UTC)
            == original
        )
