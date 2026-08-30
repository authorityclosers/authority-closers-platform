"""Fresh-PostgreSQL proof for password identity and progressive onboarding."""

from __future__ import annotations

import asyncio
import os
import subprocess
import sys
from collections.abc import Coroutine, Iterator
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from uuid import uuid4

import httpx
import pytest
from fastapi import FastAPI
from sqlalchemy import Engine, create_engine, select
from sqlalchemy.engine import URL, make_url
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.orm import Session
from sqlalchemy.schema import CreateSchema, DropSchema

from ac_platform.application.settings import Settings
from ac_platform.http.auth import install_identity_http
from ac_platform.http.problem import register_problem_handlers
from ac_platform.identity.models import EmailChallenge, EmailChallengeKind, Person
from ac_platform.identity.password_auth import decrypt_challenge_token
from ac_platform.outbox.models import OutboxEvent


@dataclass(frozen=True, slots=True)
class _Harness:
    engine: Engine
    schema_url: URL


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
        settings = Settings(
            environment="test",
            database_url=postgres_harness.schema_url.render_as_string(hide_password=False),
            session_token_pepper=token_pepper,
            oauth_transaction_secret="postgres-oauth-transaction-secret-long-enough",  # noqa: S106
            email_challenge_secret=challenge_secret,
            learner_consent_version="staging-test-document-v1",
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
                assert (await client.get("/v1/me")).status_code == 200
        finally:
            await async_engine.dispose()

    _run_async(scenario())
