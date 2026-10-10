"""Real sign-in routes, joins, row locks and failure isolation on local PostgreSQL."""

import asyncio
from datetime import UTC, datetime
from typing import Any, cast
from uuid import UUID, uuid4, uuid5

import httpx
import pytest
from fastapi import FastAPI
from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.orm import Session

import ac_platform.organisations.sign_in as sign_in
from ac_platform.application.settings import Settings
from ac_platform.audit.models import AuditEvent
from ac_platform.audit.service import verify_audit_chain_sync
from ac_platform.http.auth import install_identity_http
from ac_platform.http.problem import register_problem_handlers
from ac_platform.identity.email_login import decrypt_email_login_code
from ac_platform.identity.models import EmailLoginCode, Person, ProviderIdentity
from ac_platform.identity.models import Session as IdentitySession
from ac_platform.organisations.service import OrganisationService, _tenant_slug
from ac_platform.tenancy.models import Membership, OrganisationInvite, Tenant
from tests.integration.test_media_delivery_renewal_postgresql import postgres_harness  # noqa: F401
from tests.integration.test_password_identity_http_postgresql import _ExistingGoogleProvider
from tests.unit.http.test_organisation_seat_exemptions import install_approval
from tests.unit.organisations.test_service import seed_paid_seats


def _organisation_name(name: str, case_id: UUID) -> str:
    return f"{case_id.hex} {name}"


def test_organisation_fixture_tenant_ids_preserve_full_case_namespace():
    names = (
        "Fictional invited organisation",
        "Fictional domain organisation",
        "Fictional concurrent sign-in",
        "Fictional claim 0",
        "Fictional claim 1",
    )
    cases = [
        (_organisation_name(name, case_id), uuid5(case_id, name))
        for case_id in (UUID(int=1), UUID(int=2))
        for name in names
    ]
    slugs = [_tenant_slug(name, tenant_id) for name, tenant_id in cases]
    assert len(set(slugs)) == len(slugs)
    assert all(
        slug.endswith(tenant_id.hex) for slug, (_, tenant_id) in zip(slugs, cases, strict=True)
    )
    assert all(len(slug) <= 63 for slug in slugs)


@pytest.mark.parametrize("method", ["email", "google_authenticate", "google_register"])
@pytest.mark.parametrize(
    "fail_hook,seat_mode",
    [(False, "paid"), (False, "exempt"), (False, "full"), (True, "paid"), ("database", "paid")],
)
def test_verified_sign_in_accepts_invite_and_domain_join_without_blocking_session(
    postgres_harness,  # noqa: F811
    monkeypatch,
    method,
    fail_hook,  # noqa: F811
    seat_mode,
    tmp_path,
):
    async def exercise():
        engine = create_async_engine(postgres_harness.schema_url)
        sessions = async_sessionmaker(engine, expire_on_commit=False)
        owner, person, operations, public = (uuid4() for _ in range(4))
        email_domain = f"{person.hex}.example.test"
        email, subject = f"rep@{email_domain}", f"subject-{person.hex}"
        settings = Settings(
            _env_file=None,
            environment="test",
            operations_tenant_id=operations,
            public_learner_tenant_id=public,
            learner_consent_version="fictional-consent-v1",
            public_app_url="https://app.authorityclosers.test",
            api_url="https://api.authorityclosers.test",
        )
        try:
            async with sessions() as db, db.begin():
                db.add_all(
                    [
                        Tenant(id=operations, name="Fixture ops", slug=f"ops-{operations.hex}"),
                        Tenant(id=public, name="Fixture learners", slug=f"public-{public.hex}"),
                        Person(
                            id=owner,
                            email=f"owner-{owner.hex}@owner.test",
                            email_verified_at=datetime.now(UTC),
                        ),
                    ]
                )
                if method != "google_register":
                    db.add(
                        Person(
                            id=person,
                            email=email,
                            email_verified_at=datetime.now(UTC),
                            consent_version=settings.learner_consent_version,
                            consented_at=datetime.now(UTC),
                        )
                    )
                await db.flush()
                if method == "google_authenticate":
                    db.add(
                        ProviderIdentity(
                            person_id=person, issuer="https://accounts.google.com", subject=subject
                        )
                    )
                service = OrganisationService(
                    db, operations_tenant_id=operations, public_learner_tenant_id=public
                )
                invited = await service.create(
                    _organisation_name("Fictional invited organisation", operations),
                    owner,
                    uuid4(),
                    "AUT-448 fixture",
                )
                domain = await service.create(
                    _organisation_name("Fictional domain organisation", operations),
                    owner,
                    uuid4(),
                    "AUT-448 fixture",
                )
                await service.set_domains_attested(
                    domain.tenant_id, [email_domain], True, "fictional proof", uuid4()
                )
                if seat_mode != "exempt":
                    await seed_paid_seats(
                        db, domain.tenant_id, owner, seats=1 if seat_mode == "full" else 3
                    )
                db.add(
                    OrganisationInvite(
                        tenant_id=invited.tenant_id,
                        email_normalized=email,
                        role="admin",
                        command_id=uuid4(),
                    )
                )
            if fail_hook:

                async def fail(*args, **kwargs):
                    if fail_hook == "database":
                        await args[0].execute(text("SELECT CAST('fictional' AS integer)"))
                    raise RuntimeError("fictional audit failure")

                monkeypatch.setattr(sign_in, "append_audit_event", fail)
            provider = _ExistingGoogleProvider(email=email, subject=subject)
            app = FastAPI()
            if seat_mode == "exempt":
                from types import SimpleNamespace

                install_approval(
                    SimpleNamespace(app=app, settings=settings, tenant=domain.tenant_id), tmp_path
                )
            register_problem_handlers(app)
            install_identity_http(
                app, settings=settings, sessions=cast(Any, sessions), provider=provider
            )
            async with httpx.AsyncClient(
                transport=httpx.ASGITransport(app=app, client=("127.0.0.1", 12345)),
                base_url="https://app.authorityclosers.test",
            ) as client:
                if method == "email":
                    request = await client.post(
                        "/v1/auth/email-code/request",
                        json={"email": email, "surface": "learner"},
                        headers={"Origin": "https://app.authorityclosers.test"},
                    )
                    assert request.status_code == 202
                    with Session(postgres_harness.engine) as db:
                        challenge = db.scalar(
                            select(EmailLoginCode).where(EmailLoginCode.normalized_email == email)
                        )
                        assert challenge is not None
                        code = decrypt_email_login_code(
                            settings.email_challenge_secret.get_secret_value(),
                            challenge,
                            generation_id=challenge.generation_id,
                        )
                    response = await client.post(
                        "/v1/auth/email-code/verify",
                        json={"email": email, "code": code, "surface": "learner"},
                        headers={"Origin": "https://app.authorityclosers.test"},
                    )
                    assert response.status_code == 200 and response.json()["authenticated"] is True
                else:
                    params = {
                        "action": "register" if method == "google_register" else "authenticate",
                        "surface": "learner",
                        "return_path": "/home",
                    }
                    if method == "google_register":
                        params["consent"] = "true"
                    start = await client.get("/v1/auth/google/start", params=params)
                    assert start.status_code == 303
                    response = await client.get(
                        "/v1/auth/google/callback",
                        params={
                            "state": provider.transactions[-1].state,
                            "code": "controlled-google-code",
                        },
                    )
                    assert response.status_code == 303
                    assert response.headers["location"] == "https://app.authorityclosers.test/home"
                assert settings.session_cookie_name in client.cookies
            with Session(postgres_harness.engine) as db:
                signed_in = db.scalar(select(Person).where(Person.email == email))
                assert signed_in is not None
                memberships = [
                    db.get(Membership, (tenant, signed_in.id))
                    for tenant in [invited.tenant_id, domain.tenant_id]
                ]
                invite = db.scalar(
                    select(OrganisationInvite).where(
                        OrganisationInvite.tenant_id == invited.tenant_id
                    )
                )
                assert (
                    db.scalar(
                        select(func.count())
                        .select_from(IdentitySession)
                        .where(IdentitySession.person_id == signed_in.id)
                    )
                    == 1
                )
                if fail_hook:
                    assert memberships == [None, None] and invite.status == "pending"
                else:
                    assert memberships[0].role == "admin"
                    assert (memberships[1] is None) is (seat_mode == "full")
                    if seat_mode != "full":
                        assert memberships[1].role == "member"
                    assert invite.status == "accepted" and invite.accepted_person_id == signed_in.id
                    for tenant in [invited.tenant_id, domain.tenant_id]:
                        event = db.scalar(
                            select(AuditEvent).where(
                                AuditEvent.tenant_id == tenant,
                                AuditEvent.action == "organisation.member_joined",
                            )
                        )
                        if tenant == domain.tenant_id and seat_mode == "full":
                            assert event is None
                            continue
                        assert event.actor_person_id == signed_in.id
                        assert event.reason == (
                            "invite_accepted" if tenant == invited.tenant_id else "domain_auto_join"
                        )
                        assert verify_audit_chain_sync(db, tenant).valid
        finally:
            await engine.dispose()

    asyncio.run(exercise())


@pytest.mark.parametrize("distinct_people", [False, True])
def test_concurrent_sign_ins_use_one_seat_and_join_event(postgres_harness, distinct_people):  # noqa: F811
    async def exercise():
        engine = create_async_engine(postgres_harness.schema_url)
        sessions = async_sessionmaker(engine, expire_on_commit=False)
        owner, person, operations, public = (uuid4() for _ in range(4))
        second = uuid4() if distinct_people else person
        email_domain = f"race-{person.hex}.example.test"
        settings = Settings(
            _env_file=None,
            environment="test",
            operations_tenant_id=operations,
            public_learner_tenant_id=public,
        )
        try:
            async with sessions() as db, db.begin():
                db.add_all(
                    [
                        Person(
                            id=owner,
                            email=f"owner-{owner.hex}@example.test",
                            email_verified_at=datetime.now(UTC),
                        ),
                        Person(
                            id=person,
                            email=f"rep@{email_domain}",
                            email_verified_at=datetime.now(UTC),
                        ),
                    ]
                )
                if distinct_people:
                    db.add(
                        Person(
                            id=second,
                            email=f"other@{email_domain}",
                            email_verified_at=datetime.now(UTC),
                        )
                    )
                await db.flush()
                service = OrganisationService(
                    db, operations_tenant_id=operations, public_learner_tenant_id=public
                )
                org = await service.create(
                    _organisation_name("Fictional concurrent sign-in", operations),
                    owner,
                    uuid4(),
                    "AUT-448 fixture",
                )
                await service.set_domains_attested(
                    org.tenant_id, [email_domain], True, "fictional proof", uuid4()
                )
                await seed_paid_seats(db, org.tenant_id, owner, seats=2)

            async def join(person_id):
                async with sessions() as db, db.begin():
                    await sign_in.join_at_sign_in_best_effort(db, person_id, settings=settings)

            await asyncio.wait_for(asyncio.gather(join(person), join(second)), timeout=15)
            with Session(postgres_harness.engine) as db:
                joined = [db.get(Membership, (org.tenant_id, p)) for p in {person, second}]
                assert sum(member is not None for member in joined) == 1
                assert next(member for member in joined if member is not None).role == "member"
                assert (
                    db.scalar(
                        select(func.count())
                        .select_from(AuditEvent)
                        .where(
                            AuditEvent.tenant_id == org.tenant_id,
                            AuditEvent.action == "organisation.member_joined",
                        )
                    )
                    == 1
                )
                assert verify_audit_chain_sync(db, org.tenant_id).valid
        finally:
            await engine.dispose()

    asyncio.run(exercise())


def test_concurrent_domain_claims_have_one_winner_and_no_partial_history(postgres_harness):  # noqa: F811
    async def exercise():
        from ac_platform.organisations.service import OrganisationDomainConflict
        from ac_platform.tenancy.models import OrganisationDomainSetting

        engine = create_async_engine(postgres_harness.schema_url)
        sessions = async_sessionmaker(engine, expire_on_commit=False)
        owner, operations, public = (uuid4() for _ in range(3))
        email_domain = f"claim-{owner.hex}.example.test"
        try:
            async with sessions() as db, db.begin():
                db.add(
                    Person(
                        id=owner,
                        email=f"owner-{owner.hex}@example.test",
                        email_verified_at=datetime.now(UTC),
                    )
                )
                await db.flush()
                service = OrganisationService(
                    db, operations_tenant_id=operations, public_learner_tenant_id=public
                )
                orgs = [
                    (
                        await service.create(
                            _organisation_name(f"Fictional claim {i}", operations),
                            owner,
                            uuid4(),
                            "AUT-448 fixture",
                        )
                    ).tenant_id
                    for i in range(2)
                ]

            async def verify(domain, token):
                assert domain == email_domain and len(token) >= 43
                await asyncio.sleep(0.01)

            async def claim(tenant):
                try:
                    async with sessions() as db, db.begin():
                        service = OrganisationService(
                            db, operations_tenant_id=operations, public_learner_tenant_id=public
                        )
                        await service.set_domains_attested(
                            tenant,
                            [email_domain],
                            True,
                            f"dns_txt:{owner}",
                            uuid4(),
                            actor_person_id=owner,
                            verify_domain=verify,
                        )
                    return "verified"
                except OrganisationDomainConflict:
                    return "conflict"

            outcomes = await asyncio.wait_for(
                asyncio.gather(*(claim(tenant) for tenant in orgs)), timeout=15
            )
            assert sorted(outcomes) == ["conflict", "verified"]
            with Session(postgres_harness.engine) as db:
                assert (
                    db.scalar(
                        select(func.count())
                        .select_from(OrganisationDomainSetting)
                        .where(OrganisationDomainSetting.tenant_id.in_(orgs))
                    )
                    == 1
                )
                assert (
                    db.scalar(
                        select(func.count())
                        .select_from(AuditEvent)
                        .where(
                            AuditEvent.tenant_id.in_(orgs),
                            AuditEvent.action == "organisation.domains_set",
                        )
                    )
                    == 1
                )
                for tenant in orgs:
                    assert verify_audit_chain_sync(db, tenant).valid
        finally:
            await engine.dispose()

    asyncio.run(exercise())
