"""PostgreSQL proof for the Sales Xray Google full-acknowledgement route."""

from __future__ import annotations

import asyncio
import sys
from collections.abc import Coroutine
from datetime import UTC, datetime
from typing import Any
from uuid import UUID, uuid4

import httpx
import pytest
from fastapi import FastAPI
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.orm import Session

from ac_platform.application.settings import Settings
from ac_platform.audit.models import AuditEvent
from ac_platform.audit.service import AuditRepository
from ac_platform.http.auth import install_identity_http
from ac_platform.http.auth_transactions import AuthTransaction, AuthTransactionCodec
from ac_platform.http.problem import register_problem_handlers
from ac_platform.http.sales_xray_profile import install_sales_xray_profile_http
from ac_platform.identity.models import Person, ProviderAuthorizationTransaction, ProviderIdentity
from ac_platform.identity.models import Session as IdentitySession
from ac_platform.identity.sales_xray_profile_models import SalesXrayProfile
from ac_platform.identity.services import ProviderAuthorizationType, VerifiedProviderAssertion
from ac_platform.tenancy.models import Membership, Tenant
from tests.integration.test_password_identity_http_postgresql import (
    _Harness,
    _run_async,
)
from tests.integration.test_password_identity_http_postgresql import (
    postgres_harness as _postgres_harness,
)

SALES_ORIGIN = "https://salesxray.authorityclosers.test"
CONSENT_ACTION = "identity.learner_consent_accepted.v1"


@pytest.fixture(scope="module")
def postgres_harness():
    yield from _postgres_harness.__wrapped__()


class _GoogleProvider:
    audience = "postgres-sales-google-client.apps.googleusercontent.com"

    def __init__(self, *, email: str, subject: str, display_name: str) -> None:
        self.email = email
        self.subject = subject
        self.display_name = display_name
        self.transactions: list[AuthTransaction] = []
        self.exchange_calls = 0

    def authorization_url(self, transaction: AuthTransaction, *, redirect_uri: str) -> str:
        assert redirect_uri == f"{SALES_ORIGIN}/v1/auth/google/callback"
        self.transactions.append(transaction)
        return f"https://accounts.example.test/authorize?state={transaction.state}"

    async def exchange_code(
        self,
        code: str,
        transaction: AuthTransaction,
        *,
        callback_state: str,
        redirect_uri: str,
    ) -> VerifiedProviderAssertion:
        self.exchange_calls += 1
        assert code == "controlled-google-code"
        assert callback_state == transaction.state
        assert redirect_uri == f"{SALES_ORIGIN}/v1/auth/google/callback"
        return VerifiedProviderAssertion(
            issuer="https://accounts.google.com",
            subject=self.subject,
            audience=self.audience,
            state=callback_state,
            nonce=transaction.nonce,
            authorization_type=transaction.authorization_type,
            email=self.email,
            email_verified=True,
            display_name=self.display_name,
        )


def _run[T](coroutine: Coroutine[Any, Any, T]) -> T:
    if sys.platform == "win32":
        with asyncio.Runner(loop_factory=asyncio.SelectorEventLoop) as runner:
            return runner.run(coroutine)
    return asyncio.run(coroutine)


def _settings(harness: _Harness, *, tenant_id: UUID, consent_version: str) -> Settings:
    return Settings(
        environment="test",
        database_url=harness.schema_url.render_as_string(hide_password=False),
        session_token_pepper="postgres-sales-google-session-pepper-long-enough",  # noqa: S106
        oauth_transaction_secret="postgres-sales-google-transaction-secret-long-enough",  # noqa: S106
        email_challenge_secret="postgres-sales-google-email-secret-long-enough",  # noqa: S106
        learner_consent_version=consent_version,
        public_learner_tenant_id=tenant_id,
        operations_tenant_id=uuid4(),
        public_app_url="https://app.authorityclosers.test",
        admin_app_url="https://admin.authorityclosers.test",
        api_url="https://api.authorityclosers.test",
        sales_xray_app_url=SALES_ORIGIN,
    )


def _install_app(
    *,
    settings: Settings,
    sessions: async_sessionmaker,
    provider: _GoogleProvider,
    raise_app_exceptions: bool = True,
) -> tuple[FastAPI, httpx.ASGITransport]:
    application = FastAPI()
    register_problem_handlers(application)
    require_actor = install_identity_http(
        application,
        settings=settings,
        sessions=sessions,
        provider=provider,
    )
    install_sales_xray_profile_http(
        application,
        settings=settings,
        require_actor=require_actor,
    )
    return application, httpx.ASGITransport(
        app=application,
        client=("127.0.0.1", 12345),
        raise_app_exceptions=raise_app_exceptions,
    )


async def _start_and_callback(
    client: httpx.AsyncClient,
    provider: _GoogleProvider,
    *,
    consent_version: str,
) -> httpx.Response:
    started = await client.get(
        "/v1/auth/google/start",
        params={
            "action": "authenticate",
            "surface": "sales_xray",
            "consent": "true",
            "age_attested": "true",
            "consent_version": consent_version,
            "return_path": f"/auth/complete?flow={uuid4()}",
        },
        follow_redirects=False,
    )
    assert started.status_code == 303
    transaction = provider.transactions[-1]
    assert transaction.authorization_type is ProviderAuthorizationType.REGISTER
    assert transaction.age_attested is True
    return await client.get(
        "/v1/auth/google/callback",
        params={"state": transaction.state, "code": "controlled-google-code"},
        follow_redirects=False,
    )


def test_sales_xray_google_full_ack_supersession_is_audited_and_transactional(
    postgres_harness: _Harness,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def scenario() -> None:
        previous_version = "google-prior-consent-v1"
        current_version = "google-current-consent-v2"
        previous_time = datetime(2026, 8, 30, 12, tzinfo=UTC)
        person_id, tenant_id = uuid4(), uuid4()
        email = f"google-sx-{person_id.hex}@example.test"
        subject = f"google-sx-subject-{person_id.hex}"
        with Session(postgres_harness.engine) as database, database.begin():
            database.add_all(
                [
                    Tenant(
                        id=tenant_id, slug=f"google-sx-{tenant_id.hex}", name="Synthetic Academy"
                    ),
                    Person(
                        id=person_id,
                        email=email,
                        first_name=None,
                        display_name=None,
                        email_verified_at=previous_time,
                        consent_version=previous_version,
                        consented_at=previous_time,
                    ),
                    ProviderIdentity(
                        person_id=person_id,
                        issuer="https://accounts.google.com",
                        subject=subject,
                    ),
                ]
            )
        async_engine = create_async_engine(postgres_harness.schema_url, pool_pre_ping=True)
        sessions = async_sessionmaker(async_engine, expire_on_commit=False)
        settings = _settings(
            postgres_harness,
            tenant_id=tenant_id,
            consent_version=current_version,
        )
        provider = _GoogleProvider(
            email=email,
            subject=subject,
            display_name="Verified Google Name",
        )
        _, transport = _install_app(
            settings=settings,
            sessions=sessions,
            provider=provider,
        )
        try:
            async with httpx.AsyncClient(
                transport=transport,
                base_url=SALES_ORIGIN,
            ) as client:
                first = await _start_and_callback(
                    client,
                    provider,
                    consent_version=current_version,
                )
                assert first.status_code == 303
                first_transaction = provider.transactions[-1]
                assert first.headers["location"] == (
                    f"{SALES_ORIGIN}/auth/complete?flow="
                    f"{first_transaction.return_path.rsplit('=', maxsplit=1)[1]}"
                    "&auth_result=success"
                )
                profile = await client.get("/v1/me/sales-xray-profile")
                assert profile.status_code == 200
                assert profile.json()["name"] == "Verified Google Name"
                assert profile.json()["phone_number_e164"] is None
                assert profile.json()["profile_complete"] is False

                with Session(postgres_harness.engine) as database:
                    person = database.get(Person, person_id)
                    assert person is not None
                    first_consent_at = person.consented_at
                    assert person.consent_version == current_version
                    assert first_consent_at is not None and first_consent_at != previous_time
                    assert person.display_name == "Verified Google Name"
                    consent_events = list(
                        database.scalars(
                            select(AuditEvent)
                            .where(
                                AuditEvent.tenant_id == tenant_id,
                                AuditEvent.actor_person_id == person_id,
                                AuditEvent.action == CONSENT_ACTION,
                                AuditEvent.resource_type == "person_consent",
                                AuditEvent.resource_id == str(person_id),
                            )
                            .order_by(AuditEvent.sequence_no)
                        )
                    )
                    assert len(consent_events) == 1
                    current_event = consent_events[0]
                    assert current_event.occurred_at == first_consent_at
                    current_payload = dict(current_event.payload)
                    assert (
                        datetime.fromisoformat(current_payload["previous_consented_at"])
                        == previous_time
                    )
                    current_payload["previous_consented_at"] = previous_time.isoformat()
                    assert current_payload == {
                        "consent_version": current_version,
                        "previous_consent_version": previous_version,
                        "previous_consented_at": previous_time.isoformat(),
                        "explicit_acceptance": True,
                        "age_attestation": "18_plus_learner_declaration",
                        "accepted_via": "google",
                        "terms_path": "/terms",
                        "privacy_path": "/privacy",
                    }
                    assert database.get(Membership, (tenant_id, person_id)) is not None
                    sales_xray_profile = database.scalar(
                        select(SalesXrayProfile).where(
                            SalesXrayProfile.person_id == person_id
                        )
                    )
                    assert sales_xray_profile is not None
                    assert sales_xray_profile.phone_number_e164 is None
                    assert sales_xray_profile.phone_verified_at is None

                second = await _start_and_callback(
                    client,
                    provider,
                    consent_version=current_version,
                )
                assert second.status_code == 303
                with Session(postgres_harness.engine) as database:
                    person = database.get(Person, person_id)
                    assert person is not None
                    assert person.consented_at == first_consent_at
                    assert person.display_name == "Verified Google Name"
                    assert (
                        database.scalar(
                            select(func.count())
                            .select_from(AuditEvent)
                            .where(
                                AuditEvent.tenant_id == tenant_id,
                                AuditEvent.actor_person_id == person_id,
                                AuditEvent.action == CONSENT_ACTION,
                                AuditEvent.resource_type == "person_consent",
                                AuditEvent.resource_id == str(person_id),
                            )
                        )
                        == 1
                    )

                stale = AuthTransaction.issue(
                    ProviderAuthorizationType.REGISTER,
                    surface="sales_xray",
                    return_path=f"/auth/complete?flow={uuid4()}",
                    consent_version=previous_version,
                    age_attested=True,
                )
                encoded = AuthTransactionCodec(
                    settings.oauth_transaction_secret.get_secret_value()
                ).encode(stale)
                exchange_calls = provider.exchange_calls
                rejected = await client.get(
                    "/v1/auth/google/callback",
                    params={"state": stale.state, "code": "controlled-google-code"},
                    headers={
                        "cookie": f"{settings.oauth_transaction_cookie_name}={encoded}",
                    },
                    follow_redirects=False,
                )
                assert rejected.status_code == 303
                assert rejected.headers["location"].endswith("auth_result=review_terms")
                assert provider.exchange_calls == exchange_calls
                with Session(postgres_harness.engine) as database:
                    person = database.get(Person, person_id)
                    assert person is not None
                    assert person.consent_version == current_version
                    assert person.consented_at == first_consent_at
                    assert (
                        database.scalar(
                            select(func.count())
                            .select_from(AuditEvent)
                            .where(
                                AuditEvent.tenant_id == tenant_id,
                                AuditEvent.actor_person_id == person_id,
                                AuditEvent.action == CONSENT_ACTION,
                                AuditEvent.resource_type == "person_consent",
                                AuditEvent.resource_id == str(person_id),
                            )
                        )
                        == 1
                    )

            rollback_person_id, rollback_tenant_id = uuid4(), uuid4()
            rollback_email = f"google-rollback-{rollback_person_id.hex}@example.test"
            rollback_subject = f"google-rollback-subject-{rollback_person_id.hex}"
            with Session(postgres_harness.engine) as database, database.begin():
                database.add_all(
                    [
                        Tenant(
                            id=rollback_tenant_id,
                            slug=f"google-rollback-{rollback_tenant_id.hex}",
                            name="Synthetic rollback Academy",
                        ),
                        Person(
                            id=rollback_person_id,
                            email=rollback_email,
                            email_verified_at=previous_time,
                            consent_version=previous_version,
                            consented_at=previous_time,
                        ),
                        ProviderIdentity(
                            person_id=rollback_person_id,
                            issuer="https://accounts.google.com",
                            subject=rollback_subject,
                        ),
                    ]
                )
            rollback_settings = _settings(
                postgres_harness,
                tenant_id=rollback_tenant_id,
                consent_version=current_version,
            )
            rollback_provider = _GoogleProvider(
                email=rollback_email,
                subject=rollback_subject,
                display_name="Rollback Name",
            )
            _, rollback_transport = _install_app(
                settings=rollback_settings,
                sessions=sessions,
                provider=rollback_provider,
                raise_app_exceptions=False,
            )
            original_append = AuditRepository.append

            async def fail_consent_audit(repository: AuditRepository, **kwargs: Any) -> AuditEvent:
                if kwargs.get("action") == CONSENT_ACTION:
                    raise RuntimeError("controlled consent audit failure")
                return await original_append(repository, **kwargs)

            monkeypatch.setattr(AuditRepository, "append", fail_consent_audit)
            try:
                async with httpx.AsyncClient(
                    transport=rollback_transport,
                    base_url=SALES_ORIGIN,
                ) as client:
                    started = await client.get(
                        "/v1/auth/google/start",
                        params={
                            "action": "authenticate",
                            "surface": "sales_xray",
                            "consent": "true",
                            "age_attested": "true",
                            "consent_version": current_version,
                            "return_path": f"/auth/complete?flow={uuid4()}",
                        },
                        follow_redirects=False,
                    )
                    assert started.status_code == 303
                    transaction = rollback_provider.transactions[-1]
                    failed = await client.get(
                        "/v1/auth/google/callback",
                        params={
                            "state": transaction.state,
                            "code": "controlled-google-code",
                        },
                        follow_redirects=False,
                    )
                    assert failed.status_code == 500
            finally:
                monkeypatch.setattr(AuditRepository, "append", original_append)

            with Session(postgres_harness.engine) as database:
                person = database.get(Person, rollback_person_id)
                assert person is not None
                assert person.consent_version == previous_version
                assert person.consented_at == previous_time
                assert database.get(Membership, (rollback_tenant_id, rollback_person_id)) is None
                assert (
                    database.scalar(
                        select(func.count())
                        .select_from(IdentitySession)
                        .where(IdentitySession.person_id == rollback_person_id)
                    )
                    == 0
                )
                assert (
                    database.scalar(
                        select(func.count())
                        .select_from(SalesXrayProfile)
                        .where(SalesXrayProfile.person_id == rollback_person_id)
                    )
                    == 0
                )
                assert (
                    database.scalar(
                        select(func.count())
                        .select_from(AuditEvent)
                        .where(
                            AuditEvent.tenant_id == rollback_tenant_id,
                            AuditEvent.actor_person_id == rollback_person_id,
                            AuditEvent.action == CONSENT_ACTION,
                        )
                    )
                    == 0
                )
                transaction_row = database.get(
                    ProviderAuthorizationTransaction,
                    rollback_provider.transactions[-1].transaction_id,
                )
                assert transaction_row is not None
                assert transaction_row.status == "issued"
                assert transaction_row.consumed_at is None
        finally:
            await async_engine.dispose()

    _run_async(scenario())
