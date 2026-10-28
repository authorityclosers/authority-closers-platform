"""Real session locks, provisioning, consent and audit, on a disposable test schema.

Uses the existing password HTTP sandbox settings/harness. Never a deployed DB.
"""

from __future__ import annotations

import asyncio
import base64
import hashlib
from datetime import UTC, datetime, timedelta
from urllib.parse import parse_qs, urlsplit
from uuid import uuid4

import httpx
import pytest
from fastapi import FastAPI
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.orm import Session

from ac_platform.audit.models import AuditEvent
from ac_platform.audit.service import verify_audit_chain_sync
from ac_platform.http.auth import install_identity_http
from ac_platform.http.auth_transactions import CROSS_APP_HANDOFF_ERROR, CrossAppHandoffCodec
from ac_platform.http.problem import register_problem_handlers
from ac_platform.identity.application import AsyncIdentityApplication
from ac_platform.identity.learner_consent import CURRENT_LEARNER_CONSENT_VERSION
from ac_platform.identity.models import DeletionRequest, Person
from ac_platform.identity.models import Session as SessionRow
from ac_platform.tenancy.models import Membership, Tenant
from tests.integration.test_password_identity_http_postgresql import (
    _email_code_settings,
    _Harness,
    _run_async,
)
from tests.integration.test_password_identity_http_postgresql import (
    postgres_harness as _postgres_harness,
)

VERIFIER = "a" * 43
CHALLENGE = (
    base64.urlsafe_b64encode(hashlib.sha256(VERIFIER.encode()).digest()).rstrip(b"=").decode()
)


@pytest.fixture(scope="module")
def postgres_harness():
    yield from _postgres_harness.__wrapped__()


@pytest.mark.parametrize("consent", ["current", "outdated", "missing"])
@pytest.mark.parametrize(
    "source_role,source_count,existing_learner",
    [
        ("owner", 1, False),
        ("viewer", 1, False),
        ("learner", 0, False),
        ("owner", 2, False),
        ("viewer", 1, True),
    ],
)
def test_real_exchange_and_consent_completion(
    postgres_harness: _Harness,
    consent: str,
    source_role: str,
    source_count: int,
    existing_learner: bool,
):
    async def scenario():
        public_id, organisation_id, person_id = uuid4(), uuid4(), uuid4()
        current = CURRENT_LEARNER_CONSENT_VERSION
        with Session(postgres_harness.engine) as database, database.begin():
            database.add_all(
                [
                    Tenant(id=public_id, slug=public_id.hex, name="Synthetic Academy"),
                    Tenant(
                        id=organisation_id, slug=organisation_id.hex, name="Synthetic Workspace"
                    ),
                    Person(
                        id=person_id,
                        email=f"handoff-{person_id.hex}@example.test",
                        email_verified_at=datetime.now(UTC),
                        consent_version=current
                        if consent == "current"
                        else "previous"
                        if consent == "outdated"
                        else None,
                        consented_at=datetime.now(UTC) if consent != "missing" else None,
                    ),
                ]
            )
            database.flush()
            if source_count:
                database.add(
                    Membership(tenant_id=organisation_id, person_id=person_id, role=source_role)
                )
            if source_count == 2:
                extra_id = uuid4()
                database.add(Tenant(id=extra_id, slug=extra_id.hex, name="Other Workspace"))
                database.flush()
                database.add(Membership(tenant_id=extra_id, person_id=person_id, role="viewer"))
            if existing_learner:
                database.add(Membership(tenant_id=public_id, person_id=person_id, role="learner"))
        settings = _email_code_settings(
            postgres_harness.schema_url,
            public_tenant_id=public_id,
            operations_tenant_id=organisation_id,
            consent_version=current,
        )
        learner = str(settings.public_app_url).rstrip("/")
        sales = str(settings.sales_xray_app_url).rstrip("/")
        engine = create_async_engine(postgres_harness.schema_url)
        sessions = async_sessionmaker(engine, expire_on_commit=False)
        application = FastAPI()
        register_problem_handlers(application)
        install_identity_http(application, settings=settings, sessions=sessions)
        try:
            async with sessions() as database, database.begin():
                identity = AsyncIdentityApplication(
                    database, token_pepper=settings.session_token_pepper.get_secret_value()
                )
                source = await identity.issue_authenticated_session(person_id)
                if source_count:
                    await identity.select_tenant(source.token, organisation_id)
            async with httpx.AsyncClient(transport=httpx.ASGITransport(app=application)) as client:
                started = await client.post(
                    sales + "/v1/auth/handoff/start",
                    headers={
                        "origin": sales,
                        "cookie": f"{settings.session_cookie_name}={source.token}",
                    },
                    json={
                        "target": "learner",
                        "challenge": CHALLENGE,
                        "return_path": "/learning?tab=mine",
                    },
                )
                assert started.status_code == 200
                code = parse_qs(urlsplit(started.json()["url"]).fragment)["code"][0]
                handoff = CrossAppHandoffCodec(
                    settings.oauth_transaction_secret.get_secret_value()
                ).decode(code)
                with Session(postgres_harness.engine) as database:
                    assert database.get(SessionRow, handoff.session_id).selected_tenant_id is None
                payload = {"code": code, "verifier": VERIFIER}
                exchanged = await client.post(
                    learner + "/v1/auth/handoff/redeem", headers={"origin": learner}, json=payload
                )
                assert exchanged.status_code == 200
                expected = (
                    "success"
                    if consent == "current"
                    else "consent_update_required"
                    if consent == "outdated"
                    else "consent_required"
                )
                assert exchanged.json() == {"result": expected, "return_path": "/learning?tab=mine"}
                token = exchanged.cookies[settings.session_cookie_name]
                assert token not in {source.token, handoff.session_token}
                assert "domain=" not in exchanged.headers["set-cookie"].lower()
                replay = await client.post(
                    learner + "/v1/auth/handoff/redeem", headers={"origin": learner}, json=payload
                )
                assert (
                    replay.status_code == 400 and replay.json()["detail"] == CROSS_APP_HANDOFF_ERROR
                )
                with Session(postgres_harness.engine) as database:
                    assert database.get(SessionRow, handoff.session_id).revoked_at is not None
                    assert database.get(SessionRow, source.metadata.id).revoked_at is None
                    recorded = database.get(Person, person_id)
                    assert recorded.consent_version == (
                        current
                        if consent == "current"
                        else "previous"
                        if consent == "outdated"
                        else None
                    )
                    assert (
                        database.scalar(select(func.count(Person.id)).where(Person.id == person_id))
                        == 1
                    )
                    events = list(
                        database.scalars(
                            select(AuditEvent)
                            .where(AuditEvent.tenant_id == public_id)
                            .order_by(AuditEvent.sequence_no)
                        )
                    )
                    assert [event.action for event in events] == [
                        "identity.cross_app_handoff_started.v1",
                        "identity.cross_app_handoff_redeemed.v1",
                    ]
                    assert events[0].session_id == handoff.session_id
                    assert handoff.session_token not in str([event.payload for event in events])
                    assert verify_audit_chain_sync(database, public_id).valid
                me = await client.get(
                    learner + "/v1/me",
                    headers={"cookie": f"{settings.session_cookie_name}={token}"},
                )
                assert me.status_code == 200
                assert me.json()["selected_tenant_id"] == (
                    str(public_id) if consent == "current" else None
                )
                if consent != "current":
                    assert me.json()["membership_role"] is None
                    assert me.json()["permissions"] == []
                    # Pending consent leaves even an existing learner membership unselected.
                    with Session(postgres_harness.engine) as database:
                        membership = database.get(Membership, (public_id, person_id))
                        assert (membership is not None) is existing_learner
                    renewed = await client.post(
                        learner + "/v1/me/consent/renew",
                        headers={
                            "origin": learner,
                            "cookie": f"{settings.session_cookie_name}={token}",
                        },
                        json={"expected_version": current, "accepted": True},
                    )
                    assert renewed.status_code == 200
                    assert renewed.json()["replayed"] is False
                    with Session(postgres_harness.engine) as database:
                        accepted_at = database.get(Person, person_id).consented_at
                        acceptance = database.scalar(
                            select(AuditEvent).where(
                                AuditEvent.actor_person_id == person_id,
                                AuditEvent.action == "identity.learner_consent_accepted.v1",
                            )
                        )
                        assert acceptance.tenant_id == public_id
                        acceptance_id = acceptance.id
                    # Retry must preserve the consent audit and selected learner context.
                    again = await client.post(
                        learner + "/v1/me/consent/renew",
                        headers={
                            "origin": learner,
                            "cookie": f"{settings.session_cookie_name}={token}",
                        },
                        json={"expected_version": current, "accepted": True},
                    )
                    assert again.status_code == 200
                    assert again.json()["replayed"] is True
                    assert again.json()["consented_at"] == renewed.json()["consented_at"]
                    with Session(postgres_harness.engine) as database:
                        acceptances = list(
                            database.scalars(
                                select(AuditEvent).where(
                                    AuditEvent.actor_person_id == person_id,
                                    AuditEvent.action == "identity.learner_consent_accepted.v1",
                                )
                            )
                        )
                        assert len(acceptances) == 1
                        assert acceptances[0].id == acceptance_id
                        assert acceptances[0].tenant_id == public_id
                        assert database.get(Person, person_id).consented_at == accepted_at
                        assert verify_audit_chain_sync(database, public_id).valid
                async with sessions() as database, database.begin():
                    resolved = await AsyncIdentityApplication(
                        database, token_pepper=settings.session_token_pepper.get_secret_value()
                    ).resolve_actor(token)
                    assert resolved.actor.tenant_id == public_id
                with Session(postgres_harness.engine) as database:
                    assert database.get(Membership, (public_id, person_id)).role == "learner"
                    assert database.get(Person, person_id).consent_version == current
        finally:
            await engine.dispose()

    _run_async(scenario())


def test_concurrent_redeem_works_once_and_failure_rolls_back(
    postgres_harness: _Harness, monkeypatch
):
    async def scenario():
        public_id, operations_id, person_id = uuid4(), uuid4(), uuid4()
        with Session(postgres_harness.engine) as database, database.begin():
            database.add_all(
                [
                    Tenant(id=public_id, slug=public_id.hex, name="Synthetic Academy"),
                    Tenant(id=operations_id, slug=operations_id.hex, name="Synthetic Operations"),
                    Person(
                        id=person_id,
                        email=f"race-{person_id.hex}@example.test",
                        email_verified_at=datetime.now(UTC),
                        consent_version=CURRENT_LEARNER_CONSENT_VERSION,
                        consented_at=datetime.now(UTC),
                    ),
                ]
            )
        settings = _email_code_settings(
            postgres_harness.schema_url,
            public_tenant_id=public_id,
            operations_tenant_id=operations_id,
            consent_version=CURRENT_LEARNER_CONSENT_VERSION,
        )
        learner, sales = (
            str(settings.public_app_url).rstrip("/"),
            str(settings.sales_xray_app_url).rstrip("/"),
        )
        engine = create_async_engine(postgres_harness.schema_url)
        sessions = async_sessionmaker(engine, expire_on_commit=False)
        application = FastAPI()
        register_problem_handlers(application)
        install_identity_http(application, settings=settings, sessions=sessions)
        try:
            async with sessions() as database, database.begin():
                source = await AsyncIdentityApplication(
                    database, token_pepper=settings.session_token_pepper.get_secret_value()
                ).issue_authenticated_session(person_id)
            async with httpx.AsyncClient(transport=httpx.ASGITransport(app=application)) as client:

                async def start():
                    response = await client.post(
                        sales + "/v1/auth/handoff/start",
                        headers={
                            "origin": sales,
                            "cookie": f"{settings.session_cookie_name}={source.token}",
                        },
                        json={"target": "learner", "challenge": CHALLENGE},
                    )
                    assert response.status_code == 200
                    return parse_qs(urlsplit(response.json()["url"]).fragment)["code"][0]

                code = await start()
                real_issue = AsyncIdentityApplication.issue_authenticated_session

                async def reject_issue(*args, **kwargs):
                    raise OSError("controlled issuance outage")

                monkeypatch.setattr(
                    AsyncIdentityApplication, "issue_authenticated_session", reject_issue
                )
                body = {"code": code, "verifier": VERIFIER}
                failed = await client.post(
                    learner + "/v1/auth/handoff/redeem", headers={"origin": learner}, json=body
                )
                assert failed.status_code == 400
                carried = CrossAppHandoffCodec(
                    settings.oauth_transaction_secret.get_secret_value()
                ).decode(code)
                with Session(postgres_harness.engine) as database:
                    assert database.get(SessionRow, carried.session_id).revoked_at is None
                    assert database.get(Membership, (public_id, person_id)) is None
                monkeypatch.setattr(
                    AsyncIdentityApplication, "issue_authenticated_session", real_issue
                )
                responses = await asyncio.gather(
                    *[
                        client.post(
                            learner + "/v1/auth/handoff/redeem",
                            headers={"origin": learner},
                            json=body,
                        )
                        for _ in range(2)
                    ]
                )
                assert sorted(item.status_code for item in responses) == [200, 400]
                with Session(postgres_harness.engine) as database:
                    assert (
                        database.scalar(
                            select(func.count(AuditEvent.id)).where(
                                AuditEvent.tenant_id == public_id,
                                AuditEvent.action == "identity.cross_app_handoff_redeemed.v1",
                            )
                        )
                        == 1
                    )
        finally:
            await engine.dispose()

    _run_async(scenario())


@pytest.mark.parametrize("invalid", ["suspended", "deleting", "expired", "reviewer", "revoked"])
@pytest.mark.parametrize("phase", ["start", "redeem"])
def test_real_person_and_session_fences(postgres_harness: _Harness, invalid, phase):
    async def scenario():
        public_id, operations_id, person_id = uuid4(), uuid4(), uuid4()
        with Session(postgres_harness.engine) as database, database.begin():
            database.add_all(
                [
                    Tenant(id=public_id, slug=public_id.hex, name="Synthetic Academy"),
                    Tenant(id=operations_id, slug=operations_id.hex, name="Synthetic Operations"),
                    Person(
                        id=person_id,
                        email=f"fence-{person_id.hex}@example.test",
                        email_verified_at=datetime.now(UTC),
                        consent_version=CURRENT_LEARNER_CONSENT_VERSION,
                        consented_at=datetime.now(UTC),
                    ),
                ]
            )
        settings = _email_code_settings(
            postgres_harness.schema_url,
            public_tenant_id=public_id,
            operations_tenant_id=operations_id,
            consent_version=CURRENT_LEARNER_CONSENT_VERSION,
        )
        learner, sales = (
            str(settings.public_app_url).rstrip("/"),
            str(settings.sales_xray_app_url).rstrip("/"),
        )
        engine = create_async_engine(postgres_harness.schema_url)
        sessions = async_sessionmaker(engine, expire_on_commit=False)
        application = FastAPI()
        register_problem_handlers(application)
        install_identity_http(application, settings=settings, sessions=sessions)

        def invalidate(session_id):
            with Session(postgres_harness.engine) as database, database.begin():
                if invalid == "suspended":
                    database.get(Person, person_id).status = "suspended"
                elif invalid == "deleting":
                    database.add(DeletionRequest(person_id=person_id))
                elif invalid == "expired":
                    row = database.get(SessionRow, session_id)
                    row.created_at = datetime.now(UTC) - timedelta(days=2)
                    row.expires_at = datetime.now(UTC) - timedelta(days=1)
                elif invalid == "revoked":
                    database.get(SessionRow, session_id).revoked_at = datetime.now(UTC)
                else:
                    database.get(SessionRow, session_id).audience = "reviewer"

        try:
            async with sessions() as database, database.begin():
                source = await AsyncIdentityApplication(
                    database, token_pepper=settings.session_token_pepper.get_secret_value()
                ).issue_authenticated_session(person_id)
            if phase == "start":
                invalidate(source.metadata.id)
            async with httpx.AsyncClient(transport=httpx.ASGITransport(app=application)) as client:
                response = await client.post(
                    sales + "/v1/auth/handoff/start",
                    headers={
                        "origin": sales,
                        "cookie": f"{settings.session_cookie_name}={source.token}",
                    },
                    json={"target": "learner", "challenge": CHALLENGE},
                )
                if phase == "start":
                    assert response.status_code in {401, 403}
                    assert settings.session_cookie_name not in response.cookies
                    with Session(postgres_harness.engine) as database:
                        assert (
                            database.scalar(
                                select(func.count(SessionRow.id)).where(
                                    SessionRow.person_id == person_id,
                                )
                            )
                            == 1
                        )
                        assert (
                            database.scalar(
                                select(func.count(AuditEvent.id)).where(
                                    AuditEvent.actor_person_id == person_id,
                                    AuditEvent.action == "identity.cross_app_handoff_started.v1",
                                )
                            )
                            == 0
                        )
                    return
                assert response.status_code == 200
                code = parse_qs(urlsplit(response.json()["url"]).fragment)["code"][0]
                handoff = CrossAppHandoffCodec(
                    settings.oauth_transaction_secret.get_secret_value()
                ).decode(code)
                invalidate(handoff.session_id)
                refused = await client.post(
                    learner + "/v1/auth/handoff/redeem",
                    headers={"origin": learner},
                    json={"code": code, "verifier": VERIFIER},
                )
                assert (
                    refused.status_code == 400
                    and refused.json()["detail"] == CROSS_APP_HANDOFF_ERROR
                )
                assert settings.session_cookie_name not in refused.cookies
                with Session(postgres_harness.engine) as database:
                    assert (
                        database.get(SessionRow, handoff.session_id).revoked_at is not None
                    ) is (invalid == "revoked")
        finally:
            await engine.dispose()

    _run_async(scenario())
