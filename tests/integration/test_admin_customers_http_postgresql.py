"""Fictional C2 directory proof against the lane's disposable PostgreSQL schema."""

import json
from datetime import UTC, datetime, timedelta
from hashlib import sha256
from hmac import digest
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import UUID, uuid4

import httpx
import pytest
from fastapi import FastAPI
from sqlalchemy import event, select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from ac_platform.application.settings import Settings
from ac_platform.authorization.application import CapabilityApplication
from ac_platform.authorization.policy import CapabilityScope
from ac_platform.billing.ledger import BillingLedger
from ac_platform.billing.models import BillingAccount, BillingLedgerEntry
from ac_platform.conversation_intelligence.acquisition_challenge import UploadChallenge
from ac_platform.conversation_intelligence.acquisition_models import (
    ConversationAcquisitionSettlement,
    ConversationAcquisitionUsage,
    ConversationVisitor,
    ConversationVisitorClaim,
)
from ac_platform.conversation_intelligence.acquisition_sessions import AcquisitionSessions
from ac_platform.http.admin_customers import install_admin_customers_http
from ac_platform.http.auth import install_identity_http
from ac_platform.http.conversation_acquisition import install_acquisition_http
from ac_platform.http.problem import register_problem_handlers
from ac_platform.identity.models import Person
from ac_platform.identity.models import Session as IdentitySession
from ac_platform.kernel.authz import ActorContext
from ac_platform.tenancy.models import Membership, Organisation, Tenant
from tests.database.test_conversation_postgresql import postgres_harness as _postgres_harness

ORIGIN = "https://admin.example.test"
PATH = "/v1/admin/customers"
CREATED = datetime(2026, 10, 1, 12, tzinfo=UTC)
PUBLIC, OPERATIONS, ORG, OTHER = (UUID(int=value) for value in range(101, 105))


@pytest.fixture
def postgres_harness():
    yield from _postgres_harness.__wrapped__()


@pytest.fixture
async def directory(postgres_harness):
    engine = create_async_engine(postgres_harness.url)
    sessions = async_sessionmaker(engine, expire_on_commit=False)
    settings = Settings(
        _env_file=None,
        environment="test",
        admin_app_url=ORIGIN,
        public_app_url="https://learner.example.test",
        sales_xray_app_url="https://salesxray.example.test",
        public_learner_tenant_id=PUBLIC,
        operations_tenant_id=OPERATIONS,
        sales_xray_trial_policy="v1",
    )
    ids = {
        label: UUID(int=index)
        for index, label in enumerate(
            (
                "personal",
                "organisation",
                "dual",
                "staff",
                "suspended",
                "deleted",
                "other",
                "manager",
                "operator",
                "forbidden",
            ),
            1,
        )
    }
    tokens = {
        label: label[0] * 43 for label in ("manager", "operator", "personal", "dual", "forbidden")
    }
    session_ids = {label: UUID(int=1000 + ids[label].int) for label in tokens}
    manager = ActorContext(ids["manager"], session_ids["manager"], OPERATIONS)
    try:
        async with sessions() as db, db.begin():
            db.add_all(
                Tenant(id=tenant, slug=str(tenant), name=name)
                for tenant, name in (
                    (PUBLIC, "Fictional Personal"),
                    (OPERATIONS, "Fictional Operations"),
                    (ORG, "Fictional Organisation"),
                    (OTHER, "Unregistered tenant"),
                )
            )
            db.add_all(
                Person(
                    id=person,
                    email=None if label == "deleted" else f"{label}@example.test",
                    display_name=None if label == "deleted" else f"Fictional {label.title()}",
                    status=label if label in {"suspended", "deleted"} else "active",
                    created_at=CREATED,
                    email_verified_at=CREATED,
                )
                for label, person in ids.items()
            )
            await db.flush()
            db.add(
                Organisation(
                    tenant_id=ORG, creation_command_id=uuid4(), domain_verification_token="x" * 43
                )
            )
            for label, tenants in {
                "personal": (PUBLIC,),
                "organisation": (ORG,),
                "dual": (PUBLIC, ORG),
                "staff": (OPERATIONS,),
                "suspended": (PUBLIC,),
                "deleted": (PUBLIC,),
                "other": (OTHER,),
                "manager": (OPERATIONS,),
                "forbidden": (OPERATIONS,),
            }.items():
                db.add_all(
                    Membership(
                        tenant_id=tenant,
                        person_id=ids[label],
                        role="owner"
                        if tenant == OPERATIONS
                        else "member"
                        if tenant == ORG
                        else "learner",
                        status="inactive" if label == "suspended" else "active",
                        ended_at=CREATED if label == "suspended" else None,
                    )
                    for tenant in tenants
                )
            await db.flush()
            now = datetime.now(UTC)
            pepper = settings.session_token_pepper.get_secret_value().encode()
            db.add_all(
                IdentitySession(
                    id=session_ids[label],
                    person_id=ids[label],
                    token_hash=digest(pepper, token.encode(), sha256),
                    selected_tenant_id=PUBLIC if label in {"personal", "dual"} else None,
                    created_at=now - timedelta(hours=1),
                    expires_at=now + timedelta(days=1),
                    last_seen_at=CREATED + timedelta(minutes=1) if label == "personal" else None,
                )
                for label, token in tokens.items()
            )
            await db.flush()
            capabilities = CapabilityApplication(db, operations_tenant_id=OPERATIONS)
            await capabilities.bootstrap_first_manager(
                person_id=ids["manager"], command_id=uuid4(), reason="Fictional bootstrap"
            )
            grant = await capabilities.grant(
                manager,
                command_id=uuid4(),
                subject_person_id=ids["operator"],
                permission="platform_tenants_read",
                scope=CapabilityScope("platform"),
                reason="Fictional directory read",
            )
        app = FastAPI()
        register_problem_handlers(app)
        actor = install_identity_http(app, settings=settings, sessions=sessions)
        install_admin_customers_http(app, settings=settings, require_actor=actor)
        yield SimpleNamespace(
            engine=engine,
            sessions=sessions,
            app=app,
            actor=actor,
            settings=settings,
            ids=ids,
            tokens=tokens,
            session_ids=session_ids,
            manager=manager,
            grant=grant,
        )
    finally:
        await engine.dispose()


async def _get(client, query="", **kwargs):
    response = await client.get(PATH + query, **kwargs)
    assert response.headers["cache-control"] == "no-store"
    return response


async def test_shapes_categories_status_and_literal_search(directory, record_property):
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=directory.app), base_url=ORIGIN
    ) as client:
        client.cookies.set(directory.settings.session_cookie_name, directory.tokens["operator"])
        listed = await _get(client)
        assert listed.status_code == 200, listed.text
        body = listed.json()
        assert set(body) == {"items", "next_cursor"} and body["next_cursor"] is None
        assert [row["person_id"] for row in body["items"]] == [
            str(directory.ids[label])
            for label in ("deleted", "suspended", "dual", "organisation", "personal")
        ]
        for row in body["items"]:
            assert set(row) == {
                "person_id",
                "name",
                "email",
                "status",
                "created_at",
                "last_active_at",
                "personal",
                "organisations",
            }
            assert row["created_at"] == "2026-10-01T12:00:00Z"
            if row["personal"] is not None:
                assert row["personal"] == {
                    "plan_key": "trial",
                    "available_seconds": 3600,
                    "used_seconds_30d": 0,
                }
            for org in row["organisations"]:
                assert org == {
                    "tenant_id": str(ORG),
                    "name": "Fictional Organisation",
                    "role": "member",
                }
        assert body["items"][0]["name"] is body["items"][0]["email"] is None
        assert body["items"][3]["personal"] is None
        assert body["items"][-1]["last_active_at"] == "2026-10-01T12:01:00Z"
        record_property("a1b_customer_list_fixture", json.dumps(body, sort_keys=True))
        for query, labels in (
            ("?kind=personal", {"personal", "dual", "suspended", "deleted"}),
            ("?kind=organisation", {"organisation", "dual"}),
            ("?status=suspended", {"suspended"}),
            ("?status=deleted", {"deleted"}),
            ("?status=active", {"personal", "organisation", "dual"}),
            ("?q=PERSONAL", {"personal"}),
            ("?q=tional%20du", {"dual"}),
            ("?q=%40example", set()),
            ("?q=%25_", set()),
            ("?q=&kind=personal&status=active", {"personal", "dual"}),
        ):
            response = await _get(client, query)
            assert response.status_code == 200, response.text
            assert {row["person_id"] for row in response.json()["items"]} == {
                str(directory.ids[label]) for label in labels
            }


async def test_keyset_validation_fresh_authority_surface_and_no_store(directory):
    async with directory.sessions() as db, db.begin():
        db.add_all(
            Person(id=UUID(int=i), email=f"page-{i}@example.test", created_at=CREATED)
            for i in range(20, 72)
        )
        await db.flush()
        db.add_all(
            Membership(tenant_id=ORG, person_id=UUID(int=i), role="member") for i in range(20, 72)
        )
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=directory.app), base_url=ORIGIN
    ) as client:
        response = await _get(client)
        assert (response.status_code, response.json()["code"]) == (401, "authentication_required")
        client.cookies.set(directory.settings.session_cookie_name, directory.tokens["forbidden"])
        response = await _get(client)
        assert (response.status_code, response.json()["code"]) == (403, "authorization_denied")
        client.cookies.set(directory.settings.session_cookie_name, directory.tokens["operator"])
        response = await client.get("https://learner.example.test" + PATH)
        assert response.status_code == 403 and response.json()["code"] == "admin_surface_required"
        assert response.headers["cache-control"] == "no-store"
        assert len((await _get(client)).json()["items"]) == 25
        assert len((await _get(client, "?limit=50")).json()["items"]) == 50
        seen, cursor = [], None
        while True:
            query = "?limit=7" + ("&cursor=" + cursor if cursor else "")
            page = (await _get(client, query)).json()
            seen.extend(row["person_id"] for row in page["items"])
            cursor = page["next_cursor"]
            if cursor is None:
                break
        assert len(seen) == len(set(seen)) == 57
        assert seen == sorted(seen, key=lambda value: UUID(value).int, reverse=True)
        for query in (
            "?unknown=1",
            "?limit=1&limit=1",
            "?q=aa&q=aa",
            "?kind=staff",
            "?status=inactive",
            "?limit=0",
            "?limit=51",
            "?limit=1.0",
            "?q=a",
            "?q=" + "a" * 121,
            "?cursor=",
            "?cursor=not-a-cursor",
            "?cursor=W10",
            "?cursor=!!",
        ):
            invalid = await _get(client, query)
            assert invalid.status_code == 422 and invalid.json()["code"] == "validation_failed"
            assert invalid.headers["content-type"].startswith("application/problem+json")
        async with directory.sessions() as db, db.begin():
            await CapabilityApplication(db, operations_tenant_id=OPERATIONS).revoke(
                directory.manager,
                command_id=uuid4(),
                grant_id=directory.grant.id,
                reason="Fictional fresh revocation",
            )
        revoked = await _get(client)
        assert revoked.status_code == 403 and revoked.json()["code"] == "authorization_denied"


async def test_personal_projection_parity_isolation_and_read_only(directory, monkeypatch):
    now = datetime.now(UTC)
    async with directory.sessions() as db, db.begin():
        visitor, stranger = uuid4(), uuid4()
        db.add_all(
            ConversationVisitor(
                id=identity,
                tenant_id=PUBLIC,
                token_hash=identity.bytes * 2,
                created_at=now,
                expires_at=now + timedelta(days=1),
            )
            for identity in (visitor, stranger)
        )
        # Same person, foreign tenant: it must not change their Personal summary.
        db.add(Membership(tenant_id=ORG, person_id=directory.ids["personal"], role="member"))
        await db.flush()
        db.add(
            ConversationVisitorClaim(
                visitor_id=visitor,
                tenant_id=PUBLIC,
                person_id=directory.ids["personal"],
                session_id=directory.session_ids["personal"],
                created_at=now,
            )
        )
        for label, tenant, guest, reserved, charged, age in (
            ("personal", PUBLIC, None, 120, 30, 0),
            ("personal", PUBLIC, None, 40, None, 0),
            ("personal", PUBLIC, None, 10, 0, 0),
            ("personal", PUBLIC, None, 90, None, 31),
            (None, PUBLIC, visitor, 20, None, 0),
            (None, PUBLIC, stranger, 70, None, 0),
            ("dual", PUBLIC, None, 55, None, 0),
            ("personal", ORG, None, 777, None, 0),
        ):
            usage_id = uuid4()
            db.add(
                ConversationAcquisitionUsage(
                    id=usage_id,
                    tenant_id=tenant,
                    person_id=directory.ids[label] if label else None,
                    visitor_id=guest,
                    submission_id=uuid4(),
                    source_sha256="a" * 64,
                    duration_evidence_sha256="b" * 64,
                    reserved_seconds=reserved,
                    policy_revision="fictional-v1",
                    created_at=now - timedelta(days=age),
                )
            )
            await db.flush()
            if charged is not None:
                db.add(
                    ConversationAcquisitionSettlement(
                        usage_id=usage_id,
                        charged_seconds=charged,
                        kind="no_work_performed" if charged == 0 else "completed",
                        receipt_sha256="c" * 64,
                        created_at=now,
                    )
                )
    install_acquisition_http(
        directory.app,
        settings=directory.settings,
        sessions=directory.sessions,
        require_actor=directory.actor,
        factory=lambda db, tenant: AcquisitionSessions(
            db, tenant_id=tenant, policy_revision="fictional-v1", operations_tenant_id=OPERATIONS
        ),
        challenge=UploadChallenge(
            secret=directory.settings.session_token_pepper, hostname="salesxray.example.test"
        ),
    )
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=directory.app), base_url=ORIGIN
    ) as client:
        client.cookies.set(directory.settings.session_cookie_name, directory.tokens["operator"])
        statements = []

        def capture(conn, cursor, statement, parameters, context, executemany):
            statements.append(statement)

        event.listen(directory.engine.sync_engine, "before_cursor_execute", capture)
        try:
            response = await _get(client, "?q=personal")
        finally:
            event.remove(directory.engine.sync_engine, "before_cursor_execute", capture)
        assert response.status_code == 200, response.text
        assert all(statement.lstrip().upper().startswith("SELECT") for statement in statements)
        summary = response.json()["items"][0]["personal"]
        assert summary == {"plan_key": "trial", "available_seconds": 3420, "used_seconds_30d": 90}
        other = (await _get(client, "?q=dual")).json()["items"][0]["personal"]
        assert other == {"plan_key": "trial", "available_seconds": 3545, "used_seconds_30d": 55}
        client.cookies.set(directory.settings.session_cookie_name, directory.tokens["personal"])
        for path in ("/v1/me/plan", "/v1/me/usage"):
            me = await client.get("https://salesxray.example.test" + path)
            assert me.status_code == 200, me.text
            assert me.json()["allowance"]["available_seconds"] == summary["available_seconds"]
        async with directory.sessions() as db:
            assert await db.scalar(select(BillingAccount.id).limit(1)) is None
            assert await db.scalar(select(BillingLedgerEntry.id).limit(1)) is None
        client.cookies.set(directory.settings.session_cookie_name, directory.tokens["operator"])
        with monkeypatch.context() as context:
            context.setattr(
                BillingLedger,
                "project_person",
                AsyncMock(side_effect=ValueError("Fictional unavailable projection")),
            )
            unavailable = await _get(client, "?q=personal")
            assert (
                unavailable.status_code == 503
                and unavailable.json()["code"] == "customer_read_unavailable"
            )
        directory.settings.public_learner_tenant_id = None
        unavailable = await _get(client)
        assert (
            unavailable.status_code == 503
            and unavailable.json()["code"] == "customer_read_unavailable"
        )
