"""PostgreSQL proof: Settings -> Security -> Delete account asks for the account's deletion
in the app (Google Play). With DELETE typed on a fresh session it opens the deletion
request, signs the account out everywhere, keeps every sign-in out, writes the audit event
and queues both emails; staff, a stale session, a wrong word or an organisation that still
needs its owner change nothing."""

from __future__ import annotations

from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID, uuid4

import httpx
import pytest
from fastapi import FastAPI
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.orm import Session

from ac_platform.audit.models import AuditEvent
from ac_platform.http.auth import install_identity_http
from ac_platform.http.problem import register_problem_handlers
from ac_platform.http.routes import RouteContext
from ac_platform.http.routes.account_deletion import install as install_account_deletion
from ac_platform.identity.account_deletion import (
    ACCOUNT_CLOSED_ACTION,
    ACCOUNT_CLOSED_EVENT,
    DELETION_REQUESTED_EVENT,
)
from ac_platform.identity.application import AsyncIdentityApplication
from ac_platform.identity.models import DeletionRequest, Person
from ac_platform.identity.models import Session as IdentitySession
from ac_platform.identity.services import AccountClosedError
from ac_platform.outbox.models import OutboxEvent
from ac_platform.tenancy.models import (
    Membership,
    MembershipRole,
    MembershipStatus,
    Organisation,
    Tenant,
)
from tests.integration.test_password_identity_http_postgresql import _Harness, _run_async
from tests.integration.test_password_identity_http_postgresql import (
    postgres_harness as _postgres_harness,
)
from tests.integration.test_sales_xray_provider_sign_in_postgresql import (
    SALES_ORIGIN,
    _settings,
)

PATH = "/v1/me/account-deletion"
VERIFIED = datetime(2026, 9, 1, tzinfo=UTC)


@pytest.fixture(scope="module")
def postgres_harness() -> Iterator[_Harness]:
    yield from _postgres_harness.__wrapped__()


def _person(database: Session, label: str) -> UUID:
    person_id = uuid4()
    database.add(
        Person(
            id=person_id,
            email=f"{label}-{person_id.hex}@example.test",
            email_verified_at=VERIFIED,
            consent_version="v1",
            consented_at=VERIFIED,
        )
    )
    database.flush()
    return person_id


def _seed(harness: _Harness, *, staff: bool = False) -> tuple[UUID, UUID]:
    tenant_id = uuid4()
    with Session(harness.engine) as database, database.begin():
        database.add(Tenant(id=tenant_id, slug=f"sx-delete-{tenant_id.hex}", name="Synthetic"))
        person_id = _person(database, "delete")
        if staff:
            ops = uuid4()
            database.add(Tenant(id=ops, slug=f"sx-ops-{ops.hex}", name="Ops"))
            database.flush()
            database.add(
                Membership(
                    tenant_id=ops,
                    person_id=person_id,
                    role=MembershipRole.SUPPORT.value,
                    status=MembershipStatus.ACTIVE.value,
                )
            )
    return tenant_id, person_id


def _organisation(harness: _Harness, owner_id: UUID, name: str, *, members: int) -> UUID:
    tenant_id = uuid4()
    with Session(harness.engine) as database, database.begin():
        database.add(Tenant(id=tenant_id, slug=f"sx-org-{tenant_id.hex}", name=name))
        database.flush()
        database.add(
            Organisation(
                tenant_id=tenant_id,
                created_by_person_id=owner_id,
                creation_command_id=uuid4(),
                domain_verification_token=uuid4().hex * 2,
            )
        )
        database.add(
            Membership(
                tenant_id=tenant_id,
                person_id=owner_id,
                role=MembershipRole.OWNER.value,
                status=MembershipStatus.ACTIVE.value,
            )
        )
        for _ in range(members):
            database.add(
                Membership(
                    tenant_id=tenant_id,
                    person_id=_person(database, "member"),
                    role=MembershipRole.MEMBER.value,
                    status=MembershipStatus.ACTIVE.value,
                )
            )
    return tenant_id


async def _call(
    harness: _Harness,
    *,
    tenant_id: UUID,
    person_id: UUID,
    method: str,
    age: timedelta = timedelta(minutes=1),
    body: dict[str, Any] | None = None,
    origin: str = SALES_ORIGIN,
    other_devices: int = 0,
) -> httpx.Response:
    engine = create_async_engine(harness.schema_url, pool_pre_ping=True)
    sessions = async_sessionmaker(engine, expire_on_commit=False)
    settings = _settings(harness, tenant_id=tenant_id)
    try:
        async with sessions() as database, database.begin():
            identity = AsyncIdentityApplication(
                database, token_pepper=settings.session_token_pepper.get_secret_value()
            )
            for _ in range(other_devices):
                await identity.issue_authenticated_session(person_id, user_agent="phone")
            issued = await identity.issue_authenticated_session(person_id, user_agent="test")
            await database.execute(
                update(IdentitySession)
                .where(IdentitySession.id == issued.metadata.id)
                .values(created_at=datetime.now(UTC) - age)
            )
        application = FastAPI()
        register_problem_handlers(application)
        require_actor = install_identity_http(application, settings=settings, sessions=sessions)
        install_account_deletion(
            application,
            RouteContext(settings=settings, require_actor=require_actor, sessions=sessions),
        )
        transport = httpx.ASGITransport(app=application, client=("127.0.0.1", 12345))
        async with httpx.AsyncClient(
            transport=transport,
            base_url=SALES_ORIGIN,
            cookies={settings.session_cookie_name: issued.token},
        ) as client:
            return await client.request(method, PATH, headers={"origin": origin}, json=body)
    finally:
        await engine.dispose()


def _state(harness: _Harness, person_id: UUID) -> dict[str, Any]:
    with Session(harness.engine) as database:
        sessions = list(
            database.scalars(select(IdentitySession).where(IdentitySession.person_id == person_id))
        )
        events = list(
            database.scalars(
                select(AuditEvent).where(
                    AuditEvent.actor_person_id == person_id,
                    AuditEvent.action == ACCOUNT_CLOSED_ACTION,
                )
            )
        )
        return {
            "requests": list(
                database.scalars(
                    select(DeletionRequest).where(DeletionRequest.person_id == person_id)
                )
            ),
            "open_sessions": sum(1 for row in sessions if row.revoked_at is None),
            "revoked": [row.revocation_reason for row in sessions if row.revoked_at is not None],
            "events": events,
            "emails": sorted(
                (row.event_type, row.payload["audit_event_id"])
                for row in database.scalars(
                    select(OutboxEvent).where(OutboxEvent.aggregate_id == person_id)
                )
                if row.event_type in {ACCOUNT_CLOSED_EVENT, DELETION_REQUESTED_EVENT}
            ),
        }


def test_the_preview_says_what_closes_and_which_organisation_needs_a_new_owner(
    postgres_harness: _Harness,
) -> None:
    tenant_id, person_id = _seed(postgres_harness)
    team = _organisation(postgres_harness, person_id, "Bright Team", members=2)
    solo = _organisation(postgres_harness, person_id, "Solo Desk", members=0)
    response = _run_async(
        _call(postgres_harness, tenant_id=tenant_id, person_id=person_id, method="GET")
    )
    assert response.status_code == 200
    assert response.headers["cache-control"] == "private, no-store"
    assert response.json() == {
        "confirm_word": "DELETE",
        "fresh_sign_in": True,
        "fresh_minutes": 10,
        "staff": False,
        "transfer_first": [{"id": str(team), "name": "Bright Team", "other_members": 2}],
        "closes_with_account": [{"id": str(solo), "name": "Solo Desk"}],
    }


def test_delete_closes_the_account_signs_out_everywhere_and_keeps_sign_in_out(
    postgres_harness: _Harness,
) -> None:
    tenant_id, person_id = _seed(postgres_harness)
    solo = _organisation(postgres_harness, person_id, "Solo Desk", members=0)
    response = _run_async(
        _call(
            postgres_harness,
            tenant_id=tenant_id,
            person_id=person_id,
            method="POST",
            body={"confirm": " delete "},
            other_devices=1,
        )
    )
    assert response.status_code == 200, response.text
    assert response.json()["closed"] is True
    cookie = response.headers.get("set-cookie", "")
    assert "Max-Age=0" in cookie or "max-age=0" in cookie.lower()

    state = _state(postgres_harness, person_id)
    [request] = state["requests"]
    assert request.status == "requested"
    assert state["open_sessions"] == 0
    assert state["revoked"] == ["account closed for deletion"] * 2
    [event] = state["events"]
    assert event.payload == {
        "deletion_request_id": str(request.id),
        "sessions_revoked": 2,
        "organisations_closing": [str(solo)],
        "ip_address": "127.0.0.1",
    }
    assert state["emails"] == sorted(
        [(ACCOUNT_CLOSED_EVENT, str(event.id)), (DELETION_REQUESTED_EVENT, str(event.id))]
    )

    async def sign_in_again() -> None:
        engine = create_async_engine(postgres_harness.schema_url, pool_pre_ping=True)
        try:
            async with async_sessionmaker(engine)() as database, database.begin():
                await AsyncIdentityApplication(
                    database, token_pepper="p" * 32
                ).issue_authenticated_session(person_id)
        finally:
            await engine.dispose()

    with pytest.raises(AccountClosedError):
        _run_async(sign_in_again())


@pytest.mark.parametrize(
    ("staff", "members", "age", "word", "status", "code"),
    [
        (False, None, timedelta(minutes=1), "remove", 422, "confirm"),
        (False, None, timedelta(minutes=30), "DELETE", 403, "fresh_sign_in"),
        (True, None, timedelta(minutes=1), "DELETE", 403, "staff"),
        (False, 1, timedelta(minutes=1), "DELETE", 409, "transfer_ownership_first"),
    ],
    ids=["wrong-word", "stale-session", "staff", "organisation-needs-an-owner"],
)
def test_a_refused_delete_changes_nothing(
    postgres_harness: _Harness,
    staff: bool,
    members: int | None,
    age: timedelta,
    word: str,
    status: int,
    code: str,
) -> None:
    tenant_id, person_id = _seed(postgres_harness, staff=staff)
    team = (
        None
        if members is None
        else _organisation(postgres_harness, person_id, "Bright Team", members=members)
    )
    response = _run_async(
        _call(
            postgres_harness,
            tenant_id=tenant_id,
            person_id=person_id,
            method="POST",
            age=age,
            body={"confirm": word},
        )
    )
    assert response.status_code == status
    detail = response.json()["detail"]
    assert detail["code"] == code
    if team is not None:
        assert detail["organisations"] == [
            {"id": str(team), "name": "Bright Team", "other_members": members}
        ]
    state = _state(postgres_harness, person_id)
    assert state["requests"] == [] and state["events"] == [] and state["emails"] == []
    assert state["open_sessions"] == 1


def test_another_origin_is_refused(postgres_harness: _Harness) -> None:
    tenant_id, person_id = _seed(postgres_harness)
    response = _run_async(
        _call(
            postgres_harness,
            tenant_id=tenant_id,
            person_id=person_id,
            method="POST",
            body={"confirm": "DELETE"},
            origin="https://attacker.example",
        )
    )
    assert response.status_code == 403
    assert _state(postgres_harness, person_id)["requests"] == []
