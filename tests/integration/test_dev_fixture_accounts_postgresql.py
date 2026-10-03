"""Dev fixture accounts on fresh migrated PostgreSQL, proven through the app's HTTP routes."""

from __future__ import annotations

from uuid import UUID, uuid4

import httpx
import pytest
from fastapi import FastAPI
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.orm import Session

from ac_platform.authorization.models import CapabilityGrant
from ac_platform.development import sales_xray_fixture_accounts as fixture
from ac_platform.development.sales_xray_fixture_accounts import (
    ACCOUNTS,
    PASSWORD_VARIABLES,
    seed_fixture_accounts,
)
from ac_platform.http.auth import install_identity_http
from ac_platform.http.problem import register_problem_handlers
from ac_platform.identity.models import EmailChallenge, Person
from ac_platform.identity.password_auth import PasswordIdentityService
from ac_platform.outbox.models import OutboxEvent
from ac_platform.tenancy.learner_provisioning import AsyncLearnerProvisioningApplication
from ac_platform.tenancy.models import Membership, Tenant
from tests.integration.test_password_identity_http_postgresql import (
    _email_code_settings,
    _Harness,
    _run_async,
)
from tests.integration.test_password_identity_http_postgresql import (
    postgres_harness as _postgres_harness,
)

ORIGIN = "https://salesxray.authorityclosers.test"
CONSENT = "dev-fixture-consent-v1"
PASSWORDS = {kind: f"fictional-{kind}-password-only" for kind in ACCOUNTS}


@pytest.fixture(scope="module")
def postgres_harness():
    yield from _postgres_harness.__wrapped__()


def test_fixture_accounts_sign_in_on_sales_xray_and_rerun_is_a_no_op(
    postgres_harness: _Harness,
) -> None:
    async def scenario() -> None:
        public_tenant, operations_tenant = uuid4(), uuid4()
        staff_email = f"staff-{uuid4().hex}@authorityclosers.test"
        with Session(postgres_harness.engine) as database, database.begin():
            database.add_all(
                [
                    Tenant(id=public_tenant, slug=public_tenant.hex, name="Synthetic Public"),
                    Tenant(id=operations_tenant, slug=operations_tenant.hex, name="Synthetic Ops"),
                    Person(id=uuid4(), email=staff_email, first_name="Staff"),
                ]
            )
        settings = _email_code_settings(
            postgres_harness.schema_url,
            public_tenant_id=public_tenant,
            operations_tenant_id=operations_tenant,
            consent_version=CONSENT,
        )
        engine = create_async_engine(postgres_harness.schema_url, pool_pre_ping=True)
        sessions = async_sessionmaker(engine, expire_on_commit=False)

        async def seed(passwords: dict[str, str] = PASSWORDS) -> dict[str, UUID]:
            async with sessions() as database, database.begin():
                return await seed_fixture_accounts(
                    database,
                    passwords=passwords,
                    secret=settings.email_challenge_secret.get_secret_value(),
                    public_tenant_id=public_tenant,
                    consent_version=CONSENT,
                )

        def snapshot() -> tuple[object, ...]:
            with Session(postgres_harness.engine) as database:
                return tuple(
                    database.scalar(select(func.count()).select_from(model))
                    for model in (Person, Membership, EmailChallenge, OutboxEvent, CapabilityGrant)
                ) + (database.scalar(select(Person.revision).where(Person.email == staff_email)),)

        application = FastAPI()
        register_problem_handlers(application)
        install_identity_http(application, settings=settings, sessions=sessions)
        try:
            # A later mismatch must roll back the earlier new fixture accounts.
            async with sessions() as database, database.begin():
                secret = settings.email_challenge_secret.get_secret_value()
                identity = PasswordIdentityService(database, token_secret=secret)
                registration = await identity.register(
                    email=ACCOUNTS["member"],
                    first_name="SX Member",
                    whatsapp_number=fixture.FIXTURE_PHONE,
                    password=PASSWORDS["member"],
                    consent_version=CONSENT,
                )
                person = await fixture.verify_registration_without_mail(
                    database, identity, registration, secret=secret
                )
                await AsyncLearnerProvisioningApplication(database).ensure(
                    person_id=person.id,
                    tenant_id=public_tenant,
                    required_consent_version=CONSENT,
                )
            before = snapshot()
            with pytest.raises(ValueError, match="does not accept its fixture password"):
                await seed({**PASSWORDS, "member": "a-different-fictional-password"})
            assert snapshot() == before
            ids = await seed()
            assert list(ids) == list(ACCOUNTS.values())
            with Session(postgres_harness.engine) as database:
                fixture_ids = set(ids.values())
                memberships = database.scalars(
                    select(Membership).where(Membership.person_id.in_(fixture_ids))
                ).all()
                assert sorted((m.person_id, m.tenant_id, m.role) for m in memberships) == sorted(
                    (person_id, public_tenant, "learner") for person_id in fixture_ids
                )
                assert database.scalar(select(func.count()).select_from(OutboxEvent)) == 0
                assert database.scalar(select(func.count()).select_from(CapabilityGrant)) == 0
                assert all(
                    challenge.consumed_at is not None
                    for challenge in database.scalars(
                        select(EmailChallenge).where(EmailChallenge.person_id.in_(fixture_ids))
                    )
                )
            for kind, email in ACCOUNTS.items():
                async with httpx.AsyncClient(
                    transport=httpx.ASGITransport(app=application),
                    base_url=ORIGIN,
                    headers={"Origin": ORIGIN},
                ) as client:
                    login = await client.post(
                        "/v1/auth/password/login",
                        json={"email": email, "password": PASSWORDS[kind]},
                    )
                    assert login.status_code == 200, login.text
                    assert login.json()["person_id"] == str(ids[email])
                    workspaces = await client.get("/v1/me/workspaces")
                    assert workspaces.status_code == 200
                    assert workspaces.json()["selected_tenant_id"] == str(public_tenant)
                    assert [w["tenant_id"] for w in workspaces.json()["workspaces"]] == [
                        str(public_tenant)
                    ]

            before = snapshot()
            assert await seed() == ids
            assert snapshot() == before
            with pytest.raises(ValueError, match="does not accept its fixture password"):
                await seed({**PASSWORDS, "member": "a-different-fictional-password"})
            assert snapshot() == before
        finally:
            await engine.dispose()

    _run_async(scenario())


@pytest.mark.parametrize(
    ("environment", "database_url"),
    [
        ("test", None),
        ("staging", None),
        ("development", "postgresql+psycopg://ac_runtime@postgres:5432/ac_platform"),
        ("development", None),
    ],
)
def test_wrong_environment_or_database_refuses_before_connecting(
    postgres_harness: _Harness, monkeypatch, environment: str, database_url: str | None
) -> None:
    # The harness database is real but is not the dev endpoint, so it must refuse.
    settings = _email_code_settings(
        postgres_harness.schema_url,
        public_tenant_id=uuid4(),
        operations_tenant_id=uuid4(),
        consent_version=CONSENT,
    ).model_copy(
        update={
            "environment": environment,
            "database_url": database_url
            or postgres_harness.schema_url.render_as_string(hide_password=False),
        }
    )
    for kind, value in PASSWORDS.items():
        monkeypatch.setenv(PASSWORD_VARIABLES[kind], value)
    monkeypatch.setattr(fixture, "Settings", lambda **_: settings)
    with Session(postgres_harness.engine) as database:
        people = database.scalar(select(func.count()).select_from(Person))
    with pytest.raises(ValueError, match="Only the development database"):
        fixture.main(["--acknowledge-development-fixtures"])
    with Session(postgres_harness.engine) as database:
        assert database.scalar(select(func.count()).select_from(Person)) == people
