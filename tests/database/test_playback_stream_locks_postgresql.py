"""19 Oct pool incident: an open audio stream must not block the same person's writes.

Real cookie authentication and PostgreSQL. The stream is held open the way a
phone does it (it stops reading); meanwhile the same person signs in with the
locking resolver every write route starts with, and asks for /v1/me.
"""

from __future__ import annotations

import asyncio
import hashlib
import hmac
import secrets
import threading
import time
from dataclasses import replace
from pathlib import Path
from typing import Any

import httpx
import pytest
from fastapi import FastAPI
from sqlalchemy import text, update
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from ac_platform.application.settings import Settings
from ac_platform.conversation_intelligence.application import AUDIOATLAS_HOSTED_RECIPE
from ac_platform.http.auth import install_identity_http
from ac_platform.http.conversation import install_conversation_http
from ac_platform.http.conversation_intake import ConversationIntakeRuntime
from ac_platform.http.problem import register_problem_handlers
from ac_platform.identity.application import AsyncIdentityApplication
from ac_platform.identity.models import Session as IdentitySession
from tests.database.test_conversation_intake_postgresql import policy
from tests.database.test_conversation_postgresql import postgres_harness as _postgres_harness
from tests.database.test_conversation_postgresql import run
from tests.database.test_conversation_reports_postgresql import _build_fixture


@pytest.fixture(scope="module")
def postgres_harness() -> Any:
    yield from _postgres_harness.__wrapped__()


def test_an_open_audio_stream_does_not_block_the_same_persons_writes(
    postgres_harness: Any, tmp_path: Path
) -> None:
    async def exercise() -> None:
        fixture = await _build_fixture(postgres_harness, tmp_path)
        prepared = fixture.prepared
        engine = create_async_engine(postgres_harness.url)
        sessions = async_sessionmaker(engine, expire_on_commit=False)
        pepper = "synthetic-http-session-pepper-for-local-proof"
        token = secrets.token_urlsafe(32)
        settings = Settings(
            _env_file=None,
            environment="test",
            public_app_url="http://learner.test",
            admin_app_url="http://admin.test",
            coach_app_url="http://coach.test",
            api_url="http://api.test",
            session_token_pepper=pepper,
            oauth_transaction_secret=secrets.token_urlsafe(32),
            email_challenge_secret=secrets.token_urlsafe(32),
        )
        runtime = ConversationIntakeRuntime(
            replace(
                policy(prepared.scope_id, prepared.state.tenant_id),
                acoustic_recipe=AUDIOATLAS_HOSTED_RECIPE,
            ),
            prepared.storage,
            prepared.scratch,
        )
        app = FastAPI()
        register_problem_handlers(app)
        require_actor = install_identity_http(app, settings=settings, sessions=sessions)
        install_conversation_http(
            app, settings=settings, require_actor=require_actor, intake_runtime=runtime
        )
        async with sessions() as database, database.begin():
            await database.execute(
                update(IdentitySession)
                .where(IdentitySession.id == prepared.state.session_id)
                .values(
                    token_hash=hmac.new(pepper.encode(), token.encode(), hashlib.sha256).digest()
                )
            )
        cookie = {"Cookie": f"{settings.session_cookie_name}={token}"}

        # The phone reads the first bytes, then stops reading: the stream stays open.
        reading = threading.Event()
        resume = threading.Event()
        original = prepared.storage.iter_bytes

        def held(key: str, **kwargs: Any) -> Any:
            for chunk in original(key, **kwargs):
                half = max(1, len(chunk) // 2)
                yield chunk[:half]
                reading.set()
                resume.wait(60)
                yield chunk[half:]

        prepared.storage.iter_bytes = held  # type: ignore[method-assign]
        try:
            async with httpx.AsyncClient(
                transport=httpx.ASGITransport(app=app), base_url="http://learner.test"
            ) as client:
                stream = asyncio.create_task(
                    client.get(
                        f"/v1/conversation/recordings/{prepared.recording_id}/source",
                        headers=cookie,
                    )
                )
                assert await asyncio.to_thread(reading.wait, 30), "the stream never started"

                # The locking sign-in every write route starts with goes straight through.
                started = time.monotonic()
                async with asyncio.timeout(10):
                    async with sessions() as database, database.begin():
                        resolved = await AsyncIdentityApplication(
                            database, token_pepper=pepper
                        ).resolve_actor(token)
                assert resolved.actor.person_id == prepared.state.person_id
                assert time.monotonic() - started < 3

                # So does a real request of the same person over HTTP.
                started = time.monotonic()
                me = await asyncio.wait_for(client.get("/v1/me", headers=cookie), 10)
                assert me.status_code == 200 and time.monotonic() - started < 3

                # The open stream holds no transaction on the server.
                async with engine.connect() as connection:
                    open_transactions = (
                        await connection.execute(
                            text(
                                "SELECT count(*) FROM pg_stat_activity"
                                " WHERE datname = current_database()"
                                " AND state LIKE 'idle in transaction%'"
                            )
                        )
                    ).scalar()
                assert open_transactions == 0

                resume.set()
                whole = await asyncio.wait_for(stream, 30)
                assert whole.status_code == 200
                assert whole.content == prepared.data
        finally:
            resume.set()
            prepared.storage.iter_bytes = original  # type: ignore[method-assign]
            await engine.dispose()

    run(exercise())
