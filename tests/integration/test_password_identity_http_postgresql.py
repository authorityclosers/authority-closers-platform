"""Fresh-PostgreSQL proof for password identity and progressive onboarding."""

from __future__ import annotations

import asyncio
import hashlib
import os
import subprocess
import sys
from collections.abc import Coroutine, Iterator
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any
from uuid import UUID, uuid4

import httpx
import pytest
from fastapi import FastAPI
from sqlalchemy import Engine, create_engine, delete, func, select
from sqlalchemy.engine import URL, make_url
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.orm import Session
from sqlalchemy.schema import CreateSchema, DropSchema

from ac_platform.application.settings import Settings
from ac_platform.audit.models import AuditEvent
from ac_platform.audit.service import AuditRepository
from ac_platform.http.auth import install_identity_http
from ac_platform.http.auth_transactions import AuthTransaction
from ac_platform.http.problem import register_problem_handlers
from ac_platform.identity.email_login import (
    EMAIL_LOGIN_ATTEMPT_LIMIT,
    EMAIL_LOGIN_CODE_TTL,
    EMAIL_LOGIN_REQUEST_EVENT,
    EMAIL_LOGIN_RESEND_AFTER,
    EMAIL_LOGIN_SEND_WINDOW,
    EmailLoginCodeService,
    _code_hash,
    _encrypt_code,
    decrypt_email_login_code,
)
from ac_platform.identity.models import (
    EmailChallenge,
    EmailChallengeKind,
    EmailLoginCode,
    IdentityCommandIdempotency,
    PasswordCredential,
    Person,
    ProviderAuthorizationTransaction,
    ProviderIdentity,
)
from ac_platform.identity.models import Session as IdentitySession
from ac_platform.identity.password_auth import (
    InvalidPasswordCredentials,
    PasswordIdentityService,
    decrypt_challenge_token,
    hash_password,
)
from ac_platform.identity.repositories import AsyncSqlAlchemyIdentityRepository
from ac_platform.identity.services import ProviderAuthorizationType, VerifiedProviderAssertion
from ac_platform.outbox.models import OutboxEvent
from ac_platform.tenancy.models import Membership, MembershipRole, MembershipStatus, Tenant


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


def _email_code_settings(
    schema_url: URL,
    *,
    public_tenant_id: UUID,
    operations_tenant_id: UUID,
    consent_version: str,
) -> Settings:
    return Settings(
        environment="test",
        database_url=schema_url.render_as_string(hide_password=False),
        session_token_pepper="postgres-email-login-token-pepper-long-enough",  # noqa: S106
        oauth_transaction_secret="postgres-email-login-oauth-secret-long-enough",  # noqa: S106
        email_challenge_secret="postgres-email-login-challenge-secret-long-enough",  # noqa: S106
        learner_consent_version=consent_version,
        public_learner_tenant_id=public_tenant_id,
        operations_tenant_id=operations_tenant_id,
        public_app_url="https://app.authorityclosers.test",
        admin_app_url="https://admin.authorityclosers.test",
        api_url="https://api.authorityclosers.test",
        sales_xray_app_url="https://salesxray.authorityclosers.test",
    )


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


@pytest.mark.parametrize(
    ("account_state", "has_password", "verified", "expected_kind"),
    [
        (None, False, False, None),
        ("active", False, True, "password_reset"),
        ("active", False, False, None),
        ("suspended", True, False, None),
        ("suspended", True, True, None),
        ("deleted", True, False, None),
    ],
)
def test_recovery_preserves_account_eligibility_without_authentication(
    postgres_harness: _Harness,
    account_state: str | None,
    has_password: bool,
    verified: bool,
    expected_kind: str | None,
) -> None:
    async def scenario() -> None:
        person_id = uuid4()
        email = f"recovery-{person_id}@example.test"
        if account_state is not None:
            with Session(postgres_harness.engine) as database, database.begin():
                database.add(
                    Person(
                        id=person_id,
                        email=email,
                        status=account_state,
                        email_verified_at=datetime.now(UTC) if verified else None,
                    )
                )
                database.flush()
                if has_password:
                    database.add(
                        PasswordCredential(
                            person_id=person_id,
                            password_hash=hash_password("synthetic recovery test password"),
                        )
                    )
        engine = create_async_engine(postgres_harness.schema_url, pool_pre_ping=True)
        settings = Settings(
            environment="test",
            database_url=postgres_harness.schema_url.render_as_string(hide_password=False),
            session_token_pepper="test-recovery-token-pepper-long-enough",  # noqa: S106
            oauth_transaction_secret="test-recovery-oauth-secret-long-enough",  # noqa: S106
            email_challenge_secret="test-recovery-challenge-secret-long-enough",  # noqa: S106
            public_app_url="https://app.authorityclosers.test",
            admin_app_url="https://admin.authorityclosers.test",
            api_url="https://api.authorityclosers.test",
        )
        app = FastAPI()
        register_problem_handlers(app)
        install_identity_http(
            app, settings=settings, sessions=async_sessionmaker(engine, expire_on_commit=False)
        )
        try:
            async with httpx.AsyncClient(
                transport=httpx.ASGITransport(app=app),
                base_url="https://app.authorityclosers.test",
            ) as client:
                response = await client.post(
                    "/v1/auth/password/recovery",
                    headers={"Origin": "https://app.authorityclosers.test"},
                    json={"email": email},
                )
                assert response.status_code == 200
                assert response.json() == {"accepted": True}
                assert response.headers["cache-control"] == "no-store"
                assert "set-cookie" not in response.headers
            with Session(postgres_harness.engine) as database:
                challenges = list(
                    database.scalars(
                        select(EmailChallenge).where(EmailChallenge.person_id == person_id)
                    )
                )
                assert [challenge.kind for challenge in challenges] == (
                    [expected_kind] if expected_kind else []
                )
                assert database.scalar(
                    select(func.count())
                    .select_from(OutboxEvent)
                    .where(OutboxEvent.aggregate_id == person_id)
                ) == int(expected_kind is not None)
                assert database.scalar(
                    select(func.count())
                    .select_from(PasswordCredential)
                    .where(PasswordCredential.person_id == person_id)
                ) == int(has_password)
                person = database.get(Person, person_id)
                if account_state is None:
                    assert person is None
                else:
                    assert person is not None
                    assert person.status == account_state
                    assert (person.email_verified_at is not None) is verified
        finally:
            await engine.dispose()

    _run_async(scenario())


def test_email_login_code_concurrently_provisions_one_account_and_commits_failures(
    postgres_harness: _Harness,
) -> None:
    async def scenario() -> None:
        public_tenant_id = uuid4()
        operations_tenant_id = uuid4()
        consent_version = "sales-xray-terms-v1"
        email = f"email-login-{uuid4().hex}@example.test"
        with Session(postgres_harness.engine) as database, database.begin():
            database.add_all(
                [
                    Tenant(
                        id=public_tenant_id,
                        slug=f"email-login-public-{public_tenant_id.hex}",
                        name="Email login public learner tenant",
                    ),
                    Tenant(
                        id=operations_tenant_id,
                        slug=f"email-login-ops-{operations_tenant_id.hex}",
                        name="Email login operations tenant",
                    ),
                ]
            )
        settings = _email_code_settings(
            postgres_harness.schema_url,
            public_tenant_id=public_tenant_id,
            operations_tenant_id=operations_tenant_id,
            consent_version=consent_version,
        )
        async_engine = create_async_engine(postgres_harness.schema_url, pool_pre_ping=True)
        application = FastAPI()
        register_problem_handlers(application)
        install_identity_http(
            application,
            settings=settings,
            sessions=async_sessionmaker(async_engine, expire_on_commit=False),
        )
        origin = "https://salesxray.authorityclosers.test"

        def client() -> httpx.AsyncClient:
            return httpx.AsyncClient(
                transport=httpx.ASGITransport(app=application, client=("127.0.0.1", 12345)),
                base_url=origin,
            )

        clients = [client() for _ in range(5)]
        try:
            config = await clients[0].get("/v1/auth/email-code/config?surface=sales_xray")
            assert config.status_code == 200
            assert config.json() == {
                "enabled": True,
                "consent_version": consent_version,
                "google_enabled": False,
                "expires_in_seconds": int(EMAIL_LOGIN_CODE_TTL.total_seconds()),
                "resend_after_seconds": int(EMAIL_LOGIN_RESEND_AFTER.total_seconds()),
            }
            request_body = {
                "email": email,
                "consent": True,
                "consent_version": consent_version,
                "age_attested": True,
                "surface": "sales_xray",
                "return_path": "/",
            }
            legacy_request_body = dict(request_body)
            legacy_request_body.pop("age_attested")
            no_full_ack = await clients[0].post(
                "/v1/auth/email-code/request",
                headers={"Origin": origin},
                json=legacy_request_body,
            )
            assert no_full_ack.status_code == 202
            with Session(postgres_harness.engine) as database:
                assert database.scalar(
                    select(EmailLoginCode).where(EmailLoginCode.normalized_email == email)
                ) is None
                assert database.scalar(
                    select(func.count()).select_from(Person).where(Person.email == email)
                ) == 0
                assert database.scalar(
                    select(func.count())
                    .select_from(OutboxEvent)
                    .where(OutboxEvent.event_type == EMAIL_LOGIN_REQUEST_EVENT)
                ) == 0
            requests = await asyncio.gather(
                clients[0].post(
                    "/v1/auth/email-code/request",
                    headers={"Origin": origin},
                    json=request_body,
                ),
                clients[1].post(
                    "/v1/auth/email-code/request",
                    headers={"Origin": origin},
                    json=request_body,
                ),
            )
            assert [response.status_code for response in requests] == [202, 202]
            assert (
                requests[0].json()
                == requests[1].json()
                == {
                    "accepted": True,
                    "expires_in_seconds": int(EMAIL_LOGIN_CODE_TTL.total_seconds()),
                    "resend_after_seconds": int(EMAIL_LOGIN_RESEND_AFTER.total_seconds()),
                }
            )
            with Session(postgres_harness.engine) as database:
                challenges = list(
                    database.scalars(
                        select(EmailLoginCode).where(EmailLoginCode.normalized_email == email)
                    )
                )
                assert len(challenges) == 1
                challenge = challenges[0]
                assert challenge.age_attested is True
                code = decrypt_email_login_code(
                    settings.email_challenge_secret.get_secret_value(),
                    challenge,
                    generation_id=challenge.generation_id,
                )
                assert (
                    database.scalar(
                        select(func.count())
                        .select_from(OutboxEvent)
                        .where(OutboxEvent.event_type == EMAIL_LOGIN_REQUEST_EVENT)
                    )
                    == 1
                )
                assert (
                    database.scalar(
                        select(func.count()).select_from(Person).where(Person.email == email)
                    )
                    == 0
                )

            wrong_code = "000000" if code != "000000" else "000001"
            bad = await clients[2].post(
                "/v1/auth/email-code/verify",
                headers={"Origin": origin},
                json={
                    "email": email,
                    "code": wrong_code,
                    "surface": "sales_xray",
                    "return_path": "/",
                },
            )
            assert bad.status_code == 400
            with Session(postgres_harness.engine) as database:
                failed_challenge = database.scalar(
                    select(EmailLoginCode).where(EmailLoginCode.normalized_email == email)
                )
                assert failed_challenge is not None
                assert failed_challenge.failed_attempts == 1
                assert failed_challenge.consumed_at is None

            verification = {
                "email": email,
                "code": code,
                "surface": "sales_xray",
                "return_path": "/",
            }
            results = await asyncio.gather(
                clients[3].post(
                    "/v1/auth/email-code/verify",
                    headers={"Origin": origin},
                    json=verification,
                ),
                clients[4].post(
                    "/v1/auth/email-code/verify",
                    headers={"Origin": origin},
                    json=verification,
                ),
            )
            assert sorted(response.status_code for response in results) == [200, 400]
            successful = next(response for response in results if response.status_code == 200)
            assert successful.json() == {
                "authenticated": True,
                "person_id": successful.json()["person_id"],
                "email": email,
                "display_name": None,
                "account_created": True,
                "profile_complete": False,
                "return_path": "/",
            }
            cookie = successful.headers["set-cookie"].lower()
            assert "httponly" in cookie
            assert "samesite=lax" in cookie
            assert "domain=" not in cookie
            me_client = clients[3] if results[0] is successful else clients[4]
            me = await me_client.get("/v1/me")
            assert me.status_code == 200
            person_id = UUID(me.json()["person_id"])
            assert me.json()["selected_tenant_id"] == str(public_tenant_id)
            assert me.json()["membership_role"] == "learner"
            replay = await clients[2].post(
                "/v1/auth/email-code/verify",
                headers={"Origin": origin},
                json=verification,
            )
            assert replay.status_code == 400
            with Session(postgres_harness.engine) as database:
                person = database.get(Person, person_id)
                assert person is not None
                assert person.first_name is None
                assert person.whatsapp_number is None
                assert person.email_verified_at is not None
                assert person.consent_version == consent_version
                assert database.get(Membership, (public_tenant_id, person_id)) is not None
                consent_audit = database.scalar(
                    select(AuditEvent).where(
                        AuditEvent.tenant_id == public_tenant_id,
                        AuditEvent.actor_person_id == person_id,
                        AuditEvent.action == "identity.learner_consent_accepted.v1",
                        AuditEvent.resource_type == "person_consent",
                        AuditEvent.resource_id == str(person_id),
                    )
                )
                assert consent_audit is not None
                assert consent_audit.occurred_at == person.consented_at
                assert consent_audit.payload["consent_version"] == consent_version
                assert consent_audit.payload["previous_consent_version"] is None
                assert consent_audit.payload["explicit_acceptance"] is True
                assert consent_audit.payload["age_attestation"] == (
                    "18_plus_learner_declaration"
                )
                assert consent_audit.payload["accepted_via"] == "email_otp"
                assert (
                    database.scalar(
                        select(func.count())
                        .select_from(IdentitySession)
                        .where(IdentitySession.person_id == person_id)
                    )
                    == 1
                )
                final_challenge = database.get(EmailLoginCode, challenge.id)
                assert final_challenge is not None
                assert final_challenge.failed_attempts == 1
                assert final_challenge.consumed_at is not None
        finally:
            for current_client in clients:
                await current_client.aclose()
            await async_engine.dispose()

    _run_async(scenario())


def test_email_login_resend_does_not_reset_failure_budget(postgres_harness: _Harness) -> None:
    async def scenario() -> None:
        async_engine = create_async_engine(postgres_harness.schema_url, pool_pre_ping=True)
        sessions = async_sessionmaker(async_engine, expire_on_commit=False)
        email = f"email-budget-{uuid4().hex}@example.test"
        secret = "postgres-email-budget-secret-long-enough-for-hmac-and-aes"  # noqa: S105
        consent = "email-budget-consent-v1"
        started = datetime(2026, 9, 23, 12, tzinfo=UTC)

        async def begin(at: datetime):
            async with sessions() as database, database.begin():
                return await EmailLoginCodeService(
                    database,
                    challenge_secret=secret,
                ).begin(
                    email=email,
                    consent_accepted=True,
                    submitted_consent_version=consent,
                    required_consent_version=consent,
                    age_attested=True,
                    now=at,
                )

        async def fail_current(at: datetime) -> None:
            async with sessions() as database, database.begin():
                challenge = await database.scalar(
                    select(EmailLoginCode).where(EmailLoginCode.normalized_email == email)
                )
                assert challenge is not None
                valid_code = decrypt_email_login_code(
                    secret,
                    challenge,
                    generation_id=challenge.generation_id,
                )
                wrong_code = "999999" if valid_code != "999999" else "999998"
                result = await EmailLoginCodeService(
                    database,
                    challenge_secret=secret,
                ).verify(
                    email=email,
                    code=wrong_code,
                    required_consent_version=consent,
                    now=at,
                )
                assert result.person is None

        try:
            first = await begin(started)
            assert first is not None
            await fail_current(started + timedelta(seconds=1))
            await fail_current(started + timedelta(seconds=2))
            resent = await begin(started + EMAIL_LOGIN_RESEND_AFTER)
            assert resent is not None
            assert resent.challenge_id == first.challenge_id
            with Session(postgres_harness.engine) as database:
                after_resend = database.get(EmailLoginCode, first.challenge_id)
                assert after_resend is not None
                assert after_resend.failed_attempts == 2
                assert after_resend.sends_in_window == 2
            await fail_current(started + timedelta(seconds=61))
            await fail_current(started + timedelta(seconds=62))
            await fail_current(started + timedelta(seconds=63))
            blocked = await begin(started + timedelta(seconds=64))
            assert blocked is None
            with Session(postgres_harness.engine) as database:
                exhausted = database.get(EmailLoginCode, first.challenge_id)
                assert exhausted is not None
                assert exhausted.failed_attempts == EMAIL_LOGIN_ATTEMPT_LIMIT
                assert exhausted.consumed_at is not None
            reset = await begin(started + EMAIL_LOGIN_SEND_WINDOW + timedelta(seconds=1))
            assert reset is not None
            assert reset.challenge_id == first.challenge_id
            with Session(postgres_harness.engine) as database:
                restarted = database.get(EmailLoginCode, first.challenge_id)
                assert restarted is not None
                assert restarted.failed_attempts == 0
                assert restarted.sends_in_window == 1
        finally:
            await async_engine.dispose()

    _run_async(scenario())


def test_email_login_requires_age_attestation_for_eligibility_but_not_verified_sign_in(
    postgres_harness: _Harness,
) -> None:
    async def scenario() -> None:
        async_engine = create_async_engine(postgres_harness.schema_url, pool_pre_ping=True)
        sessions = async_sessionmaker(async_engine, expire_on_commit=False)
        secret = "postgres-email-age-secret-long-enough-for-hmac-and-aes"  # noqa: S105
        consent_version = "email-age-consent-v2"
        now = datetime.now(UTC)
        new_email = f"email-age-new-{uuid4().hex}@example.test"
        pending_person_id = uuid4()
        pending_email = f"email-age-pending-{pending_person_id.hex}@example.test"
        verified_person_id = uuid4()
        verified_email = f"email-age-verified-{verified_person_id.hex}@example.test"
        previous_consent_time = now - timedelta(days=30)
        challenge_id = uuid4()
        generation_id = uuid4()
        code = "042731"
        pending_password_hash = hash_password("synthetic pending password phrase")
        with Session(postgres_harness.engine) as database, database.begin():
            database.add_all(
                [
                    Person(
                        id=pending_person_id,
                        email=pending_email,
                        consent_version="email-age-consent-v1",
                        consented_at=previous_consent_time,
                    ),
                    PasswordCredential(
                        person_id=pending_person_id,
                        password_hash=pending_password_hash,
                    ),
                    Person(
                        id=verified_person_id,
                        email=verified_email,
                        email_verified_at=now - timedelta(days=30),
                        consent_version="email-age-consent-v1",
                        consented_at=previous_consent_time,
                    ),
                    EmailLoginCode(
                        id=challenge_id,
                        generation_id=generation_id,
                        normalized_email=pending_email,
                        token_hash=_code_hash(secret, pending_email, code),
                        encrypted_code=_encrypt_code(
                            secret,
                            code,
                            challenge_id=challenge_id,
                            generation_id=generation_id,
                            email=pending_email,
                        ),
                        consent_version=consent_version,
                        issued_at=now,
                        expires_at=now + EMAIL_LOGIN_CODE_TTL,
                        send_window_started_at=now,
                        sends_in_window=1,
                    ),
                ]
            )

        async with sessions() as database, database.begin():
            denied = await EmailLoginCodeService(
                database,
                challenge_secret=secret,
            ).begin(
                email=new_email,
                consent_accepted=True,
                submitted_consent_version=consent_version,
                required_consent_version=consent_version,
            )
            assert denied is None

        with Session(postgres_harness.engine) as database:
            assert database.scalar(
                select(EmailLoginCode).where(EmailLoginCode.normalized_email == new_email)
            ) is None
            credential_before = database.scalar(
                select(PasswordCredential).where(PasswordCredential.person_id == pending_person_id)
            )
            assert credential_before is not None
            assert credential_before.password_hash == pending_password_hash
            pending_credential_id = credential_before.id

        async with sessions() as database, database.begin():
            denied = await EmailLoginCodeService(
                database,
                challenge_secret=secret,
            ).verify(
                email=pending_email,
                code=code,
                required_consent_version=consent_version,
                now=now + timedelta(seconds=1),
            )
            assert denied.person is None

        with Session(postgres_harness.engine) as database:
            pending_person = database.get(Person, pending_person_id)
            assert pending_person is not None
            assert pending_person.email_verified_at is None
            assert pending_person.consent_version == "email-age-consent-v1"
            assert pending_person.consented_at == previous_consent_time
            credential_after = database.get(PasswordCredential, pending_credential_id)
            assert credential_after is not None
            assert credential_after.person_id == pending_person_id
            assert credential_after.password_hash == pending_password_hash
            legacy_challenge = database.get(EmailLoginCode, challenge_id)
            assert legacy_challenge is not None
            assert legacy_challenge.age_attested is False
            assert legacy_challenge.consumed_at is not None

        async with sessions() as database, database.begin():
            issued = await EmailLoginCodeService(
                database,
                challenge_secret=secret,
            ).begin(
                email=verified_email,
                consent_accepted=False,
                submitted_consent_version=None,
                required_consent_version=consent_version,
                now=now,
            )
            assert issued is not None
            challenge = await database.scalar(
                select(EmailLoginCode).where(EmailLoginCode.normalized_email == verified_email)
            )
            assert challenge is not None
            verified_code = decrypt_email_login_code(
                secret,
                challenge,
                generation_id=challenge.generation_id,
            )
            signed_in = await EmailLoginCodeService(
                database,
                challenge_secret=secret,
            ).verify(
                email=verified_email,
                code=verified_code,
                required_consent_version=consent_version,
                now=now + timedelta(seconds=1),
            )
            assert signed_in.person is not None
            assert signed_in.person.id == verified_person_id
            assert signed_in.learner_provisioning_required is False
            assert signed_in.consent_audit_required is False
            assert signed_in.previous_consent_version is None
            assert signed_in.previous_consented_at is None

        with Session(postgres_harness.engine) as database:
            verified_person = database.get(Person, verified_person_id)
            assert verified_person is not None
            assert verified_person.email_verified_at == now - timedelta(days=30)
            assert verified_person.consent_version == "email-age-consent-v1"
            assert verified_person.consented_at == previous_consent_time
        await async_engine.dispose()

    _run_async(scenario())


def test_email_login_reclaim_cancels_unverified_password_credentials_and_sessions(
    postgres_harness: _Harness,
) -> None:
    async def scenario() -> None:
        public_tenant_id = uuid4()
        operations_tenant_id = uuid4()
        person_id = uuid4()
        email = f"email-reclaim-{person_id.hex}@example.test"
        consent_version = "email-reclaim-consent-v1"
        previous_consent_version = "email-reclaim-consent-v0"
        now = datetime.now(UTC)
        previous_consent_time = now - timedelta(days=30)
        with Session(postgres_harness.engine) as database, database.begin():
            database.add_all(
                [
                    Tenant(
                        id=public_tenant_id,
                        slug=f"email-reclaim-public-{public_tenant_id.hex}",
                        name="Email reclaim public tenant",
                    ),
                    Tenant(
                        id=operations_tenant_id,
                        slug=f"email-reclaim-ops-{operations_tenant_id.hex}",
                        name="Email reclaim operations tenant",
                    ),
                    Person(
                        id=person_id,
                        email=email,
                        email_verified_at=None,
                        consent_version=previous_consent_version,
                        consented_at=previous_consent_time,
                    ),
                ]
            )
            database.flush()
            database.add(
                PasswordCredential(
                    person_id=person_id,
                    password_hash=hash_password("attacker-known-password-phrase"),
                )
            )
            database.add_all(
                [
                    EmailChallenge(
                        id=uuid4(),
                        person_id=person_id,
                        kind=EmailChallengeKind.VERIFICATION.value,
                        token_hash=hashlib.sha256(b"old-verification-token").digest(),
                        encrypted_token="opaque-verification-token",  # noqa: S106
                        issued_at=now - timedelta(minutes=1),
                        expires_at=now + timedelta(minutes=9),
                    ),
                    EmailChallenge(
                        id=uuid4(),
                        person_id=person_id,
                        kind=EmailChallengeKind.PASSWORD_RESET.value,
                        token_hash=hashlib.sha256(b"old-reset-token").digest(),
                        encrypted_token="opaque-reset-token",  # noqa: S106
                        issued_at=now - timedelta(minutes=1),
                        expires_at=now + timedelta(minutes=9),
                    ),
                    IdentitySession(
                        id=uuid4(),
                        person_id=person_id,
                        token_hash=hashlib.sha256(b"old-unverified-session").digest(),
                        created_at=now - timedelta(minutes=1),
                        expires_at=now + timedelta(days=1),
                        audience="account",
                    ),
                ]
            )
        settings = _email_code_settings(
            postgres_harness.schema_url,
            public_tenant_id=public_tenant_id,
            operations_tenant_id=operations_tenant_id,
            consent_version=consent_version,
        )
        async_engine = create_async_engine(postgres_harness.schema_url, pool_pre_ping=True)
        sessions = async_sessionmaker(async_engine, expire_on_commit=False)
        async with sessions() as database, database.begin():
            await AuditRepository(database).append(
                tenant_id=public_tenant_id,
                actor_person_id=person_id,
                action="identity.learner_consent_accepted.v1",
                resource_type="person_consent",
                resource_id=person_id,
                payload={
                    "consent_version": previous_consent_version,
                    "previous_consent_version": None,
                    "previous_consented_at": None,
                    "explicit_acceptance": True,
                    "age_attestation": "18_plus_learner_declaration",
                    "terms_path": "/terms",
                    "privacy_path": "/privacy",
                    "accepted_via": "password_registration",
                },
                reason="Prior learner consent accepted during synthetic setup.",
                now=previous_consent_time,
            )
        application = FastAPI()
        register_problem_handlers(application)
        install_identity_http(
            application,
            settings=settings,
            sessions=async_sessionmaker(async_engine, expire_on_commit=False),
        )
        origin = "https://salesxray.authorityclosers.test"

        def client() -> httpx.AsyncClient:
            return httpx.AsyncClient(
                transport=httpx.ASGITransport(app=application, client=("127.0.0.1", 12345)),
                base_url=origin,
            )

        requester, verifier = client(), client()
        try:
            request = await requester.post(
                "/v1/auth/email-code/request",
                headers={"Origin": origin},
                json={
                    "email": email,
                    "consent": True,
                    "consent_version": consent_version,
                    "age_attested": True,
                    "surface": "sales_xray",
                    "return_path": "/",
                },
            )
            assert request.status_code == 202
            with Session(postgres_harness.engine) as database:
                challenge = database.scalar(
                    select(EmailLoginCode).where(EmailLoginCode.normalized_email == email)
                )
                assert challenge is not None
                code = decrypt_email_login_code(
                    settings.email_challenge_secret.get_secret_value(),
                    challenge,
                    generation_id=challenge.generation_id,
                )
            response = await verifier.post(
                "/v1/auth/email-code/verify",
                headers={"Origin": origin},
                json={
                    "email": email,
                    "code": code,
                    "surface": "sales_xray",
                    "return_path": "/",
                },
            )
            assert response.status_code == 200
            assert response.json()["account_created"] is False
            assert response.json()["person_id"] == str(person_id)
            me = await verifier.get("/v1/me")
            assert me.status_code == 200
            assert me.json()["selected_tenant_id"] == str(public_tenant_id)
            assert me.json()["membership_role"] == "learner"
            with Session(postgres_harness.engine) as database:
                person = database.get(Person, person_id)
                assert person is not None
                assert person.email_verified_at is not None
                assert person.consent_version == consent_version
                assert person.consented_at is not None
                membership = database.get(Membership, (public_tenant_id, person_id))
                assert membership is not None
                assert membership.role == "learner" and membership.status == "active"
                assert database.scalar(
                    select(PasswordCredential).where(PasswordCredential.person_id == person_id)
                ) is None
                old_challenges = list(
                    database.scalars(
                        select(EmailChallenge).where(EmailChallenge.person_id == person_id)
                    )
                )
                assert len(old_challenges) == 2
                assert all(item.consumed_at is not None for item in old_challenges)
                old_session = database.scalar(
                    select(IdentitySession).where(
                        IdentitySession.person_id == person_id,
                        IdentitySession.revocation_reason == "email_login_identity_reclaimed",
                    )
                )
                assert old_session is not None
                audit = database.scalar(
                    select(AuditEvent).where(
                        AuditEvent.tenant_id == operations_tenant_id,
                        AuditEvent.action == "identity.email_login_unverified_credential_reclaimed",
                        AuditEvent.resource_id == str(person_id),
                    )
                )
                assert audit is not None
                assert audit.payload == {
                    "password_credential_removed": True,
                    "email_challenges_consumed": 2,
                    "sessions_revoked": 1,
                }
                consent_history = list(
                    database.scalars(
                        select(AuditEvent)
                        .where(
                            AuditEvent.tenant_id == public_tenant_id,
                            AuditEvent.actor_person_id == person_id,
                            AuditEvent.action == "identity.learner_consent_accepted.v1",
                            AuditEvent.resource_type == "person_consent",
                            AuditEvent.resource_id == str(person_id),
                        )
                        .order_by(AuditEvent.sequence_no)
                    )
                )
                assert len(consent_history) == 2
                assert consent_history[0].payload["consent_version"] == previous_consent_version
                assert consent_history[1].occurred_at == person.consented_at
                assert consent_history[1].payload["consent_version"] == consent_version
                assert (
                    consent_history[1].payload["previous_consent_version"]
                    == previous_consent_version
                )
                assert (
                    consent_history[1].payload["previous_consented_at"]
                    == previous_consent_time.isoformat()
                )
                assert consent_history[1].payload["accepted_via"] == "email_otp"
                assert consent_history[1].payload["age_attestation"] == (
                    "18_plus_learner_declaration"
                )
            async with async_sessionmaker(async_engine)() as database, database.begin():
                try:
                    await PasswordIdentityService(
                        database,
                        token_secret=settings.email_challenge_secret.get_secret_value(),
                    ).authenticate(
                        email=email,
                        password="attacker-known-password-phrase",  # noqa: S106
                    )
                except InvalidPasswordCredentials:
                    pass
                else:
                    pytest.fail("the reclaimed unverified password authenticated")
        finally:
            await requester.aclose()
            await verifier.aclose()
            await async_engine.dispose()

    _run_async(scenario())


def test_email_login_never_authenticates_privileged_membership(postgres_harness: _Harness) -> None:
    async def scenario() -> None:
        public_tenant_id = uuid4()
        operations_tenant_id = uuid4()
        privileged_tenant_id = uuid4()
        privileged_id = uuid4()
        pending_id = uuid4()
        privileged_email = f"otp-admin-{privileged_id.hex}@example.test"
        pending_email = f"otp-pending-admin-{pending_id.hex}@example.test"
        consent_version = "email-admin-consent-v1"
        with Session(postgres_harness.engine) as database, database.begin():
            database.add_all(
                [
                    Tenant(
                        id=public_tenant_id,
                        slug=f"otp-admin-public-{public_tenant_id.hex}",
                        name="Email OTP public tenant",
                    ),
                    Tenant(
                        id=operations_tenant_id,
                        slug=f"otp-admin-ops-{operations_tenant_id.hex}",
                        name="Email OTP operations tenant",
                    ),
                    Tenant(
                        id=privileged_tenant_id,
                        slug=f"otp-admin-privileged-{privileged_tenant_id.hex}",
                        name="Email OTP privileged tenant",
                    ),
                    Person(
                        id=privileged_id,
                        email=privileged_email,
                        email_verified_at=datetime.now(UTC),
                    ),
                    Person(
                        id=pending_id,
                        email=pending_email,
                        email_verified_at=datetime.now(UTC),
                    ),
                ]
            )
            database.flush()
            database.add(
                Membership(
                    tenant_id=privileged_tenant_id,
                    person_id=privileged_id,
                    role=MembershipRole.ADMIN.value,
                    status=MembershipStatus.ACTIVE.value,
                )
            )
        settings = _email_code_settings(
            postgres_harness.schema_url,
            public_tenant_id=public_tenant_id,
            operations_tenant_id=operations_tenant_id,
            consent_version=consent_version,
        )
        async_engine = create_async_engine(postgres_harness.schema_url, pool_pre_ping=True)
        application = FastAPI()
        register_problem_handlers(application)
        install_identity_http(
            application,
            settings=settings,
            sessions=async_sessionmaker(async_engine, expire_on_commit=False),
        )
        origin = "https://salesxray.authorityclosers.test"
        client = httpx.AsyncClient(
            transport=httpx.ASGITransport(app=application, client=("127.0.0.1", 12345)),
            base_url=origin,
        )
        try:
            privileged_request = await client.post(
                "/v1/auth/email-code/request",
                headers={"Origin": origin},
                json={"email": privileged_email, "surface": "sales_xray"},
            )
            assert privileged_request.status_code == 202
            with Session(postgres_harness.engine) as database:
                assert (
                    database.scalar(
                        select(EmailLoginCode).where(
                            EmailLoginCode.normalized_email == privileged_email
                        )
                    )
                    is None
                )
            pending_request = await client.post(
                "/v1/auth/email-code/request",
                headers={"Origin": origin},
                json={"email": pending_email, "surface": "sales_xray"},
            )
            assert pending_request.status_code == 202
            with Session(postgres_harness.engine) as database:
                pending_challenge = database.scalar(
                    select(EmailLoginCode).where(EmailLoginCode.normalized_email == pending_email)
                )
                assert pending_challenge is not None
                code = decrypt_email_login_code(
                    settings.email_challenge_secret.get_secret_value(),
                    pending_challenge,
                    generation_id=pending_challenge.generation_id,
                )
            # Privilege is rechecked at consume time, not just when the email
            # is queued, so a newly granted admin role cannot inherit OTP auth.
            with Session(postgres_harness.engine) as database, database.begin():
                database.add(
                    Membership(
                        tenant_id=privileged_tenant_id,
                        person_id=pending_id,
                        role=MembershipRole.OWNER.value,
                        status=MembershipStatus.ACTIVE.value,
                    )
                )
            denied = await client.post(
                "/v1/auth/email-code/verify",
                headers={"Origin": origin},
                json={
                    "email": pending_email,
                    "code": code,
                    "surface": "sales_xray",
                    "return_path": "/",
                },
            )
            assert denied.status_code == 400
            assert "set-cookie" not in denied.headers
            with Session(postgres_harness.engine) as database:
                assert (
                    database.scalar(
                        select(func.count())
                        .select_from(IdentitySession)
                        .where(IdentitySession.person_id.in_((privileged_id, pending_id)))
                    )
                    == 0
                )
                consumed = database.get(EmailLoginCode, pending_challenge.id)
                assert consumed is not None
                assert consumed.consumed_at is not None
        finally:
            await client.aclose()
            await async_engine.dispose()

    _run_async(scenario())


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
            operations_tenant_id=uuid4(),
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

                # An unverified learner can recover from a missed signup email
                # through the normal recovery route, without receiving a reset
                # token or becoming verified before proving mailbox control.
                resend = await client.post(
                    "/v1/auth/password/recovery",
                    headers=headers,
                    json={"email": "learner@example.com"},
                )
                assert resend.status_code == 200
                assert resend.headers["cache-control"] == "no-store"
                assert resend.json() == {"accepted": True}
                assert "set-cookie" not in resend.headers

                with Session(postgres_harness.engine) as database:
                    assert database.get(Person, person.id).email_verified_at is None
                    assert (
                        database.scalar(
                            select(func.count())
                            .select_from(EmailChallenge)
                            .where(
                                EmailChallenge.person_id == person.id,
                                EmailChallenge.kind == EmailChallengeKind.PASSWORD_RESET.value,
                            )
                        )
                        == 0
                    )
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

                onboarding_payload = {
                    "experience_context": "sales",
                    "learning_goal": "Ask a clearer next-step question",
                    "practice_situation": None,
                    "weekly_minutes": 30,
                    "status": "completed",
                    "current_step": 3,
                }
                onboarding_key = str(uuid4())
                onboarding_headers = headers | {
                    "If-Match": '"onboarding-revision-0"',
                    "Idempotency-Key": onboarding_key,
                }
                missing_key = await client.put(
                    "/v1/onboarding",
                    headers=headers | {"If-Match": '"onboarding-revision-0"'},
                    json=onboarding_payload,
                )
                assert missing_key.status_code == 428
                assert missing_key.json()["code"] == "idempotency_key_required"

                committed_response, concurrent_replay = await asyncio.wait_for(
                    asyncio.gather(
                        client.put(
                            "/v1/onboarding",
                            headers=onboarding_headers,
                            json=onboarding_payload,
                        ),
                        client.put(
                            "/v1/onboarding",
                            headers=onboarding_headers,
                            json=onboarding_payload,
                        ),
                    ),
                    timeout=10,
                )
                assert committed_response.status_code == 200
                assert concurrent_replay.status_code == 200
                replayed_state = concurrent_replay.json()
                committed_state = committed_response.json()
                replayed_updated_at = datetime.fromisoformat(replayed_state.pop("updated_at"))
                committed_updated_at = datetime.fromisoformat(committed_state.pop("updated_at"))
                assert replayed_state == committed_state
                assert replayed_updated_at == committed_updated_at
                del committed_response  # The server committed, but the caller lost the response.

                profile = await client.put(
                    "/v1/onboarding",
                    headers=onboarding_headers,
                    json=onboarding_payload,
                )
                assert profile.status_code == 200
                assert profile.headers["etag"] == '"onboarding-revision-1"'
                assert profile.json()["next_action_href"] == "/home"
                assert (
                    "No unreviewed personalized course mapping"
                    in profile.json()["next_action_reason"]
                )
                with Session(postgres_harness.engine) as database:
                    refreshed_person = database.get(Person, person.id)
                    assert refreshed_person is not None
                    assert refreshed_person.onboarding_revision == 1
                    markers = list(
                        database.scalars(
                            select(AuditEvent).where(
                                AuditEvent.tenant_id == public_tenant_id,
                                AuditEvent.actor_person_id == person.id,
                                AuditEvent.action == "identity.onboarding_save_idempotency",
                            )
                        )
                    )
                    assert len(markers) == 1
                    marker_payload = markers[0].payload
                    assert set(marker_payload) == {
                        "operation",
                        "idempotency_key_digest",
                        "request_digest",
                        "result_person_id",
                        "result_revision",
                        "result_updated_at",
                    }
                    assert marker_payload["operation"] == "onboarding_save"
                    key_digest = hashlib.sha256(onboarding_key.encode("ascii")).hexdigest()
                    assert marker_payload["idempotency_key_digest"] == key_digest
                    assert onboarding_key not in str(marker_payload)
                    request_digest = marker_payload["request_digest"]
                    assert isinstance(request_digest, str)
                    assert len(request_digest) == 64
                    assert marker_payload["result_person_id"] == str(person.id)
                    assert marker_payload["result_revision"] == 1
                    result_updated_at = marker_payload["result_updated_at"]
                    assert isinstance(result_updated_at, str)
                    assert datetime.fromisoformat(result_updated_at) == datetime.fromisoformat(
                        profile.json()["updated_at"]
                    )
                    command = database.scalar(
                        select(IdentityCommandIdempotency).where(
                            IdentityCommandIdempotency.tenant_id == public_tenant_id,
                            IdentityCommandIdempotency.actor_person_id == person.id,
                            IdentityCommandIdempotency.operation == "onboarding_save",
                            IdentityCommandIdempotency.key_digest == key_digest,
                        )
                    )
                    assert command is not None
                    assert command.status == "completed"
                    assert command.request_digest == request_digest
                    assert command.result_revision == 1

                conflicting_reuse = await client.put(
                    "/v1/onboarding",
                    headers=onboarding_headers,
                    json=onboarding_payload | {"learning_goal": "A different canonical request"},
                )
                assert conflicting_reuse.status_code == 409
                assert conflicting_reuse.json()["code"] == "onboarding_idempotency_conflict"

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


def test_password_login_does_not_create_public_membership(
    postgres_harness: _Harness,
) -> None:
    async def scenario() -> None:
        person_id = uuid4()
        public_tenant_id = uuid4()
        password = "existing verified account password"  # noqa: S105
        now = datetime(2026, 9, 1, 10, tzinfo=UTC)
        with Session(postgres_harness.engine) as database, database.begin():
            database.add_all(
                [
                    Person(
                        id=person_id,
                        email=f"auth-only-{person_id.hex}@example.com",
                        first_name="Authentication only",
                        email_verified_at=now,
                    ),
                    Tenant(
                        id=public_tenant_id,
                        slug=f"auth-only-public-{person_id.hex}",
                        name="Authentication-only public tenant",
                    ),
                ]
            )
            database.flush()
            database.add(
                PasswordCredential(
                    person_id=person_id,
                    password_hash=hash_password(password),
                )
            )

        async_engine = create_async_engine(postgres_harness.schema_url, pool_pre_ping=True)
        sessions = async_sessionmaker(async_engine, expire_on_commit=False)
        settings = Settings(
            environment="test",
            database_url=postgres_harness.schema_url.render_as_string(hide_password=False),
            session_token_pepper="postgres-auth-only-pepper-that-is-long-enough",  # noqa: S106
            oauth_transaction_secret="postgres-auth-only-oauth-secret-long-enough",  # noqa: S106
            email_challenge_secret="postgres-auth-only-email-secret-long-enough",  # noqa: S106
            learner_consent_version="staging-test-document-v1",
            public_learner_tenant_id=public_tenant_id,
            operations_tenant_id=uuid4(),
            public_app_url="https://app.authorityclosers.test",
            admin_app_url="https://admin.authorityclosers.test",
            api_url="https://api.authorityclosers.test",
        )
        application = FastAPI()
        register_problem_handlers(application)
        install_identity_http(application, settings=settings, sessions=sessions)
        transport = httpx.ASGITransport(app=application, client=("127.0.0.1", 12345))
        try:
            async with httpx.AsyncClient(
                transport=transport,
                base_url="https://app.authorityclosers.test",
            ) as client:
                login = await client.post(
                    "/v1/auth/password/login",
                    headers={"Origin": "https://app.authorityclosers.test"},
                    json={
                        "email": f"auth-only-{person_id.hex}@example.com",
                        "password": password,
                    },
                )
                assert login.status_code == 200
                me = await client.get("/v1/me")
                assert me.status_code == 200
                assert me.json()["selected_tenant_id"] is None
                assert me.json()["membership_role"] is None
        finally:
            await async_engine.dispose()

        with Session(postgres_harness.engine) as database:
            assert database.get(Membership, (public_tenant_id, person_id)) is None

    _run_async(scenario())


def test_existing_google_identity_authenticates_concurrently_without_registration_config(
    postgres_harness: _Harness,
) -> None:
    async def scenario() -> None:
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
            learner_consent_version=None,
            public_learner_tenant_id=None,
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

        async def start(
            client: httpx.AsyncClient,
            *,
            return_path: str,
        ) -> AuthTransaction:
            started = await client.get(
                "/v1/auth/google/start",
                params={
                    "action": "authenticate",
                    "surface": "learner",
                    "return_path": return_path,
                },
                follow_redirects=False,
            )
            assert started.status_code == 303
            transaction = provider.transactions[-1]
            assert transaction.authorization_type is ProviderAuthorizationType.AUTHENTICATE
            assert transaction.consent_version is None
            return transaction

        try:
            async with httpx.AsyncClient(
                transport=transport,
                base_url="https://app.authorityclosers.test",
            ) as client:
                first_transaction = await start(client, return_path="/home?flow=first")
                second_transaction = await start(client, return_path="/home?flow=second")

                first_callback = await client.get(
                    "/v1/auth/google/callback",
                    params={
                        "state": first_transaction.state,
                        "code": "controlled-google-code",
                    },
                    follow_redirects=False,
                )
                assert first_callback.status_code == 303
                assert first_callback.headers["location"] == (
                    "https://app.authorityclosers.test/home?flow=first"
                )

                second_callback = await client.get(
                    "/v1/auth/google/callback",
                    params={
                        "state": second_transaction.state,
                        "code": "controlled-google-code",
                    },
                    follow_redirects=False,
                )
                assert second_callback.status_code == 303
                assert second_callback.headers["location"] == (
                    "https://app.authorityclosers.test/home?flow=second"
                )
                me = await client.get("/v1/me")
                assert me.status_code == 200
                assert me.json()["person_id"] == str(person_id)
                assert me.json()["selected_tenant_id"] == str(other_tenant_id)
                assert me.json()["membership_role"] == "support"

                with Session(postgres_harness.engine) as database:
                    session_rows = list(
                        database.scalars(
                            select(IdentitySession).where(IdentitySession.person_id == person_id)
                        )
                    )
                    assert len(session_rows) == 2
                    assert {row.selected_tenant_id for row in session_rows} == {other_tenant_id}
                    for accepted_transaction in (first_transaction, second_transaction):
                        transaction = database.get(
                            ProviderAuthorizationTransaction,
                            accepted_transaction.transaction_id,
                        )
                        assert transaction is not None
                        assert transaction.status == "consumed"
                        assert transaction.consumed_at is not None
                    assert database.get(Membership, (public_tenant_id, person_id)) is None
                    support_membership = database.get(
                        Membership,
                        (other_tenant_id, person_id),
                    )
                    assert support_membership is not None
                    assert support_membership.role == "support"
        finally:
            await async_engine.dispose()

    _run_async(scenario())


def test_unknown_google_identity_authenticate_callback_fails_closed_without_registration(
    postgres_harness: _Harness,
) -> None:
    async def scenario() -> None:
        provider_subject = f"google-unknown-{uuid4().hex}"
        provider_email = f"google-unknown-{uuid4().hex}@example.com"
        async_engine = create_async_engine(postgres_harness.schema_url, pool_pre_ping=True)
        sessions = async_sessionmaker(async_engine, expire_on_commit=False)
        provider = _ExistingGoogleProvider(email=provider_email, subject=provider_subject)
        settings = Settings(
            environment="test",
            database_url=postgres_harness.schema_url.render_as_string(hide_password=False),
            session_token_pepper="postgres-unknown-google-token-pepper-long-enough",  # noqa: S106
            oauth_transaction_secret="postgres-unknown-google-transaction-secret-long-enough",  # noqa: S106
            email_challenge_secret="postgres-unknown-google-email-secret-long-enough",  # noqa: S106
            learner_consent_version=None,
            public_learner_tenant_id=None,
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
        try:
            async with httpx.AsyncClient(
                transport=transport,
                base_url="https://app.authorityclosers.test",
            ) as client:
                started = await client.get(
                    "/v1/auth/google/start",
                    params={"action": "authenticate", "surface": "learner"},
                    follow_redirects=False,
                )
                assert started.status_code == 303
                transaction = provider.transactions[-1]

                callback = await client.get(
                    "/v1/auth/google/callback",
                    params={"state": transaction.state, "code": "controlled-google-code"},
                    follow_redirects=False,
                )
                assert callback.status_code == 303
                assert callback.headers["location"] == (
                    "https://app.authorityclosers.test/auth/callback?result=registration_required"
                )
                assert (await client.get("/v1/me")).status_code == 401

            with Session(postgres_harness.engine) as database:
                authorization = database.get(
                    ProviderAuthorizationTransaction,
                    transaction.transaction_id,
                )
                assert authorization is not None
                assert authorization.status == "issued"
                assert authorization.consumed_at is None
                assert (
                    database.scalar(
                        select(func.count())
                        .select_from(ProviderIdentity)
                        .where(ProviderIdentity.subject == provider_subject)
                    )
                    == 0
                )
                assert (
                    database.scalar(
                        select(func.count())
                        .select_from(Person)
                        .where(Person.email == provider_email)
                    )
                    == 0
                )
        finally:
            await async_engine.dispose()

    _run_async(scenario())


def test_existing_google_registration_records_first_consent_and_enables_password_setup(
    postgres_harness: _Harness,
) -> None:
    async def scenario() -> None:
        consent_version = "staging-test-document-v1"
        now = datetime(2026, 8, 31, 12, tzinfo=UTC)
        person_id = uuid4()
        public_tenant_id = uuid4()
        provider_subject = f"google-consent-upgrade-{person_id.hex}"
        provider_email = f"google-consent-upgrade-{person_id.hex}@example.com"
        challenge_secret = "postgres-consent-upgrade-email-secret-long-enough"  # noqa: S105
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
                        slug=f"google-upgrade-{person_id.hex}",
                        name="Google consent-upgrade learner tenant",
                    ),
                ]
            )

        async_engine = create_async_engine(postgres_harness.schema_url, pool_pre_ping=True)
        sessions = async_sessionmaker(async_engine, expire_on_commit=False)
        provider = _ExistingGoogleProvider(email=provider_email, subject=provider_subject)
        settings = Settings(
            environment="test",
            database_url=postgres_harness.schema_url.render_as_string(hide_password=False),
            session_token_pepper="postgres-consent-upgrade-token-pepper-long-enough",  # noqa: S106
            oauth_transaction_secret="postgres-consent-upgrade-transaction-secret-long-enough",  # noqa: S106
            email_challenge_secret=challenge_secret,
            learner_consent_version=consent_version,
            public_learner_tenant_id=public_tenant_id,
            operations_tenant_id=uuid4(),
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
        headers = {"Origin": "https://app.authorityclosers.test"}
        try:
            async with httpx.AsyncClient(
                transport=transport,
                base_url="https://app.authorityclosers.test",
            ) as client:
                started = await client.get(
                    "/v1/auth/google/start",
                    params={
                        "action": "register",
                        "surface": "learner",
                        "return_path": "/home",
                        "consent": "true",
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
                assert callback.status_code == 303
                assert callback.headers["location"] == "https://app.authorityclosers.test/home"
                me = await client.get("/v1/me")
                assert me.status_code == 200
                assert me.json()["person_id"] == str(person_id)
                assert me.json()["selected_tenant_id"] == str(public_tenant_id)

                with Session(postgres_harness.engine) as database:
                    person = database.get(Person, person_id)
                    assert person is not None
                    assert person.consent_version == consent_version
                    assert person.consented_at is not None
                    assert database.get(Membership, (public_tenant_id, person_id)) is not None
                    assert database.scalar(
                        select(PasswordCredential).where(PasswordCredential.person_id == person_id)
                    ) is None

                recovery = await client.post(
                    "/v1/auth/password/recovery",
                    headers=headers,
                    json={"email": provider_email},
                )
                assert recovery.status_code == 200
                with Session(postgres_harness.engine) as database:
                    challenge = database.scalar(
                        select(EmailChallenge)
                        .where(
                            EmailChallenge.person_id == person_id,
                            EmailChallenge.kind == EmailChallengeKind.PASSWORD_RESET.value,
                            EmailChallenge.consumed_at.is_(None),
                        )
                        .order_by(EmailChallenge.issued_at.desc())
                    )
                    assert challenge is not None
                    reset_token = decrypt_challenge_token(
                        challenge_secret,
                        challenge.encrypted_token,
                        kind=EmailChallengeKind.PASSWORD_RESET,
                        person_id=person_id,
                    )

                repeated_recovery, reset = await asyncio.wait_for(
                    asyncio.gather(
                        client.post(
                            "/v1/auth/password/recovery",
                            headers=headers,
                            json={"email": provider_email},
                        ),
                        client.post(
                            "/v1/auth/password/reset",
                            headers=headers,
                            json={
                                "token": reset_token,
                                "new_password": "provider learner password",
                            },
                        ),
                    ),
                    timeout=10,
                )
                assert repeated_recovery.status_code == 200
                assert reset.status_code in {200, 400}
                if reset.status_code == 400:
                    with Session(postgres_harness.engine) as database:
                        replacement = database.scalar(
                            select(EmailChallenge)
                            .where(
                                EmailChallenge.person_id == person_id,
                                EmailChallenge.kind == EmailChallengeKind.PASSWORD_RESET.value,
                                EmailChallenge.consumed_at.is_(None),
                            )
                            .order_by(EmailChallenge.issued_at.desc())
                        )
                        assert replacement is not None
                        replacement_token = decrypt_challenge_token(
                            challenge_secret,
                            replacement.encrypted_token,
                            kind=EmailChallengeKind.PASSWORD_RESET,
                            person_id=person_id,
                        )
                    reset = await client.post(
                        "/v1/auth/password/reset",
                        headers=headers,
                        json={
                            "token": replacement_token,
                            "new_password": "provider learner password",
                        },
                    )
                    assert reset.status_code == 200
                assert (await client.get("/v1/me")).status_code == 401
                login = await client.post(
                    "/v1/auth/password/login",
                    headers=headers,
                    json={
                        "email": provider_email,
                        "password": "provider learner password",
                    },
                )
                assert login.status_code == 200
                assert (await client.get("/v1/me")).status_code == 200
        finally:
            await async_engine.dispose()

    _run_async(scenario())


def test_concurrent_existing_google_registrations_share_one_canonical_person(
    postgres_harness: _Harness,
) -> None:
    async def scenario() -> None:
        consent_version = "staging-test-document-v1"
        now = datetime(2026, 8, 31, 12, tzinfo=UTC)
        person_id = uuid4()
        public_tenant_id = uuid4()
        provider_subject = f"google-concurrent-existing-{person_id.hex}"
        provider_email = f"google-concurrent-existing-{person_id.hex}@example.com"
        with Session(postgres_harness.engine) as database, database.begin():
            database.add_all(
                [
                    Person(
                        id=person_id,
                        email=provider_email,
                        first_name="Existing learner",
                        email_verified_at=now,
                    ),
                    ProviderIdentity(
                        person_id=person_id,
                        issuer="https://accounts.google.com",
                        subject=provider_subject,
                    ),
                    Tenant(
                        id=public_tenant_id,
                        slug=f"google-concurrent-{person_id.hex}",
                        name="Google concurrent learner tenant",
                    ),
                ]
            )

        async_engine = create_async_engine(postgres_harness.schema_url, pool_pre_ping=True)
        sessions = async_sessionmaker(async_engine, expire_on_commit=False)
        provider = _ExistingGoogleProvider(email=provider_email, subject=provider_subject)
        settings = Settings(
            environment="test",
            database_url=postgres_harness.schema_url.render_as_string(hide_password=False),
            session_token_pepper="postgres-concurrent-token-pepper-long-enough",  # noqa: S106
            oauth_transaction_secret="postgres-concurrent-transaction-secret-long-enough",  # noqa: S106
            email_challenge_secret="postgres-concurrent-email-secret-long-enough",  # noqa: S106
            learner_consent_version=consent_version,
            public_learner_tenant_id=public_tenant_id,
            operations_tenant_id=uuid4(),
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
        clients = [
            httpx.AsyncClient(
                transport=transport,
                base_url="https://app.authorityclosers.test",
            )
            for _ in range(2)
        ]
        try:
            starts = []
            for client in clients:
                started = await client.get(
                    "/v1/auth/google/start",
                    params={
                        "action": "register",
                        "surface": "learner",
                        "return_path": "/home",
                        "consent": "true",
                    },
                    follow_redirects=False,
                )
                assert started.status_code == 303
                starts.append(provider.transactions[-1])

            callbacks = await asyncio.wait_for(
                asyncio.gather(
                    *(
                        client.get(
                            "/v1/auth/google/callback",
                            params={
                                "state": transaction.state,
                                "code": "controlled-google-code",
                            },
                            follow_redirects=False,
                        )
                        for client, transaction in zip(clients, starts, strict=True)
                    )
                ),
                timeout=10,
            )
            assert [response.status_code for response in callbacks] == [303, 303]
            assert [(await client.get("/v1/me")).status_code for client in clients] == [200, 200]

            with Session(postgres_harness.engine) as database:
                people = list(
                    database.scalars(select(Person).where(Person.email == provider_email))
                )
                assert [person.id for person in people] == [person_id]
                person = people[0]
                assert person.consent_version == consent_version
                assert person.consented_at is not None
                assert (
                    database.scalar(
                        select(func.count())
                        .select_from(ProviderIdentity)
                        .where(
                            ProviderIdentity.issuer == "https://accounts.google.com",
                            ProviderIdentity.subject == provider_subject,
                        )
                    )
                    == 1
                )
                assert (
                    database.scalar(
                        select(func.count())
                        .select_from(IdentitySession)
                        .where(IdentitySession.person_id == person_id)
                    )
                    == 2
                )
                assert database.get(Membership, (public_tenant_id, person_id)) is not None
        finally:
            for client in clients:
                await client.aclose()
            await async_engine.dispose()

    _run_async(scenario())


def test_concurrent_new_google_registrations_never_commit_an_orphan_person(
    postgres_harness: _Harness,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def scenario() -> None:
        public_tenant_id = uuid4()
        provider_subject = f"google-concurrent-new-{uuid4().hex}"
        provider_email = f"google-concurrent-new-{uuid4().hex}@example.com"
        with Session(postgres_harness.engine) as database, database.begin():
            database.add(
                Tenant(
                    id=public_tenant_id,
                    slug=f"google-concurrent-new-{public_tenant_id.hex}",
                    name="Google concurrent new learner tenant",
                )
            )

        async_engine = create_async_engine(postgres_harness.schema_url, pool_pre_ping=True)
        sessions = async_sessionmaker(async_engine, expire_on_commit=False)
        provider = _ExistingGoogleProvider(email=provider_email, subject=provider_subject)

        original_lookup = AsyncSqlAlchemyIdentityRepository.find_provider_identities
        absent_lookups = 0
        both_observed_absent = asyncio.Event()

        async def synchronize_absent_lookup(self, issuer: str, subject: str):
            nonlocal absent_lookups
            matches = await original_lookup(self, issuer, subject)
            if (
                issuer == "https://accounts.google.com"
                and subject == provider_subject
                and not matches
            ):
                absent_lookups += 1
                if absent_lookups == 2:
                    both_observed_absent.set()
                await asyncio.wait_for(both_observed_absent.wait(), timeout=5)
            return matches

        monkeypatch.setattr(
            AsyncSqlAlchemyIdentityRepository,
            "find_provider_identities",
            synchronize_absent_lookup,
        )
        settings = Settings(
            environment="test",
            database_url=postgres_harness.schema_url.render_as_string(hide_password=False),
            session_token_pepper="postgres-concurrent-new-token-pepper-long-enough",  # noqa: S106
            oauth_transaction_secret="postgres-concurrent-new-transaction-secret-long-enough",  # noqa: S106
            email_challenge_secret="postgres-concurrent-new-email-secret-long-enough",  # noqa: S106
            learner_consent_version="staging-test-document-v1",
            public_learner_tenant_id=public_tenant_id,
            operations_tenant_id=uuid4(),
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
        clients = [
            httpx.AsyncClient(
                transport=transport,
                base_url="https://app.authorityclosers.test",
            )
            for _ in range(2)
        ]
        try:
            transactions = []
            for client in clients:
                started = await client.get(
                    "/v1/auth/google/start",
                    params={
                        "action": "register",
                        "surface": "learner",
                        "consent": "true",
                    },
                    follow_redirects=False,
                )
                assert started.status_code == 303
                transactions.append(provider.transactions[-1])

            callbacks = await asyncio.wait_for(
                asyncio.gather(
                    *(
                        client.get(
                            "/v1/auth/google/callback",
                            params={
                                "state": transaction.state,
                                "code": "controlled-google-code",
                            },
                            follow_redirects=False,
                        )
                        for client, transaction in zip(clients, transactions, strict=True)
                    )
                ),
                timeout=10,
            )
            assert sorted(response.status_code for response in callbacks) == [303, 409]
            assert absent_lookups == 2
            assert sorted([(await client.get("/v1/me")).status_code for client in clients]) == [
                200,
                401,
            ]

            with Session(postgres_harness.engine) as database:
                people = list(
                    database.scalars(select(Person).where(Person.email == provider_email))
                )
                assert len(people) == 1
                person_id = people[0].id
                assert (
                    database.scalar(
                        select(func.count())
                        .select_from(ProviderIdentity)
                        .where(
                            ProviderIdentity.issuer == "https://accounts.google.com",
                            ProviderIdentity.subject == provider_subject,
                            ProviderIdentity.person_id == person_id,
                        )
                    )
                    == 1
                )
                assert (
                    database.scalar(
                        select(func.count())
                        .select_from(IdentitySession)
                        .where(IdentitySession.person_id == person_id)
                    )
                    == 1
                )
                assert database.get(Membership, (public_tenant_id, person_id)) is not None
        finally:
            for client in clients:
                await client.aclose()
            await async_engine.dispose()

    _run_async(scenario())


def test_existing_google_registration_does_not_overwrite_different_consent(
    postgres_harness: _Harness,
) -> None:
    async def scenario() -> None:
        current_consent_version = "staging-test-document-v2"
        previous_consent_version = "staging-test-document-v1"
        consented_at = datetime(2026, 8, 30, 12, tzinfo=UTC)
        person_id = uuid4()
        public_tenant_id = uuid4()
        provider_subject = f"google-stale-consent-{person_id.hex}"
        provider_email = f"google-stale-consent-{person_id.hex}@example.com"
        with Session(postgres_harness.engine) as database, database.begin():
            database.add_all(
                [
                    Person(
                        id=person_id,
                        email=provider_email,
                        first_name="Existing learner",
                        email_verified_at=consented_at,
                        consent_version=previous_consent_version,
                        consented_at=consented_at,
                    ),
                    ProviderIdentity(
                        person_id=person_id,
                        issuer="https://accounts.google.com",
                        subject=provider_subject,
                    ),
                    Tenant(
                        id=public_tenant_id,
                        slug=f"google-stale-{person_id.hex}",
                        name="Google stale-consent learner tenant",
                    ),
                ]
            )

        async_engine = create_async_engine(postgres_harness.schema_url, pool_pre_ping=True)
        sessions = async_sessionmaker(async_engine, expire_on_commit=False)
        provider = _ExistingGoogleProvider(email=provider_email, subject=provider_subject)
        settings = Settings(
            environment="test",
            database_url=postgres_harness.schema_url.render_as_string(hide_password=False),
            session_token_pepper="postgres-stale-consent-token-pepper-long-enough",  # noqa: S106
            oauth_transaction_secret="postgres-stale-consent-transaction-secret-long-enough",  # noqa: S106
            email_challenge_secret="postgres-stale-consent-email-secret-long-enough",  # noqa: S106
            learner_consent_version=current_consent_version,
            public_learner_tenant_id=public_tenant_id,
            operations_tenant_id=uuid4(),
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
        try:
            async with httpx.AsyncClient(
                transport=transport,
                base_url="https://app.authorityclosers.test",
            ) as client:
                started = await client.get(
                    "/v1/auth/google/start",
                    params={
                        "action": "register",
                        "surface": "learner",
                        "consent": "true",
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
                assert callback.status_code == 303
                assert callback.headers["location"] == (
                    "https://app.authorityclosers.test/auth/callback?result=consent_update_required"
                )
                assert (await client.get("/v1/me")).status_code == 401

            with Session(postgres_harness.engine) as database:
                person = database.get(Person, person_id)
                assert person is not None
                assert person.consent_version == previous_consent_version
                assert person.consented_at == consented_at
                authorization = database.get(
                    ProviderAuthorizationTransaction,
                    transaction.transaction_id,
                )
                assert authorization is not None
                assert authorization.status == "issued"
                assert authorization.consumed_at is None
                assert database.get(Membership, (public_tenant_id, person_id)) is None
                assert (
                    database.scalar(
                        select(func.count())
                        .select_from(IdentitySession)
                        .where(IdentitySession.person_id == person_id)
                    )
                    == 0
                )
        finally:
            await async_engine.dispose()

    _run_async(scenario())


def test_new_google_learner_registration_persists_consent_and_public_membership(
    postgres_harness: _Harness,
) -> None:
    async def scenario() -> None:
        consent_version = "staging-test-document-v1"
        public_tenant_id = uuid4()
        provider_email = f"google-new-{uuid4().hex}@example.com"
        provider_subject = f"google-new-{uuid4().hex}"
        with Session(postgres_harness.engine) as database, database.begin():
            database.add(
                Tenant(
                    id=public_tenant_id,
                    slug=f"google-new-{public_tenant_id.hex}",
                    name="Google public learner tenant",
                )
            )

        async_engine = create_async_engine(postgres_harness.schema_url, pool_pre_ping=True)
        sessions = async_sessionmaker(async_engine, expire_on_commit=False)
        provider = _ExistingGoogleProvider(email=provider_email, subject=provider_subject)
        settings = Settings(
            environment="test",
            database_url=postgres_harness.schema_url.render_as_string(hide_password=False),
            session_token_pepper="postgres-new-google-token-pepper-long-enough",  # noqa: S106
            oauth_transaction_secret="postgres-new-google-transaction-secret-long-enough",  # noqa: S106
            email_challenge_secret="postgres-new-google-email-secret-long-enough",  # noqa: S106
            learner_consent_version=consent_version,
            public_learner_tenant_id=public_tenant_id,
            operations_tenant_id=uuid4(),
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
        person_id = None
        transaction_id = None
        try:
            async with httpx.AsyncClient(
                transport=transport,
                base_url="https://app.authorityclosers.test",
            ) as client:
                started = await client.get(
                    "/v1/auth/google/start",
                    params={
                        "action": "register",
                        "surface": "learner",
                        "consent": "true",
                    },
                    follow_redirects=False,
                )
                assert started.status_code == 303
                transaction = provider.transactions[-1]
                transaction_id = transaction.transaction_id
                assert transaction.consent_version == consent_version

                callback = await client.get(
                    "/v1/auth/google/callback",
                    params={"state": transaction.state, "code": "controlled-google-code"},
                    follow_redirects=False,
                )
                assert callback.status_code == 303
                assert callback.headers["location"] == "https://app.authorityclosers.test/home"

                me = await client.get("/v1/me")
                assert me.status_code == 200
                person_id = UUID(me.json()["person_id"])
                assert me.json()["selected_tenant_id"] == str(public_tenant_id)
                assert me.json()["membership_role"] == "learner"

            with Session(postgres_harness.engine) as database:
                person = database.get(Person, person_id)
                assert person is not None
                assert person.consent_version == consent_version
                assert person.consented_at is not None
                assert person.email_verified_at is not None
                membership = database.get(Membership, (public_tenant_id, person_id))
                assert membership is not None
                assert membership.role == "learner"
                assert membership.status == "active"
                transaction_row = database.get(
                    ProviderAuthorizationTransaction,
                    transaction_id,
                )
                assert transaction_row is not None
                assert transaction_row.status == "consumed"
                assert transaction_row.consumed_at is not None
                assert (
                    database.scalar(
                        select(func.count())
                        .select_from(IdentitySession)
                        .where(IdentitySession.person_id == person_id)
                    )
                    == 1
                )
        finally:
            await async_engine.dispose()
            with Session(postgres_harness.engine) as database, database.begin():
                if person_id is not None:
                    database.execute(
                        delete(IdentitySession).where(IdentitySession.person_id == person_id)
                    )
                    database.execute(delete(Membership).where(Membership.person_id == person_id))
                    database.execute(
                        delete(ProviderIdentity).where(ProviderIdentity.person_id == person_id)
                    )
                    database.execute(delete(Person).where(Person.id == person_id))
                if transaction_id is not None:
                    database.execute(
                        delete(ProviderAuthorizationTransaction).where(
                            ProviderAuthorizationTransaction.id == transaction_id
                        )
                    )
                database.execute(delete(Tenant).where(Tenant.id == public_tenant_id))

    _run_async(scenario())
