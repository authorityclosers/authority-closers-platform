"""Fictional HTTP contract evidence for organisation create, rename and usage (O1b)."""

import json
from datetime import UTC, datetime, timedelta
from typing import Any, cast
from uuid import UUID, uuid4

import httpx
import pytest
from pydantic import ValidationError
from sqlalchemy import select
from sqlalchemy.orm import Session

from ac_platform.audit.models import AuditEvent
from ac_platform.audit.service import verify_audit_chain_sync
from ac_platform.conversation_intelligence.acquisition_models import (
    ConversationAcquisitionSettlement as Settlement,
)
from ac_platform.conversation_intelligence.acquisition_models import (
    ConversationAcquisitionUsage as Usage,
)
from ac_platform.http.organisation import OrganisationNameResponse, UsageResponse
from ac_platform.identity.models import Person
from ac_platform.identity.models import Session as IdentitySession
from ac_platform.organisations.usage import member_usage
from ac_platform.tenancy.models import Membership, Organisation, Tenant
from tests.unit.http.test_organisation import state  # noqa: F401
from tests.unit.http.test_workspaces import (  # noqa: F401
    OTHER_TOKEN,
    TOKEN,
    HttpDatabase,
    workspace_state,
)

ORIGIN = "https://learner.authorityclosers.test"


async def send(state, method, path, *, body=None, token=TOKEN, key=None, origin=ORIGIN):  # noqa: F811
    headers = {"cookie": f"ac_session={token}"}
    if key is not None:
        headers["Idempotency-Key"] = str(key)
    if origin is not None:
        headers["origin"] = origin
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=state.app), base_url=ORIGIN
    ) as client:
        return await client.request(method, "/v1" + path, headers=headers, json=body)


def refused(response, status, code):
    assert response.status_code == status, response.text
    assert response.headers["content-type"] == "application/problem+json"
    assert response.json()["code"] == code


def usage_row(state, tenant, person, seconds, created):  # noqa: F811
    return Usage(
        id=uuid4(),
        tenant_id=tenant,
        person_id=person,
        submission_id=uuid4(),
        source_sha256="a" * 64,
        duration_evidence_sha256="b" * 64,
        reserved_seconds=seconds,
        policy_revision="fictional",
        created_at=created,
    )


@pytest.fixture(autouse=True)
def sqlite_adapter_add_all(monkeypatch):
    # The shared SQLite adapter has no add_all; the create command uses it.
    monkeypatch.setattr(
        HttpDatabase, "add_all", lambda self, rows: [self.add(row) for row in rows], raising=False
    )


async def test_create_replays_selects_and_stops_at_three_owned(state):  # noqa: F811
    key = uuid4()
    created = await send(
        state, "POST", "/organisations", body={"name": " Fictional Sales "}, key=key
    )
    assert created.status_code == 201, created.text
    body = created.json()
    assert body == {"tenant_id": body["tenant_id"], "name": "Fictional Sales", "role": "owner"}
    assert "no-store" in created.headers["cache-control"]
    OrganisationNameResponse.model_validate_json(json.dumps(body))
    with pytest.raises(ValidationError):
        OrganisationNameResponse.model_validate_json(json.dumps(dict(body, extra=1)))
    # The same key and body return the first result; a changed body is refused.
    replay = await send(state, "POST", "/organisations", body={"name": "Fictional Sales"}, key=key)
    assert replay.status_code == 200 and replay.json() == body
    changed = await send(state, "POST", "/organisations", body={"name": "Another"}, key=key)
    refused(changed, 409, "idempotency_conflict")
    with Session(state.engine) as db:
        tenant_id = UUID(body["tenant_id"])
        members = list(db.scalars(select(Membership).where(Membership.tenant_id == tenant_id)))
        assert [(row.person_id, row.role, row.status) for row in members] == [
            (state.person, "owner", "active")
        ]
        assert db.get(Organisation, members[0].tenant_id) is not None
        assert verify_audit_chain_sync(db, tenant_id=members[0].tenant_id).valid
    # The existing context route selects the new organisation.
    chosen = await send(state, "POST", "/context", body={"tenant_id": body["tenant_id"]})
    assert chosen.status_code == 200, chosen.text
    profile = (await send(state, "GET", "/organisation")).json()
    assert (profile["name"], profile["role"], profile["member_count"]) == (
        "Fictional Sales",
        "owner",
        1,
    )
    # The fixture owner already owns Alpha, so one more reaches the limit of three.
    third = await send(state, "POST", "/organisations", body={"name": "Third"}, key=uuid4())
    assert third.status_code == 201
    fourth = await send(state, "POST", "/organisations", body={"name": "Fourth"}, key=uuid4())
    refused(fourth, 409, "organisation_limit")
    assert (
        await send(state, "POST", "/organisations", body={"name": "Fictional Sales"}, key=key)
    ).json() == body


@pytest.mark.parametrize(
    "body", [{"name": "A"}, {"name": "x" * 81}, {"name": 5}, {"name": "Fine", "slug": "x"}, {}]
)
async def test_create_and_rename_refuse_invalid_bodies(state, body):  # noqa: F811
    for method, path in (("POST", "/organisations"), ("PATCH", "/organisation")):
        refused(await send(state, method, path, body=body, key=uuid4()), 422, "validation_failed")
    with Session(state.engine) as db:
        assert db.get(Tenant, state.tenant).name == "Alpha"


async def test_create_needs_origin_session_key_and_verified_email(state):  # noqa: F811
    body = {"name": "Fictional"}
    assert (
        await send(state, "POST", "/organisations", body=body, key=uuid4(), origin=None)
    ).status_code == 403
    assert (
        await send(state, "POST", "/organisations", body=body, key=uuid4(), token="bad")  # noqa: S106
    ).status_code == 401
    assert (await send(state, "POST", "/organisations", body=body, key="short")).status_code == 422
    # Sign-in itself requires a verified email, so an unverified person has no session.
    with Session(state.engine) as db, db.begin():
        db.get(Person, state.person).email_verified_at = None
    assert (await send(state, "POST", "/organisations", body=body, key=uuid4())).status_code == 401
    with Session(state.engine) as db:
        assert db.scalar(select(Tenant).where(Tenant.name == "Fictional")) is None


async def test_owner_renames_with_audit_and_replay(state):  # noqa: F811
    key = uuid4()
    renamed = await send(state, "PATCH", "/organisation", body={"name": "Alpha Sales"}, key=key)
    assert renamed.status_code == 200, renamed.text
    assert renamed.json() == {
        "tenant_id": str(state.tenant),
        "name": "Alpha Sales",
        "role": "owner",
    }
    assert "no-store" in renamed.headers["cache-control"]
    assert (await send(state, "GET", "/organisation")).json()["name"] == "Alpha Sales"
    replay = await send(state, "PATCH", "/organisation", body={"name": "Alpha Sales"}, key=key)
    assert replay.status_code == 200 and replay.json() == renamed.json()
    refused(
        await send(state, "PATCH", "/organisation", body={"name": "Changed"}, key=key),
        409,
        "idempotency_conflict",
    )
    with Session(state.engine) as db:
        assert verify_audit_chain_sync(db, tenant_id=state.tenant).valid
        audit = db.scalars(select(AuditEvent).where(AuditEvent.tenant_id == state.tenant)).one()
        assert audit.action == "organisation.renamed"
        assert audit.actor_person_id == state.person
        assert (audit.payload["before"], audit.payload["after"]) == (
            {"name": "Alpha"},
            {"name": "Alpha Sales"},
        )


async def test_rename_refuses_other_roles_origin_and_personal(state):  # noqa: F811
    body = {"name": "Not Allowed"}
    # The fixture's other person is this organisation's admin.
    admin = await send(state, "PATCH", "/organisation", body=body, key=uuid4(), token=OTHER_TOKEN)
    refused(admin, 403, "authorization_denied")
    assert (
        await send(state, "PATCH", "/organisation", body=body, key=uuid4(), origin=None)
    ).status_code == 403
    for selected in (None, state.tenants["Beta"]):
        with Session(state.engine) as db, db.begin():
            db.get(IdentitySession, state.session).selected_tenant_id = selected
        personal = await send(state, "PATCH", "/organisation", body=body, key=uuid4())
        assert personal.status_code == 404
        assert personal.json()["detail"] == "No organisation selected."
        assert (await send(state, "GET", "/organisation/usage")).status_code == 404
    with Session(state.engine) as db:
        assert db.get(Tenant, state.tenant).name == "Alpha"
        assert db.scalar(select(AuditEvent).where(AuditEvent.tenant_id == state.tenant)) is None


async def test_usage_schema_window_settlement_and_role_scope(state):  # noqa: F811
    now = datetime.now(UTC)
    with Session(state.engine) as db, db.begin():
        rows = [
            usage_row(state, tenant, person, seconds, created)
            for tenant, person, seconds, created in (
                (state.tenant, state.person, 90, now - timedelta(hours=1)),
                (state.tenant, state.person, 120, now - timedelta(hours=2)),
                (state.tenant, state.person, 180, now - timedelta(hours=3)),
                (state.tenant, state.person, 600, now - timedelta(days=31)),
                (state.tenant, state.other, 30, now - timedelta(days=2)),
                # Personal use and another tenant never count for this organisation.
                (state.tenants["Beta"], state.person, 600, now),
            )
        ]
        db.add_all(rows)
        db.flush()
        db.add_all(
            [
                Settlement(
                    usage_id=rows[1].id,
                    charged_seconds=60,
                    kind="completed",
                    receipt_sha256="c" * 64,
                    created_at=now,
                ),
                Settlement(
                    usage_id=rows[2].id,
                    charged_seconds=0,
                    kind="no_work_performed",
                    receipt_sha256="d" * 64,
                    created_at=now,
                ),
            ]
        )
    response = await send(state, "GET", "/organisation/usage?days=30")
    assert response.status_code == 200, response.text
    assert "no-store" in response.headers["cache-control"]
    body = response.json()
    assert list(body) == ["since", "total_seconds", "total_calls", "members", "pool"]
    assert body["since"].endswith("Z") and body["pool"] is None
    since = datetime.fromisoformat(body["since"])
    assert abs(since - (now - timedelta(days=30))) < timedelta(minutes=1)
    members = {row["person_id"]: row for row in body["members"]}
    assert set(members) == {str(state.person), str(state.other), str(state.member)}
    own = members[str(state.person)]
    assert own == {
        "person_id": str(state.person),
        "name": "synthetic-owner@example.test",
        "seconds": 150,
        "calls": 3,
        "last_call_at": own["last_call_at"],
    }
    assert datetime.fromisoformat(own["last_call_at"]) == now - timedelta(hours=1)
    assert members[str(state.member)] == {
        "person_id": str(state.member),
        "name": "Fictional Rep",
        "seconds": 0,
        "calls": 0,
        "last_call_at": None,
    }
    assert (body["total_seconds"], body["total_calls"]) == (180, 4)
    UsageResponse.model_validate_json(json.dumps(body))
    with pytest.raises(ValidationError):
        UsageResponse.model_validate_json(json.dumps(dict(body, extra=1)))
    assert (await send(state, "GET", "/organisation/usage")).json()["total_seconds"] == 180
    wide = (await send(state, "GET", "/organisation/usage?days=90")).json()
    assert (wide["total_seconds"], wide["total_calls"]) == (780, 5)
    for query in ("days=7", "days=abc", "days=30&team=x", "since=2026-01-01"):
        refused(await send(state, "GET", f"/organisation/usage?{query}"), 422, "validation_failed")
    # An admin sees every member; a member sees only their own row and totals.
    admin = (await send(state, "GET", "/organisation/usage", token=OTHER_TOKEN)).json()
    assert admin["members"] == body["members"]
    with Session(state.engine) as db, db.begin():
        db.get(Membership, (state.tenant, state.other)).role = "member"
    member = (await send(state, "GET", "/organisation/usage", token=OTHER_TOKEN)).json()
    assert [row["person_id"] for row in member["members"]] == [str(state.other)]
    assert (member["total_seconds"], member["total_calls"]) == (30, 1)


async def test_usage_window_includes_its_boundary_instant(state):  # noqa: F811
    edge = datetime(2026, 9, 1, 12, 0, tzinfo=UTC)
    with Session(state.engine) as db, db.begin():
        db.add(usage_row(state, state.tenant, state.member, 45, edge))
        db.flush()
        database = cast(Any, HttpDatabase(db))
        assert (await member_usage(database, state.tenant, edge))[state.member][:2] == (45, 1)
        later = await member_usage(database, state.tenant, edge + timedelta(microseconds=1))
        assert later[state.member][:2] == (0, 0)
