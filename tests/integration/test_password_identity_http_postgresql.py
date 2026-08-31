"""Fresh-PostgreSQL proof for password identity and progressive onboarding."""

from __future__ import annotations

import asyncio
import os
import subprocess
import sys
from collections.abc import Coroutine, Iterator
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from uuid import uuid4

import httpx
import pytest
from fastapi import FastAPI
from sqlalchemy import Engine, create_engine, func, select
from sqlalchemy.engine import URL, make_url
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.orm import Session
from sqlalchemy.schema import CreateSchema, DropSchema

from ac_platform.application.settings import Settings
from ac_platform.http.auth import install_identity_http
from ac_platform.http.auth_transactions import AuthTransaction
from ac_platform.http.problem import register_problem_handlers
from ac_platform.identity.models import (
    EmailChallenge,
    EmailChallengeKind,
    Person,
    ProviderAuthorizationTransaction,
    ProviderIdentity,
)
from ac_platform.identity.models import Session as IdentitySession
from ac_platform.identity.password_auth import decrypt_challenge_token
from ac_platform.identity.services import VerifiedProviderAssertion
from ac_platform.outbox.models import OutboxEvent
from ac_platform.tenancy.models import Membership, Tenant


@dataclass(frozen=True, slots=True)
class _Harness:
    engine: Engine
    schema_url: URL


class _ExistingGoogleProvider:
    audience = "postgres-google-client.apps.googleusercontent.com"

    def __init__(self, *, email: str, subject: str) -> None:
        self.email = email
        self.subject = subject
        self.transactions: list[AuthTransaction] = []

    def authorization_url(
        self,
        transaction: AuthTransaction,
        *,
        redirect_uri: str,
    ) -> str:
        assert redirect_uri == "https://app.authorityclosers.test/v1/auth/google/callback"
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
        assert code == "controlled-google-code"
        assert callback_state == transaction.state
        assert redirect_uri == "https://app.authorityclosers.test/v1/auth/google/callback"
        return VerifiedProviderAssertion(
            issuer="https://accounts.google.com",
            subject=self.subject,
            audience=self.audience,
            state=callback_state,
            nonce=transaction.nonce,
            authorization_type=transaction.authorization_type,
            email=self.email,
            email_verified=True,
        )


def _run_async[T](coroutine: Coroutine[Any, Any, T]) -> T:
    if sys.platform == "win32":
        with asyncio.Runner(loop_factory=asyncio.SelectorEventLoop) as runner:
            return runner.run(coroutine)
    return asyncio.run(coroutine)


def _postgres_url() -> URL:
    raw = os.getenv("AC_PASSWORD_HTTP_POSTGRES_TEST_URL") or os.getenv("AC_TEST_DATABASE_URL")
    if not raw:
        pytest.skip("password HTTP PostgreSQL URL is not configured")
    url = make_url(raw)
    if url.get_backend_name() != "postgresql":
        pytest.skip("password HTTP integration requires PostgreSQL")
    if (
        url.host not in {None, "127.0.0.1", "localhost", "::1"}
        and os.getenv("AC_ALLOW_REMOTE_TEST_DATABASE") != "1"
    ):
        pytest.skip("refusing to mutate a non-local PostgreSQL database")
    return url.set(drivername="postgresql+psycopg")


@pytest.fixture(scope="module")
def postgres_harness() -> Iterator[_Harness]:
    root = Path(__file__).parents[2]
    base_url = _postgres_url()
    schema = f"password_http_{uuid4().hex}"
    admin_engine = create_engine(base_url, pool_pre_ping=True)
    schema_engine: Engine | None = None
    created = False
    try:
        with admin_engine.begin() as connection:
            connection.execute(CreateSchema(schema))
        created = True
        query = dict(base_url.query)
        query["options"] = f"-csearch_path={schema}"
        schema_url = base_url.set(query=query)
        environment = os.environ.copy()
        environment.update(
            {
                "AC_DATABASE_URL": base_url.render_as_string(hide_password=False),
                "AC_DATABASE_MIGRATOR_URL": base_url.render_as_string(hide_password=False),
                "AC_ENVIRONMENT": "test",
                "PGOPTIONS": f"-csearch_path={schema}",
                "PYTHONPATH": os.pathsep.join(
                    part
                    for part in (
                        str(root / "packages" / "python"),
                        environment.get("PYTHONPATH", ""),
                    )
                    if part
                ),
            }
        )
        migration = subprocess.run(
            [sys.executable, "-m", "alembic", "-c", "alembic.ini", "upgrade", "head"],
            cwd=root,
            env=environment,
            capture_output=True,
            text=True,
            timeout=180,
            check=False,
        )
        if migration.returncode != 0:
            pytest.fail(
                "fresh PostgreSQL migration failed\n"
                f"stdout:\n{migration.stdout}\n"
                f"stderr:\n{migration.stderr}"
            )
        schema_engine = create_engine(schema_url, pool_pre_ping=True)
        yield _Harness(engine=schema_engine, schema_url=schema_url)
    finally:
        if schema_engine is not None:
            schema_engine.dispose()
        if created:
            with admin_engine.begin() as connection:
                connection.execute(DropSchema(schema, cascade=True))
        admin_engine.dispose()


def test_password_identity_recovery_and_onboarding_on_fresh_postgresql(
    postgres_harness: _Harness,
) -> None:
    async def scenario() -> None:
        token_pepper = "postgres-password-token-pepper-that-is-long-enough"  # noqa: S105
        challenge_secret = "postgres-email-challenge-secret-that-is-long-enough"  # noqa: S105
        async_engine = create_async_engine(postgres_harness.schema_url, pool_pre_ping=True)
        sessions = async_sessionmaker(async_engine, expire_on_commit=False)
        public_tenant_id = uuid4()
        with Session(postgres_harness.engine) as database, database.begin():
            database.add(
                Tenant(
                    id=public_tenant_id,
                    slug="authority-closers-public-alpha",
                    name="Authority Closers public alpha",
                )
            )
        settings = Settings(
            environment="test",
            database_url=postgres_harness.schema_url.render_as_string(hide_password=False),
            session_token_pepper=token_pepper,
            oauth_transaction_secret="postgres-oauth-transaction-secret-long-enough",  # noqa: S106
            email_challenge_secret=challenge_secret,
            learner_consent_version="staging-test-document-v1",
            public_learner_tenant_id=public_tenant_id,
            public_app_url="https://app.authorityclosers.test",
            admin_app_url="https://admin.authorityclosers.test",
            api_url="https://api.authorityclosers.test",
        )
        application = FastAPI()
        register_problem_handlers(application)
        install_identity_http(application, settings=settings, sessions=sessions)
        transport = httpx.ASGITransport(app=application, client=("127.0.0.1", 12345))
        headers = {"Origin": "https://app.authorityclosers.test"}
        try:
            async with httpx.AsyncClient(
                transport=transport,
                base_url="https://app.authorityclosers.test",
            ) as client:
                registered = await client.post(
                    "/v1/auth/password/register",
                    headers=headers,
                    json={
                        "first_name": "Learner",
                        "email": "learner@example.com",
                        "whatsapp_number": "+12025550123",
                        "password": "initial learner password",
                        "consent": True,
                    },
                )
                assert registered.status_code == 202
                assert registered.headers["cache-control"] == "no-store"
                assert registered.json() == {"status": "verification_required"}
                assert "token" not in registered.text

                with Session(postgres_harness.engine) as database:
                    person = database.scalar(
                        select(Person).where(Person.email == "learner@example.com")
                    )
                    assert person is not None
                    challenge = database.scalar(
                        select(EmailChallenge).where(
                            EmailChallenge.person_id == person.id,
                            EmailChallenge.kind == EmailChallengeKind.VERIFICATION.value,
                        )
                    )
                    assert challenge is not None
                    event = database.scalar(
                        select(OutboxEvent).where(
                            OutboxEvent.aggregate_id == person.id,
                        )
                    )
                    assert event is not None
                    assert set(event.payload) == {"challenge_id", "kind"}
                    token = decrypt_challenge_token(
                        challenge_secret,
                        challenge.encrypted_token,
                        kind=EmailChallengeKind.VERIFICATION,
                        person_id=person.id,
                    )

                other_tenant_id = uuid4()
                with Session(postgres_harness.engine) as database, database.begin():
                    database.add(
                        Tenant(
                            id=other_tenant_id,
                            slug="preexisting-membership",
                            name="Pre-existing membership",
                        )
                    )
                    database.add(
                        Membership(
                            tenant_id=other_tenant_id,
                            person_id=person.id,
                            role="support",
                            status="active",
                        )
                    )

                resend = await client.post(
                    "/v1/auth/password/resend-verification",
                    headers=headers,
                    json={"email": "learner@example.com"},
                )
                assert resend.status_code == 200
                assert resend.headers["cache-control"] == "no-store"
                assert resend.json() == {"accepted": True}

                with Session(postgres_harness.engine) as database:
                    replacement_challenge = database.scalar(
                        select(EmailChallenge)
                        .where(
                            EmailChallenge.person_id == person.id,
                            EmailChallenge.kind == EmailChallengeKind.VERIFICATION.value,
                            EmailChallenge.consumed_at.is_(None),
                        )
                        .order_by(EmailChallenge.issued_at.desc())
                    )
                    assert replacement_challenge is not None
                    replacement_token = decrypt_challenge_token(
                        challenge_secret,
                        replacement_challenge.encrypted_token,
                        kind=EmailChallengeKind.VERIFICATION,
                        person_id=person.id,
                    )

                superseded = await client.post(
                    "/v1/auth/password/verify",
                    headers=headers,
                    json={"token": token},
                )
                assert superseded.status_code == 400

                verified = await client.post(
                    "/v1/auth/password/verify",
                    headers=headers,
                    json={"token": replacement_token},
                )
                assert verified.status_code == 200
                assert verified.json()["authenticated"] is True
                assert "token" not in verified.text
                with Session(postgres_harness.engine) as database:
                    membership = database.get(Membership, (public_tenant_id, person.id))
                    assert membership is not None
                    assert membership.role == "learner"
                    assert membership.status == "active"
                    existing_membership = database.get(
                        Membership,
                        (other_tenant_id, person.id),
                    )
                    assert existing_membership is not None
                    assert existing_membership.role == "support"
                me = await client.get("/v1/me")
                assert me.status_code == 200
                assert me.json()["selected_tenant_id"] == str(public_tenant_id)
                assert me.json()["membership_role"] == "learner"

                initial_profile = await client.get("/v1/onboarding")
                assert initial_profile.status_code == 200
                assert initial_profile.json()["status"] == "not_started"
                assert initial_profile.headers["etag"] == '"onboarding-revision-0"'

                profile = await client.put(
                    "/v1/onboarding",
                    headers=headers | {"If-Match": '"onboarding-revision-0"'},
                    json={
                        "experience_context": "sales",
                        "learning_goal": "Ask a clearer next-step question",
                        "practice_situation": None,
                        "weekly_minutes": 30,
                        "status": "completed",
                        "current_step": 3,
                    },
                )
                assert profile.status_code == 200
                assert profile.headers["etag"] == '"onboarding-revision-1"'
                assert profile.json()["next_action_href"] == "/"
                assert (
                    "No unreviewed personalized course mapping"
                    in profile.json()["next_action_reason"]
                )

                recovery = await client.post(
                    "/v1/auth/password/recovery",
                    headers=headers,
                    json={"email": "learner@example.com"},
                )
                assert recovery.status_code == 200
                assert recovery.headers["cache-control"] == "no-store"
                assert recovery.json() == {"accepted": True}

                with Session(postgres_harness.engine) as database:
                    reset_challenge = database.scalar(
                        select(EmailChallenge)
                        .where(
                            EmailChallenge.person_id == person.id,
                            EmailChallenge.kind == EmailChallengeKind.PASSWORD_RESET.value,
                        )
                        .order_by(EmailChallenge.issued_at.desc())
                    )
                    assert reset_challenge is not None
                    reset_token = decrypt_challenge_token(
                        challenge_secret,
                        reset_challenge.encrypted_token,
                        kind=EmailChallengeKind.PASSWORD_RESET,
                        person_id=person.id,
                    )

                reset = await client.post(
                    "/v1/auth/password/reset",
                    headers=headers,
                    json={
                        "token": reset_token,
                        "new_password": "replacement learner password",
                    },
                )
                assert reset.status_code == 200
                assert reset.headers["cache-control"] == "no-store"
                assert (await client.get("/v1/me")).status_code == 401

                old_login = await client.post(
                    "/v1/auth/password/login",
                    headers=headers,
                    json={
                        "email": "learner@example.com",
                        "password": "initial learner password",
                    },
                )
                assert old_login.status_code == 401
                new_login = await client.post(
                    "/v1/auth/password/login",
                    headers=headers,
                    json={
                        "email": "learner@example.com",
                        "password": "replacement learner password",
                    },
                )
                assert new_login.status_code == 200
                me_after_login = await client.get("/v1/me")
                assert me_after_login.status_code == 200
                assert me_after_login.json()["selected_tenant_id"] == str(public_tenant_id)
        finally:
            await async_engine.dispose()

    _run_async(scenario())


def test_existing_google_learner_requires_exact_consent_and_selects_public_tenant(
    postgres_harness: _Harness,
) -> None:
    async def scenario() -> None:
        consent_version = "staging-test-document-v1"
        now = datetime(2026, 8, 31, 12, tzinfo=UTC)
        person_id = uuid4()
        public_tenant_id = uuid4()
        other_tenant_id = uuid4()
        provider_subject = f"google-existing-{person_id.hex}"
        provider_email = f"google-existing-{person_id.hex}@example.com"
        with Session(postgres_harness.engine) as database, database.begin():
            database.add_all(
                [
                    Person(
                        id=person_id,
                        email=provider_email,
                        first_name="Existing learner",
                        email_verified_at=now,
                        consent_version=None,
                        consented_at=None,
                    ),
                    ProviderIdentity(
                        person_id=person_id,
                        issuer="https://accounts.google.com",
                        subject=provider_subject,
                    ),
                    Tenant(
                        id=public_tenant_id,
                        slug=f"google-public-{person_id.hex}",
                        name="Google public learner tenant",
                    ),
                    Tenant(
                        id=other_tenant_id,
                        slug=f"google-existing-{person_id.hex}",
                        name="Existing support tenant",
                    ),
                    Membership(
                        tenant_id=other_tenant_id,
                        person_id=person_id,
                        role="support",
                        status="active",
                    ),
                ]
            )

        async_engine = create_async_engine(postgres_harness.schema_url, pool_pre_ping=True)
        sessions = async_sessionmaker(async_engine, expire_on_commit=False)
        provider = _ExistingGoogleProvider(email=provider_email, subject=provider_subject)
        settings = Settings(
            environment="test",
            database_url=postgres_harness.schema_url.render_as_string(hide_password=False),
            session_token_pepper="postgres-google-token-pepper-that-is-long-enough",  # noqa: S106
            oauth_transaction_secret="postgres-google-transaction-secret-long-enough",  # noqa: S106
            email_challenge_secret="postgres-google-email-secret-that-is-long-enough",  # noqa: S106
            learner_consent_version=consent_version,
            public_learner_tenant_id=public_tenant_id,
            public_app_url="https://app.authorityclosers.test",
            admin_app_url="https://admin.authorityclosers.test",
            api_url="https://api.authorityclosers.test",
        )
        application = FastAPI()
        register_problem_handlers(application)
        install_identity_http(
            application,
            settings=settings,
            sessions=sessions,
            provider=provider,
        )
        transport = httpx.ASGITransport(app=application, client=("127.0.0.1", 12345))

        async def authenticate(client: httpx.AsyncClient) -> tuple[httpx.Response, AuthTransaction]:
            started = await client.get(
                "/v1/auth/google/start",
                params={
                    "action": "authenticate",
                    "surface": "learner",
                    "return_path": "/home",
                },
                follow_redirects=False,
            )
            assert started.status_code == 303
            transaction = provider.transactions[-1]
            callback = await client.get(
                "/v1/auth/google/callback",
                params={"state": transaction.state, "code": "controlled-google-code"},
                follow_redirects=False,
            )
            return callback, transaction

        rejected_transaction_ids = []
        try:
            async with httpx.AsyncClient(
                transport=transport,
                base_url="https://app.authorityclosers.test",
            ) as client:
                missing_consent, missing_transaction = await authenticate(client)
                assert missing_consent.status_code == 503
                assert missing_consent.json()["code"] == "password_registration_unavailable"
                rejected_transaction_ids.append(missing_transaction.transaction_id)

                with Session(postgres_harness.engine) as database:
                    assert (
                        database.scalar(
                            select(func.count())
                            .select_from(IdentitySession)
                            .where(IdentitySession.person_id == person_id)
                        )
                        == 0
                    )
                    transaction = database.get(
                        ProviderAuthorizationTransaction,
                        missing_transaction.transaction_id,
                    )
                    assert transaction is not None
                    assert transaction.status == "issued"
                    assert transaction.consumed_at is None
                    identity = database.scalar(
                        select(ProviderIdentity).where(
                            ProviderIdentity.person_id == person_id,
                            ProviderIdentity.subject == provider_subject,
                        )
                    )
                    assert identity is not None
                    assert identity.revision == 0
                    assert identity.last_authenticated_at is None
                    assert database.get(Membership, (public_tenant_id, person_id)) is None

                with Session(postgres_harness.engine) as database, database.begin():
                    person = database.get(Person, person_id)
                    assert person is not None
                    person.consent_version = "older-consent-v1"
                    person.consented_at = now

                stale_consent, stale_transaction = await authenticate(client)
                assert stale_consent.status_code == 503
                assert stale_consent.json()["code"] == "password_registration_unavailable"
                rejected_transaction_ids.append(stale_transaction.transaction_id)

                with Session(postgres_harness.engine) as database:
                    assert (
                        database.scalar(
                            select(func.count())
                            .select_from(IdentitySession)
                            .where(IdentitySession.person_id == person_id)
                        )
                        == 0
                    )
                    for transaction_id in rejected_transaction_ids:
                        transaction = database.get(ProviderAuthorizationTransaction, transaction_id)
                        assert transaction is not None
                        assert transaction.status == "issued"
                        assert transaction.consumed_at is None
                    assert database.get(Membership, (public_tenant_id, person_id)) is None

                with Session(postgres_harness.engine) as database, database.begin():
                    person = database.get(Person, person_id)
                    assert person is not None
                    person.consent_version = consent_version
                    person.consented_at = now

                authenticated, accepted_transaction = await authenticate(client)
                assert authenticated.status_code == 303
                assert authenticated.headers["location"] == "https://app.authorityclosers.test/home"
                me = await client.get("/v1/me")
                assert me.status_code == 200
                assert me.json()["selected_tenant_id"] == str(public_tenant_id)
                assert me.json()["membership_role"] == "learner"

                with Session(postgres_harness.engine) as database:
                    session_rows = list(
                        database.scalars(
                            select(IdentitySession).where(IdentitySession.person_id == person_id)
                        )
                    )
                    assert len(session_rows) == 1
                    assert session_rows[0].selected_tenant_id == public_tenant_id
                    transaction = database.get(
                        ProviderAuthorizationTransaction,
                        accepted_transaction.transaction_id,
                    )
                    assert transaction is not None
                    assert transaction.status == "consumed"
                    assert transaction.consumed_at is not None
                    learner_membership = database.get(
                        Membership,
                        (public_tenant_id, person_id),
                    )
                    assert learner_membership is not None
                    assert learner_membership.role == "learner"
                    assert learner_membership.status == "active"
                    support_membership = database.get(
                        Membership,
                        (other_tenant_id, person_id),
                    )
                    assert support_membership is not None
                    assert support_membership.role == "support"
        finally:
            await async_engine.dispose()

    _run_async(scenario())
