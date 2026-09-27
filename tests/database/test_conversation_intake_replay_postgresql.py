"""PostgreSQL/HTTP proof for the bounded committed-source intake replay."""

from __future__ import annotations

import hashlib
import hmac
import secrets
from dataclasses import replace
from datetime import timedelta
from pathlib import Path
from typing import Any
from uuid import UUID, uuid4

import httpx
import pytest
from fastapi import FastAPI
from sqlalchemy import update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from ac_platform.application.settings import Settings
from ac_platform.conversation_intelligence.application import (
    ConversationApplication,
    ConversationConflict,
    ConversationDenied,
)
from ac_platform.conversation_intelligence.contracts import IntakeIntent, QuoteAcceptance
from ac_platform.conversation_intelligence.intake import ConversationIntake
from ac_platform.conversation_intelligence.models import (
    ConversationPermission,
    ConversationRecording,
)
from ac_platform.conversation_intelligence.storage import (
    PrivateLocalRecordingStorage,
    StorageError,
)
from ac_platform.http.auth import install_identity_http
from ac_platform.http.conversation import install_conversation_http
from ac_platform.http.conversation_intake import ConversationIntakeRuntime
from ac_platform.http.problem import register_problem_handlers
from ac_platform.identity.models import Person
from ac_platform.identity.models import Session as IdentitySession
from tests.database.test_conversation_intake_postgresql import add_allowance, policy
from tests.database.test_conversation_postgresql import (
    postgres_harness as _postgres_harness,
)
from tests.database.test_conversation_postgresql import run, seed, seed_budget


@pytest.fixture(scope="module")
def postgres_harness() -> Any:
    yield from _postgres_harness.__wrapped__()


def _intent(source: bytes) -> IntakeIntent:
    return IntakeIntent(
        source_sha256=hashlib.sha256(source).hexdigest(),
        source_bytes=len(source),
        content_type="audio/wav",
        duration_ms=1_000,
        purpose="internal_analysis",
    )


async def _prepare(
    engine: Any,
    state: Any,
    scope_id: UUID,
    source: bytes,
    *,
    key: str,
    now: Any | None = None,
) -> tuple[IntakeIntent, dict[str, Any]]:
    intent = _intent(source)
    async with AsyncSession(engine) as database, database.begin():
        intake = ConversationIntake(
            ConversationApplication(database, clock=lambda: now or state.now),
            policy(scope_id, state.tenant_id),
        )
        view = await intake.prepare(state.actor, intent, key=key)
    return intent, view


async def _accept(
    engine: Any,
    state: Any,
    scope_id: UUID,
    view: dict[str, Any],
    *,
    now: Any | None = None,
) -> None:
    async with AsyncSession(engine) as database, database.begin():
        await ConversationIntake(
            ConversationApplication(database, clock=lambda: now or state.now),
            policy(scope_id, state.tenant_id),
        ).accept(
            state.actor,
            UUID(view["id"]),
            QuoteAcceptance(
                quote_fingerprint=view["quote_fingerprint"],
                privacy_revision=view["privacy_revision"],
                accepted=True,
            ),
        )


async def _store(
    engine: Any,
    state: Any,
    recording_id: UUID,
    source: bytes,
    storage: PrivateLocalRecordingStorage,
    *,
    now: Any | None = None,
) -> dict[str, Any]:
    async with AsyncSession(engine) as database, database.begin():
        return await ConversationApplication(database, clock=lambda: now or state.now).store_source(
            state.actor,
            recording_id,
            chunks=(source[index : index + 3] for index in range(0, len(source), 3)),
            storage=storage,
        )


def test_ready_source_replays_after_quote_expiry_but_changed_bytes_do_not(
    postgres_harness: Any, tmp_path: Path
) -> None:
    async def exercise() -> None:
        engine = create_async_engine(postgres_harness.url)
        storage = PrivateLocalRecordingStorage(tmp_path / "source-store")
        source = b"synthetic committed replay source"
        changed = source[:-1] + b"!"
        try:
            state = await seed(engine)
            scope_id = await seed_budget(engine)
            await add_allowance(engine, state.tenant_id, state.person_id, seconds=900)
            intent, view = await _prepare(engine, state, scope_id, source, key="replay-quote")
            await _accept(engine, state, scope_id, view)
            first = await _store(engine, state, UUID(view["recording_id"]), source, storage)
            assert first["state"] == "ready"

            expired = replace(state, now=state.now + timedelta(minutes=31))
            async with AsyncSession(engine) as database, database.begin():
                intake = ConversationIntake(
                    ConversationApplication(database, clock=lambda: expired.now),
                    policy(scope_id, state.tenant_id),
                )
                # This is the regression: an authenticated retry must inspect
                # durable source state before applying the short quote expiry.
                replay = await intake.require_accepted(
                    expired.actor, UUID(view["recording_id"]), UUID(view["id"])
                )
                assert replay["state"] == "ready"

            repeated = await _store(
                engine,
                expired,
                UUID(view["recording_id"]),
                source,
                storage,
                now=expired.now,
            )
            assert repeated["state"] == "ready"

            other_session = uuid4()
            other = replace(expired, session_id=other_session)
            async with AsyncSession(engine) as database, database.begin():
                database.add(
                    IdentitySession(
                        id=other_session,
                        person_id=state.person_id,
                        selected_tenant_id=state.tenant_id,
                        token_hash=other_session.bytes * 2,
                        expires_at=expired.now + timedelta(days=1),
                    )
                )
                await database.flush()
                with pytest.raises(ConversationDenied, match="Approve this recording"):
                    await ConversationIntake(
                        ConversationApplication(database, clock=lambda: expired.now),
                        policy(scope_id, state.tenant_id),
                    ).require_accepted(other.actor, UUID(view["recording_id"]), UUID(view["id"]))

            with pytest.raises(StorageError, match="digest_mismatch"):
                await _store(
                    engine,
                    expired,
                    UUID(view["recording_id"]),
                    changed,
                    storage,
                    now=expired.now,
                )
            assert intent.source_sha256 != hashlib.sha256(changed).hexdigest()
        finally:
            await engine.dispose()

    run(exercise())


def test_expired_uncommitted_source_stays_denied(postgres_harness: Any) -> None:
    async def exercise() -> None:
        engine = create_async_engine(postgres_harness.url)
        try:
            state = await seed(engine)
            scope_id = await seed_budget(engine)
            await add_allowance(engine, state.tenant_id, state.person_id, seconds=900)
            source = b"synthetic uncommitted source"
            _, view = await _prepare(engine, state, scope_id, source, key="uncommitted-quote")
            await _accept(engine, state, scope_id, view)
            expired = replace(state, now=state.now + timedelta(minutes=31))

            async with AsyncSession(engine) as database, database.begin():
                intake = ConversationIntake(
                    ConversationApplication(database, clock=lambda: expired.now),
                    policy(scope_id, state.tenant_id),
                )
                with pytest.raises(ConversationConflict, match="quote expired"):
                    await intake.require_accepted(
                        expired.actor, UUID(view["recording_id"]), UUID(view["id"])
                    )

        finally:
            await engine.dispose()

    run(exercise())


def test_committed_replay_preserves_permission_revocation_and_deletion(
    postgres_harness: Any, tmp_path: Path
) -> None:
    async def exercise() -> None:
        engine = create_async_engine(postgres_harness.url)
        storage = PrivateLocalRecordingStorage(tmp_path / "source-store")
        try:
            state = await seed(engine)
            scope_id = await seed_budget(engine)
            await add_allowance(engine, state.tenant_id, state.person_id, seconds=900)
            source = b"synthetic permission replay source"
            _, view = await _prepare(engine, state, scope_id, source, key="permission-quote")
            await _accept(engine, state, scope_id, view)
            await _store(engine, state, UUID(view["recording_id"]), source, storage)
            expired = replace(state, now=state.now + timedelta(minutes=31))
            permission_expired = replace(state, now=state.now + timedelta(days=8))

            async with AsyncSession(engine) as database, database.begin():
                await database.execute(
                    update(IdentitySession)
                    .where(IdentitySession.id == state.session_id)
                    .values(expires_at=permission_expired.now + timedelta(days=1))
                )
                with pytest.raises(ConversationDenied, match="permission"):
                    await ConversationIntake(
                        ConversationApplication(database, clock=lambda: permission_expired.now),
                        policy(scope_id, state.tenant_id),
                    ).require_accepted(
                        permission_expired.actor, UUID(view["recording_id"]), UUID(view["id"])
                    )

            retention_expired = replace(state, now=state.now + timedelta(days=2))
            async with AsyncSession(engine) as database, database.begin():
                recording = await database.get(ConversationRecording, UUID(view["recording_id"]))
                assert recording is not None
                await database.execute(
                    update(IdentitySession)
                    .where(IdentitySession.id == state.session_id)
                    .values(expires_at=retention_expired.now + timedelta(days=1))
                )
                await database.execute(
                    update(ConversationPermission)
                    .where(ConversationPermission.id == recording.permission_id)
                    .values(retention_until=state.now + timedelta(days=1))
                )
                permission = await database.get(ConversationPermission, recording.permission_id)
                assert permission is not None
                assert permission.expires_at > retention_expired.now
                assert permission.retention_until <= retention_expired.now
                with pytest.raises(ConversationDenied, match="permission"):
                    await ConversationIntake(
                        ConversationApplication(database, clock=lambda: retention_expired.now),
                        policy(scope_id, state.tenant_id),
                    ).require_accepted(retention_expired.actor, recording.id, UUID(view["id"]))

            async with AsyncSession(engine) as database, database.begin():
                recording = await database.get(ConversationRecording, UUID(view["recording_id"]))
                assert recording is not None
                await database.execute(
                    update(ConversationPermission)
                    .where(ConversationPermission.id == recording.permission_id)
                    .values(revoked_at=expired.now)
                )
                with pytest.raises(ConversationDenied, match="permission"):
                    await ConversationIntake(
                        ConversationApplication(database, clock=lambda: expired.now),
                        policy(scope_id, state.tenant_id),
                    ).require_accepted(expired.actor, recording.id, UUID(view["id"]))

            # A separate committed recording proves deletion remains a fence,
            # even though its quote is otherwise replayable after expiry.
            source_two = b"synthetic deleted replay source"
            _, view_two = await _prepare(engine, state, scope_id, source_two, key="deletion-quote")
            await _accept(engine, state, scope_id, view_two)
            await _store(engine, state, UUID(view_two["recording_id"]), source_two, storage)
            async with AsyncSession(engine) as database, database.begin():
                application = ConversationApplication(database, clock=lambda: expired.now)
                await application.request_deletion(
                    expired.actor, UUID(view_two["recording_id"]), key="delete-replay-source"
                )
            async with AsyncSession(engine) as database, database.begin():
                with pytest.raises(ConversationConflict, match="quote expired"):
                    await ConversationIntake(
                        ConversationApplication(database, clock=lambda: expired.now),
                        policy(scope_id, state.tenant_id),
                    ).require_accepted(
                        expired.actor, UUID(view_two["recording_id"]), UUID(view_two["id"])
                    )
        finally:
            await engine.dispose()

    run(exercise())


async def _http_app(
    engine: Any,
    state: Any,
    scope_id: UUID,
    tmp_path: Path,
    now: list[Any],
) -> tuple[FastAPI, async_sessionmaker[AsyncSession], str, Settings]:
    sessions = async_sessionmaker(engine, expire_on_commit=False)
    token = secrets.token_urlsafe(32)
    pepper = secrets.token_urlsafe(32)
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
    async with sessions() as database, database.begin():
        await database.execute(
            update(Person)
            .where(Person.id == state.person_id)
            .values(email=f"replay-{state.person_id.hex}@example.test")
        )
        await database.execute(
            update(IdentitySession)
            .where(IdentitySession.id == state.session_id)
            .values(token_hash=hmac.new(pepper.encode(), token.encode(), hashlib.sha256).digest())
        )
    runtime = ConversationIntakeRuntime(
        policy(scope_id, state.tenant_id),
        PrivateLocalRecordingStorage(tmp_path / "http-source-store"),
        PrivateLocalRecordingStorage(tmp_path / "http-source-scratch"),
    )
    app = FastAPI()
    register_problem_handlers(app)
    require_actor = install_identity_http(app, settings=settings, sessions=sessions)
    install_conversation_http(
        app, settings=settings, require_actor=require_actor, intake_runtime=runtime
    )
    return app, sessions, token, settings


def test_http_replay_is_authenticated_and_keeps_fresh_upload_expiry(
    postgres_harness: Any, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    async def exercise() -> None:
        engine = create_async_engine(postgres_harness.url)
        now = [None]
        try:
            state = await seed(engine)
            scope_id = await seed_budget(engine)
            await add_allowance(engine, state.tenant_id, state.person_id, seconds=900)
            now[0] = state.now
            real_init = ConversationApplication.__init__

            def controlled_init(self: Any, database: Any, *, clock: Any = None) -> None:
                real_init(self, database, clock=clock or (lambda: now[0]))

            monkeypatch.setattr(ConversationApplication, "__init__", controlled_init)
            app, sessions, token, settings = await _http_app(engine, state, scope_id, tmp_path, now)
            source = b"synthetic HTTP committed replay"
            changed = source[:-1] + b"!"
            cookie = {"Cookie": f"{settings.session_cookie_name}={token}"}
            base = {**cookie, "Origin": "http://learner.test"}
            intent = _intent(source).model_dump(mode="json")
            async with httpx.AsyncClient(
                transport=httpx.ASGITransport(app=app), base_url="http://learner.test"
            ) as client:
                quote_response = await client.post(
                    "/v1/conversation/intake/quote",
                    headers={**base, "Idempotency-Key": "http-replay-quote"},
                    json=intent,
                )
                assert quote_response.status_code == 201, quote_response.text
                quote = quote_response.json()
                approved = await client.post(
                    f"/v1/conversation/quotes/{quote['id']}/approve",
                    headers=base,
                    json={
                        "quote_fingerprint": quote["quote_fingerprint"],
                        "privacy_revision": quote["privacy_revision"],
                        "accepted": True,
                    },
                )
                assert approved.status_code == 200, approved.text
                upload_headers = {
                    **base,
                    "Content-Type": "application/octet-stream",
                    "Content-Length": str(len(source)),
                    "X-Analysis-Quote": quote["id"],
                }
                first = await client.put(
                    f"/v1/conversation/recordings/{quote['recording_id']}/source",
                    headers=upload_headers,
                    content=source,
                )
                assert first.status_code == 200, first.text
                now[0] = state.now + timedelta(minutes=31)
                replay = await client.put(
                    f"/v1/conversation/recordings/{quote['recording_id']}/source",
                    headers=upload_headers,
                    content=source,
                )
                assert replay.status_code == 200, replay.text
                changed_upload = await client.put(
                    f"/v1/conversation/recordings/{quote['recording_id']}/source",
                    headers=upload_headers,
                    content=changed,
                )
                assert changed_upload.status_code == 422, changed_upload.text

                other_session = uuid4()
                other_token = secrets.token_urlsafe(32)
                async with sessions() as database, database.begin():
                    database.add(
                        IdentitySession(
                            id=other_session,
                            person_id=state.person_id,
                            selected_tenant_id=state.tenant_id,
                            token_hash=hmac.new(
                                settings.session_token_pepper.get_secret_value().encode(),
                                other_token.encode(),
                                hashlib.sha256,
                            ).digest(),
                            expires_at=now[0] + timedelta(days=1),
                        )
                    )
                wrong = await client.put(
                    f"/v1/conversation/recordings/{quote['recording_id']}/source",
                    headers={
                        **upload_headers,
                        "Cookie": f"{settings.session_cookie_name}={other_token}",
                    },
                    content=source,
                )
                assert wrong.status_code == 403, wrong.text

                # A newly approved but still-uncommitted recording keeps the
                # original quote-expiry denial at the same wall-clock instant.
                now[0] = state.now
                second_source = b"synthetic HTTP uncommitted replay"
                second_quote = await client.post(
                    "/v1/conversation/intake/quote",
                    headers={**base, "Idempotency-Key": "http-uncommitted-quote"},
                    json=_intent(second_source).model_dump(mode="json"),
                )
                assert second_quote.status_code == 201, second_quote.text
                second = second_quote.json()
                second_approved = await client.post(
                    f"/v1/conversation/quotes/{second['id']}/approve",
                    headers=base,
                    json={
                        "quote_fingerprint": second["quote_fingerprint"],
                        "privacy_revision": second["privacy_revision"],
                        "accepted": True,
                    },
                )
                assert second_approved.status_code == 200, second_approved.text
                now[0] = state.now + timedelta(minutes=31)
                expired = await client.put(
                    f"/v1/conversation/recordings/{second['recording_id']}/source",
                    headers={
                        **base,
                        "Content-Type": "application/octet-stream",
                        "Content-Length": str(len(second_source)),
                        "X-Analysis-Quote": second["id"],
                    },
                    content=second_source,
                )
                assert expired.status_code == 409, expired.text
        finally:
            await engine.dispose()

    run(exercise())
