"""Canonical email sign-in -> required profile -> read-only edge eligibility.

Uses a fresh migrated loopback PostgreSQL schema and real HTTP route handlers.
Only email delivery is omitted; challenge decryption is confined to test data.
"""

from __future__ import annotations

from datetime import timedelta
from uuid import UUID, uuid4

import httpx
import pytest
from fastapi import FastAPI
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.orm import Session

from ac_platform.audit.models import AuditEvent
from ac_platform.http.auth import install_identity_http
from ac_platform.http.problem import register_problem_handlers
from ac_platform.http.sales_xray_profile import install_sales_xray_profile_http
from ac_platform.identity.email_login import decrypt_email_login_code
from ac_platform.identity.models import EmailLoginCode, Person
from ac_platform.identity.models import Session as IdentitySession
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
PROFILE = "/v1/me/sales-xray-profile"
ELIGIBILITY = PROFILE + "/write-eligibility"


@pytest.fixture(scope="module")
def postgres_harness():
    yield from _postgres_harness.__wrapped__()


def test_email_account_profile_eligibility_and_repeat_login_share_one_identity(
    postgres_harness: _Harness,
) -> None:
    async def scenario() -> None:
        public_tenant, operations_tenant = uuid4(), uuid4()
        email = f"account-journey-{uuid4().hex}@example.test"
        consent = "account-journey-consent-v1"
        with Session(postgres_harness.engine) as database, database.begin():
            database.add_all(
                [
                    Tenant(id=public_tenant, slug=public_tenant.hex, name="Synthetic Academy"),
                    Tenant(id=operations_tenant, slug=operations_tenant.hex, name="Synthetic Ops"),
                ]
            )
        settings = _email_code_settings(
            postgres_harness.schema_url,
            public_tenant_id=public_tenant,
            operations_tenant_id=operations_tenant,
            consent_version=consent,
        )
        engine = create_async_engine(postgres_harness.schema_url, pool_pre_ping=True)
        sessions = async_sessionmaker(engine, expire_on_commit=False)
        application = FastAPI()
        register_problem_handlers(application)
        require_actor = install_identity_http(application, settings=settings, sessions=sessions)
        install_sales_xray_profile_http(application, settings=settings, require_actor=require_actor)

        def issued_code() -> str:
            with Session(postgres_harness.engine) as database:
                row = database.scalar(
                    select(EmailLoginCode).where(EmailLoginCode.normalized_email == email)
                )
                assert row is not None
                return decrypt_email_login_code(
                    settings.email_challenge_secret.get_secret_value(),
                    row,
                    generation_id=row.generation_id,
                )

        try:
            async with httpx.AsyncClient(
                transport=httpx.ASGITransport(app=application),
                base_url=ORIGIN,
                headers={"Origin": ORIGIN},
            ) as client:
                assert (await client.get(ELIGIBILITY)).status_code == 401
                config = await client.get("/v1/auth/email-code/config?surface=sales_xray")
                assert config.status_code == 200 and config.json()["consent_version"] == consent
                rejected_consent = await client.post(
                    "/v1/auth/email-code/request",
                    json={
                        "email": email,
                        "consent": True,
                        "consent_version": "अमान्य",
                        "age_attested": True,
                        "surface": "sales_xray",
                        "return_path": "/",
                    },
                )
                assert rejected_consent.status_code == 202
                assert rejected_consent.json()["accepted"] is True
                with Session(postgres_harness.engine) as database:
                    assert (
                        database.scalar(
                            select(EmailLoginCode.id).where(
                                EmailLoginCode.normalized_email == email
                            )
                        )
                        is None
                    )
                requested = await client.post(
                    "/v1/auth/email-code/request",
                    json={
                        "email": email.upper(),
                        "consent": True,
                        "consent_version": consent,
                        "age_attested": True,
                        "surface": "sales_xray",
                        "return_path": "/",
                    },
                )
                assert requested.status_code == 202
                with Session(postgres_harness.engine) as database:
                    assert database.scalar(select(Person.id).where(Person.email == email)) is None
                verified = await client.post(
                    "/v1/auth/email-code/verify",
                    json={
                        "email": email,
                        "code": issued_code(),
                        "surface": "sales_xray",
                        "return_path": "/",
                    },
                )
                assert verified.status_code == 200
                identity = verified.json()
                person_id = UUID(identity["person_id"])
                assert identity["account_created"] is True
                assert identity["profile_complete"] is False
                cookie = verified.headers["set-cookie"].lower()
                assert "httponly" in cookie and "samesite=lax" in cookie
                assert ("secure" in cookie) is settings.secure_cookies
                assert "domain=" not in cookie
                assert (await client.get("/v1/me")).json()["selected_tenant_id"] == str(
                    public_tenant
                )
                profile = await client.get(PROFILE)
                assert profile.status_code == 200
                assert profile.json()["revision"] == 0
                assert profile.json()["phone_verified"] is False
                assert (await client.get(ELIGIBILITY)).status_code == 403
                fields = {
                    "full_name": "Synthetic Account",
                    "phone_number_e164": "+12025550123",
                    "expected_revision": 0,
                }
                cross_origin = await client.put(
                    PROFILE, json=fields, headers={"Origin": "https://untrusted.example.test"}
                )
                assert cross_origin.status_code == 403
                saved = await client.put(PROFILE, json=fields)
                assert saved.status_code == 200
                assert saved.json()["profile_complete"] is True
                assert saved.json()["phone_verified"] is False
                assert saved.json()["revision"] == 1
                assert (await client.put(PROFILE, json=fields)).status_code == 409

                with Session(postgres_harness.engine) as database:
                    consent_events = list(
                        database.scalars(
                            select(AuditEvent).where(
                                AuditEvent.tenant_id == public_tenant,
                                AuditEvent.actor_person_id == person_id,
                                AuditEvent.action == "identity.learner_consent_accepted.v1",
                                AuditEvent.resource_type == "person_consent",
                                AuditEvent.resource_id == str(person_id),
                            )
                        )
                    )
                    assert len(consent_events) == 1
                    assert consent_events[0].payload["consent_version"] == consent
                    assert consent_events[0].payload["accepted_via"] == "email_otp"
                    assert consent_events[0].payload["age_attestation"] == (
                        "18_plus_learner_declaration"
                    )
                    session_row = database.scalar(
                        select(IdentitySession).where(IdentitySession.person_id == person_id)
                    )
                    assert session_row is not None
                    last_seen_before = session_row.last_seen_at
                    session_id = session_row.id
                    audit_count_before = database.scalar(
                        select(func.count()).select_from(AuditEvent)
                    )
                for _ in range(2):
                    eligible = await client.get(ELIGIBILITY)
                    assert eligible.status_code == 204 and eligible.content == b""
                    assert eligible.headers["cache-control"] == "private, no-store"
                    assert eligible.headers["vary"] == "Cookie"
                    assert "set-cookie" not in eligible.headers
                assert (
                    await client.get(ELIGIBILITY + "?person_id=" + str(uuid4()))
                ).status_code == 404
                with Session(postgres_harness.engine) as database:
                    assert (
                        database.get(IdentitySession, session_id).last_seen_at == last_seen_before
                    )
                    assert database.scalar(select(func.count()).select_from(AuditEvent)) == (
                        audit_count_before
                    )
                    profile_events = list(
                        database.scalars(
                            select(AuditEvent).where(
                                AuditEvent.resource_id == str(person_id),
                                AuditEvent.action == "sales_xray.profile.self_updated.v1",
                            )
                        )
                    )
                    assert len(profile_events) == 1

                assert (await client.post("/v1/auth/logout")).status_code == 204
                assert (await client.get(ELIGIBILITY)).status_code == 401
                # Age this test-only challenge instead of sleeping through the
                # real resend interval. No production or provider state exists.
                with Session(postgres_harness.engine) as database, database.begin():
                    challenge = database.scalar(
                        select(EmailLoginCode).where(EmailLoginCode.normalized_email == email)
                    )
                    challenge.issued_at -= timedelta(seconds=61)
                requested_again = await client.post(
                    "/v1/auth/email-code/request",
                    json={"email": email, "surface": "sales_xray", "return_path": "/"},
                )
                assert requested_again.status_code == 202
                signed_in_again = await client.post(
                    "/v1/auth/email-code/verify",
                    json={
                        "email": email,
                        "code": issued_code(),
                        "surface": "sales_xray",
                        "return_path": "/",
                    },
                )
                assert signed_in_again.status_code == 200
                assert signed_in_again.json()["person_id"] == str(person_id)
                assert signed_in_again.json()["account_created"] is False
                assert signed_in_again.json()["profile_complete"] is True
                assert (await client.get(ELIGIBILITY)).status_code == 204
                with Session(postgres_harness.engine) as database, database.begin():
                    assert (
                        database.scalar(
                            select(func.count()).select_from(Person).where(Person.email == email)
                        )
                        == 1
                    )
                    assert (
                        database.scalar(
                            select(func.count())
                            .select_from(Membership)
                            .where(Membership.person_id == person_id)
                        )
                        == 1
                    )
                    assert database.scalar(
                        select(func.count())
                        .select_from(AuditEvent)
                        .where(
                            AuditEvent.tenant_id == public_tenant,
                            AuditEvent.actor_person_id == person_id,
                            AuditEvent.action == "identity.learner_consent_accepted.v1",
                            AuditEvent.resource_type == "person_consent",
                            AuditEvent.resource_id == str(person_id),
                        )
                    ) == 1
                    database.get(Person, person_id).status = "suspended"
                assert (await client.get(ELIGIBILITY)).status_code in (401, 403)
        finally:
            await engine.dispose()

    _run_async(scenario())
