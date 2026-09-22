"""Actual PostgreSQL guest isolation, atomic quota, claim and immutable receipts."""

from __future__ import annotations

import asyncio
import hashlib
import hmac
import secrets
from datetime import timedelta
from urllib.parse import parse_qs, urlencode, urlsplit
from uuid import uuid4

import httpx
import pytest
from alembic.autogenerate import compare_metadata
from alembic.migration import MigrationContext
from fastapi import FastAPI
from pydantic import SecretStr
from sqlalchemy import delete, func, select, update
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from ac_platform.application.settings import Settings
from ac_platform.conversation_intelligence.acquisition_challenge import UploadChallenge
from ac_platform.conversation_intelligence.acquisition_models import (
    ConversationAcquisitionSettlement,
    ConversationAcquisitionUsage,
    ConversationVisitor,
    ConversationVisitorClaim,
)
from ac_platform.conversation_intelligence.acquisition_sessions import (
    AcquisitionSessions,
    MeasuredSource,
)
from ac_platform.conversation_intelligence.application import (
    ConversationApplication,
    ConversationConflict,
    ConversationDenied,
    ConversationError,
)
from ac_platform.db.models import model_metadata
from ac_platform.http.auth import install_identity_http
from ac_platform.http.conversation_acquisition import install_acquisition_http
from ac_platform.http.problem import register_problem_handlers
from ac_platform.identity.models import Person
from ac_platform.identity.models import Session as IdentitySession
from ac_platform.identity.services import VerifiedProviderAssertion
from tests.database.test_conversation_postgresql import (
    application,
    run,
    seed,
    seed_budget,
    seed_run_intent,
)
from tests.database.test_conversation_postgresql import postgres_harness as _postgres_harness


@pytest.fixture(scope="module")
def postgres_harness():
    yield from _postgres_harness.__wrapped__()


def service(database, state, *, now=None, revision="acquisition-v1"):
    return AcquisitionSessions(
        database,
        tenant_id=state.tenant_id,
        policy_revision=revision,
        clock=lambda: now or state.now,
    )


def source(seconds=60):
    return MeasuredSource(uuid4(), uuid4().hex * 2, seconds * 1000, uuid4().hex * 2)


async def issue(engine, state):
    async with AsyncSession(engine) as db, db.begin():
        return await service(db, state).issue()


def test_existing_run_usage_is_preserved_when_guest_claims_account(postgres_harness):
    async def exercise():
        engine = create_async_engine(postgres_harness.url)
        try:
            state = await seed(engine)
            intent = await seed_run_intent(engine, state, await seed_budget(engine))
            async with AsyncSession(engine) as db, db.begin():
                await application(db, state).request_run(state.actor, intent, key="existing-run")
            guest = await issue(engine, state)
            async with AsyncSession(engine) as db, db.begin():
                app = service(db, state)
                await app.reserve(source(3400), token=guest.token)
                await app.claim(guest.token, state.actor)
                assert (await app.allowance(actor=state.actor))["available_seconds"] == 80
                with pytest.raises(
                    ConversationDenied,
                    match="remaining trial minutes are not enough for this recording",
                ):
                    await app.reserve(source(81), actor=state.actor)
                last = await app.reserve(source(80), actor=state.actor)
                assert (await app.allowance(actor=state.actor))["available_seconds"] == 0
                # Confirmed no-work releases only its own reservation. The
                # existing queued run's 120 seconds remain committed.
                await app.settle(last, charged_seconds=0, receipt_sha256="a" * 64, no_work=True)
                assert (await app.allowance(actor=state.actor))["available_seconds"] == 80
        finally:
            await engine.dispose()

    run(exercise())


def test_existing_upload_cannot_bypass_claimed_guest_minutes(postgres_harness):
    async def exercise():
        engine = create_async_engine(postgres_harness.url)
        try:
            state = await seed(engine)
            intent = await seed_run_intent(engine, state, await seed_budget(engine))
            guest = await issue(engine, state)
            async with AsyncSession(engine) as db, db.begin():
                app = service(db, state)
                await app.reserve(source(3500), token=guest.token)
                await app.claim(guest.token, state.actor)
            async with AsyncSession(engine) as db, db.begin():
                # The existing fixture has 180 untouched seconds and would
                # accept this 120-second job without the combined allowance.
                with pytest.raises(
                    ConversationDenied,
                    match="remaining trial minutes are not enough for this recording",
                ):
                    await application(db, state).request_run(
                        state.actor, intent, key="must-not-enqueue"
                    )
                assert (await service(db, state).allowance(actor=state.actor))[
                    "available_seconds"
                ] == 100
        finally:
            await engine.dispose()

    run(exercise())


def test_existing_and_acquisition_uploads_cannot_race_two_pools(postgres_harness):
    async def exercise():
        engine = create_async_engine(postgres_harness.url)
        try:
            state = await seed(engine)
            intent = await seed_run_intent(engine, state, await seed_budget(engine))
            guest = await issue(engine, state)
            async with AsyncSession(engine) as db, db.begin():
                app = service(db, state)
                await app.reserve(source(3400), token=guest.token)
                await app.claim(guest.token, state.actor)

            async def existing_upload():
                async with AsyncSession(engine) as db, db.begin():
                    return await application(db, state).request_run(
                        state.actor, intent, key="legacy-race"
                    )

            async def acquisition_upload():
                async with AsyncSession(engine) as db, db.begin():
                    return await service(db, state).reserve(source(100), actor=state.actor)

            results = await asyncio.wait_for(
                asyncio.gather(existing_upload(), acquisition_upload(), return_exceptions=True),
                timeout=15,
            )
            assert sum(isinstance(item, ConversationDenied) for item in results) == 1
            assert not any(isinstance(item, DBAPIError) for item in results)
            async with AsyncSession(engine) as db, db.begin():
                assert (await service(db, state).allowance(actor=state.actor))[
                    "available_seconds"
                ] in {80, 100}
        finally:
            await engine.dispose()

    run(exercise())


def test_forward_migration_matches_registry_and_guests_are_not_people(postgres_harness):
    with postgres_harness.connect() as connection:
        assert compare_metadata(MigrationContext.configure(connection), model_metadata()) == []

    async def exercise():
        engine = create_async_engine(postgres_harness.url)
        try:
            state = await seed(engine)
            async with AsyncSession(engine) as db:
                people_before = await db.scalar(select(func.count()).select_from(Person))
            guest = await issue(engine, state)
            assert guest.token not in repr(guest)
            async with AsyncSession(engine) as db, db.begin():
                row = await db.get(ConversationVisitor, guest.visitor_id)
                assert row.token_hash == hashlib.sha256(guest.token.encode()).digest()
                assert row.token_hash != guest.token.encode()
                assert await db.scalar(select(func.count()).select_from(Person)) == people_before
                assert (await service(db, state).allowance(token=guest.token))[
                    "available_seconds"
                ] == 3600
        finally:
            await engine.dispose()

    run(exercise())


def test_reduced_trial_preserves_historical_usage_and_same_source_replay(
    postgres_harness, monkeypatch
):
    async def exercise():
        engine = create_async_engine(postgres_harness.url)
        try:
            state = await seed(engine)
            guest = await issue(engine, state)
            original_source = source(4000)
            async with AsyncSession(engine) as db, db.begin():
                app = service(db, state)
                with monkeypatch.context() as historical:
                    historical.setattr(
                        "ac_platform.conversation_intelligence.acquisition_sessions.ALLOWANCE_SECONDS",
                        6000,
                    )
                    original_usage = await app.reserve(original_source, token=guest.token)
            async with AsyncSession(engine) as db, db.begin():
                app = service(db, state)
                assert await app.allowance(token=guest.token) == {
                    "allowance_seconds": 3600,
                    "committed_seconds": 4000,
                    "available_seconds": 0,
                }
                assert await app.reserve(original_source, token=guest.token) == original_usage
                await app.claim(guest.token, state.actor)
                assert await app.reserve(original_source, actor=state.actor) == original_usage
                assert (await app.allowance(actor=state.actor))["committed_seconds"] == 4000
                with pytest.raises(
                    ConversationDenied,
                    match="remaining trial minutes are not enough for this recording",
                ):
                    await app.reserve(source(1), actor=state.actor)
                await app.settle(original_usage, charged_seconds=4000, receipt_sha256="d" * 64)
                assert (await app.allowance(actor=state.actor))["available_seconds"] == 0
        finally:
            await engine.dispose()

    run(exercise())


def test_claim_preserves_guest_and_account_usage_and_replay(postgres_harness):
    async def exercise():
        engine = create_async_engine(postgres_harness.url)
        try:
            state = await seed(engine)
            guest = await issue(engine, state)
            guest_source = source(1200)
            async with AsyncSession(engine) as db, db.begin():
                app = service(db, state)
                guest_usage = await app.reserve(guest_source, token=guest.token)
                await app.reserve(source(1800), actor=state.actor)
                await app.claim(guest.token, state.actor)
                assert await app.claim(guest.token, state.actor) == guest.visitor_id
                assert await app.reserve(guest_source, actor=state.actor) == guest_usage
                allowance = await app.allowance(actor=state.actor)
                assert allowance["committed_seconds"] == 3000
                assert allowance["available_seconds"] == 600
                assert await app.allowance(token=guest.token, actor=state.actor) == allowance
                with pytest.raises(ConversationDenied):
                    await app.allowance(token=guest.token)
                with pytest.raises(
                    ConversationDenied,
                    match="remaining trial minutes are not enough for this recording",
                ):
                    await app.reserve(source(601), actor=state.actor)
            # A different browser and a policy revision never grant another 60 minutes.
            second = await issue(engine, state)
            async with AsyncSession(engine) as db, db.begin():
                app = service(db, state, revision="acquisition-v2")
                await app.reserve(source(120), token=second.token)
                await app.claim(second.token, state.actor)
                assert (await app.allowance(actor=state.actor))["available_seconds"] == 480
        finally:
            await engine.dispose()

    run(exercise())


def test_concurrent_tabs_cannot_overbook_guest_allowance(postgres_harness):
    async def exercise():
        engine = create_async_engine(postgres_harness.url)
        try:
            state = await seed(engine)
            guest = await issue(engine, state)

            async def reserve():
                async with AsyncSession(engine) as db, db.begin():
                    return await service(db, state).reserve(source(2400), token=guest.token)

            results = await asyncio.gather(reserve(), reserve(), return_exceptions=True)
            assert sum(isinstance(item, ConversationDenied) for item in results) == 1
            assert not any(isinstance(item, DBAPIError) for item in results)
            async with AsyncSession(engine) as db, db.begin():
                assert (await service(db, state).allowance(token=guest.token))[
                    "available_seconds"
                ] == 1200
        finally:
            await engine.dispose()

    run(exercise())


def test_claim_race_has_one_owner_and_cannot_reassign(postgres_harness):
    async def exercise():
        engine = create_async_engine(postgres_harness.url)
        try:
            first = await seed(engine)
            second = await seed(engine, tenant_id=first.tenant_id)
            guest = await issue(engine, first)

            async def claim(state):
                async with AsyncSession(engine) as db, db.begin():
                    await service(db, state).claim(guest.token, state.actor)
                return state.person_id

            results = await asyncio.gather(claim(first), claim(second), return_exceptions=True)
            assert sum(isinstance(item, ConversationDenied) for item in results) == 1
            winner = first if results[0] == first.person_id else second
            loser = second if winner is first else first
            async with AsyncSession(engine) as db, db.begin():
                claim_row = await db.get(ConversationVisitorClaim, guest.visitor_id)
                assert claim_row.person_id == winner.person_id
                with pytest.raises(ConversationDenied):
                    await service(db, loser).allowance(token=guest.token, actor=loser.actor)
        finally:
            await engine.dispose()

    run(exercise())


@pytest.mark.parametrize("command", ["claim", "reserve"])
def test_authenticated_requests_keep_identity_lock_order(postgres_harness, monkeypatch, command):
    """A request already admitted by HTTP cannot deadlock a direct command."""

    async def exercise():
        engine = create_async_engine(postgres_harness.url)
        try:
            state = await seed(engine)
            guest = await issue(engine, state)
            identity_locked, competing_admission = asyncio.Event(), asyncio.Event()
            original_admit = ConversationApplication.admit

            async def observed_admit(app, actor):
                if asyncio.current_task().get_name() == "competing-acquisition":
                    competing_admission.set()
                return await original_admit(app, actor)

            monkeypatch.setattr(ConversationApplication, "admit", observed_admit)

            async def http_request():
                async with AsyncSession(engine) as db, db.begin():
                    await original_admit(
                        ConversationApplication(db, clock=lambda: state.now), state.actor
                    )
                    identity_locked.set()
                    await competing_admission.wait()
                    return await service(db, state).claim(guest.token, state.actor)

            async def competing_request():
                await identity_locked.wait()
                async with AsyncSession(engine) as db, db.begin():
                    app = service(db, state)
                    if command == "claim":
                        return await app.claim(guest.token, state.actor)
                    return await app.reserve(source(30), actor=state.actor)

            await asyncio.wait_for(
                asyncio.gather(
                    asyncio.create_task(http_request()),
                    asyncio.create_task(competing_request(), name="competing-acquisition"),
                ),
                timeout=8,
            )
            async with AsyncSession(engine) as db, db.begin():
                assert (
                    await db.get(ConversationVisitorClaim, guest.visitor_id)
                ).person_id == state.person_id
                assert (await service(db, state).allowance(actor=state.actor))[
                    "committed_seconds"
                ] == (30 if command == "reserve" else 0)
        finally:
            await engine.dispose()

    run(exercise())


def test_token_expiry_revocation_tenant_and_identity_checks(postgres_harness):
    async def exercise():
        engine = create_async_engine(postgres_harness.url)
        try:
            state, foreign = await seed(engine), await seed(engine)
            guest = await issue(engine, state)
            async with AsyncSession(engine) as db, db.begin():
                with pytest.raises(ConversationDenied):
                    await service(db, foreign).allowance(token=guest.token)
                with pytest.raises(ConversationDenied):
                    await service(db, state).claim(guest.token, foreign.actor)
                with pytest.raises(ConversationDenied):
                    await service(db, state, now=state.now + timedelta(days=1)).allowance(
                        token=guest.token
                    )
                with pytest.raises(ConversationDenied):
                    await service(db, state).allowance(token=uuid4().hex)
                await db.execute(
                    update(Person)
                    .where(Person.id == state.person_id)
                    .values(email_verified_at=None)
                )
                with pytest.raises(ConversationDenied):
                    await service(db, state).claim(guest.token, state.actor)
                # Password registration doesn't need to interrupt its existing guest preview.
                assert (await service(db, state).allowance(token=guest.token))[
                    "available_seconds"
                ] == 3600
                await service(db, state).revoke(guest.token)
                with pytest.raises(ConversationDenied):
                    await service(db, state).allowance(token=guest.token)
        finally:
            await engine.dispose()

    run(exercise())


def test_settlement_is_idempotent_and_history_is_immutable(postgres_harness):
    async def exercise():
        engine = create_async_engine(postgres_harness.url)
        try:
            state = await seed(engine)
            guest = await issue(engine, state)
            async with AsyncSession(engine) as db, db.begin():
                app = service(db, state)
                usage = await app.reserve(source(100), token=guest.token)
                with pytest.raises(ConversationError):
                    await app.settle(usage, charged_seconds=0, receipt_sha256="d" * 64)
                await app.settle(usage, charged_seconds=100, receipt_sha256="d" * 64)
                await app.settle(usage, charged_seconds=100, receipt_sha256="d" * 64)
                with pytest.raises(ConversationConflict):
                    await app.settle(usage, charged_seconds=100, receipt_sha256="e" * 64)
                cancelled = await app.reserve(source(200), token=guest.token)
                assert (await app.allowance(token=guest.token))["committed_seconds"] == 300
                await app.settle(
                    cancelled, charged_seconds=0, receipt_sha256="f" * 64, no_work=True
                )
                assert (await app.allowance(token=guest.token))["committed_seconds"] == 100
                await app.claim(guest.token, state.actor)
            for model, predicate in (
                (ConversationAcquisitionUsage, ConversationAcquisitionUsage.id == usage),
                (
                    ConversationAcquisitionSettlement,
                    ConversationAcquisitionSettlement.usage_id == usage,
                ),
                (ConversationVisitorClaim, ConversationVisitorClaim.visitor_id == guest.visitor_id),
            ):
                async with AsyncSession(engine) as db:
                    with pytest.raises(DBAPIError):
                        async with db.begin():
                            await db.execute(delete(model).where(predicate))
        finally:
            await engine.dispose()

    run(exercise())


def test_replay_cannot_change_source_or_be_used_by_another_visitor(postgres_harness):
    async def exercise():
        engine = create_async_engine(postgres_harness.url)
        try:
            state = await seed(engine)
            guest, other = await issue(engine, state), await issue(engine, state)
            original = source(10)
            async with AsyncSession(engine) as db, db.begin():
                app = service(db, state)
                identifier = await app.reserve(original, token=guest.token)
                assert await app.reserve(original, token=guest.token) == identifier
                with pytest.raises(ConversationDenied):
                    await app.reserve(original, token=other.token)
                changed = MeasuredSource(
                    original.submission_id,
                    "a" * 64,
                    original.duration_ms,
                    original.duration_evidence_sha256,
                )
                with pytest.raises(ConversationConflict):
                    await app.reserve(changed, token=guest.token)
        finally:
            await engine.dispose()

    run(exercise())


def test_http_cookie_claim_and_boundary_use_real_identity_and_postgres(
    postgres_harness, monkeypatch
):
    class HttpsTestSettings(Settings):
        @property
        def secure_cookies(self) -> bool:
            return True

    async def exercise():
        engine = create_async_engine(postgres_harness.url)
        try:
            state = await seed(engine)
            sessions = async_sessionmaker(engine, expire_on_commit=False)
            pepper, identity_token = secrets.token_urlsafe(32), secrets.token_urlsafe(32)
            settings = HttpsTestSettings(
                _env_file=None,
                environment="test",
                public_app_url="https://learner.example.test",
                admin_app_url="https://admin.example.test",
                coach_app_url="https://coach.example.test",
                api_url="https://api.example.test",
                sales_xray_app_url="https://salesxray.example.test",
                public_learner_tenant_id=state.tenant_id,
                operations_tenant_id=uuid4(),
                session_token_pepper=SecretStr(pepper),
            )
            async with sessions() as db, db.begin():
                await db.execute(
                    update(Person)
                    .where(Person.id == state.person_id)
                    .values(email=f"acquisition-{state.person_id.hex}@example.test")
                )
                await db.execute(
                    update(IdentitySession)
                    .where(IdentitySession.id == state.session_id)
                    .values(
                        token_hash=hmac.new(
                            pepper.encode(), identity_token.encode(), hashlib.sha256
                        ).digest()
                    )
                )
            verifier = UploadChallenge(
                secret=SecretStr(secrets.token_urlsafe(32)), hostname="salesxray.example.test"
            )
            checks = []

            async def verify(token):
                checks.append(token)
                if token != "synthetic-challenge":  # noqa: S105 - non-secret verifier stub input
                    raise ConversationDenied("The upload check was rejected.")

            monkeypatch.setattr(verifier, "verify", verify)
            app = FastAPI()
            register_problem_handlers(app)
            require_actor = install_identity_http(app, settings=settings, sessions=sessions)
            install_acquisition_http(
                app,
                settings=settings,
                sessions=sessions,
                require_actor=require_actor,
                factory=lambda db: service(db, state),
                challenge=verifier,
            )
            origin = "https://salesxray.example.test"
            route = "/v1/conversation/acquisition"
            async with httpx.AsyncClient(
                transport=httpx.ASGITransport(app=app), base_url=origin
            ) as client:
                response = await client.post(
                    route + "/session",
                    json={"challenge_token": "rejected"},
                    headers={"Origin": origin},
                )
                assert response.status_code == 403
                assert not client.cookies
                start = await client.post(
                    route + "/session",
                    json={"challenge_token": "synthetic-challenge"},
                    headers={"Origin": origin},
                )
                assert start.status_code == 201
                cookie = start.headers["set-cookie"]
                assert "Secure" in cookie and "HttpOnly" in cookie and "SameSite=lax" in cookie
                assert "Domain=" not in cookie and "Path=/" in cookie
                visitor_token = client.cookies["__Host-ac_xray_guest"]
                assert visitor_token not in start.text
                assert start.headers["cache-control"] == "private, no-store"
                async with sessions() as db, db.begin():
                    await service(db, state).reserve(source(61), token=visitor_token)
                repeat = await client.post(
                    route + "/session",
                    json={"challenge_token": "synthetic-challenge"},
                    headers={"Origin": origin},
                )
                assert repeat.status_code == 200
                assert repeat.json()["allowance"]["available_seconds"] == 3539
                assert checks == ["rejected", "synthetic-challenge"]
                read = await client.get(route + "/session")
                assert read.status_code == 200
                assert read.json()["allowance"]["available_seconds"] == 3539
                # A malformed-but-shaped account token cannot fall back to
                # the otherwise valid guest bearer.
                client.cookies.set(
                    settings.session_cookie_name,
                    secrets.token_urlsafe(32),
                    domain="salesxray.example.test",
                    path="/",
                )
                invalid_account = await client.get(route + "/session")
                assert invalid_account.status_code == 401
                client.cookies.delete(settings.session_cookie_name)
                denial = await client.post(
                    route + "/session",
                    json={"challenge_token": "synthetic-challenge"},
                    headers={"Origin": "https://learner.example.test"},
                )
                assert denial.status_code == 403 and "no-store" in denial.headers["cache-control"]
                duplicate = await client.get(
                    route + "/session",
                    headers={
                        "Cookie": (
                            f"__Host-ac_xray_guest={visitor_token}; "
                            f"__Host-ac_xray_guest={visitor_token}"
                        )
                    },
                )
                assert duplicate.status_code == 401
                overlong = await client.post(
                    route + "/session",
                    json={"challenge_token": "DO_NOT_ECHO" * 400},
                    headers={"Origin": origin},
                )
                assert overlong.status_code == 413 and "DO_NOT_ECHO" not in overlong.text
                extra = await client.post(
                    route + "/session",
                    json={"challenge_token": "synthetic-challenge", "tenant_id": str(uuid4())},
                    headers={"Origin": origin},
                )
                assert extra.status_code == 422
                client.cookies.set(
                    settings.session_cookie_name,
                    identity_token,
                    domain="salesxray.example.test",
                    path="/",
                )
                pending_claim = await client.get(route + "/session")
                assert pending_claim.status_code == 200, pending_claim.text
                assert pending_claim.json()["state"] == "claim_required"
                assert pending_claim.json()["allowance"]["available_seconds"] == 3539
                claimed = await client.post(route + "/claim", headers={"Origin": origin})
                assert claimed.status_code == 200, claimed.text
                assert claimed.json()["allowance"]["available_seconds"] == 3539
                assert "__Host-ac_xray_guest" not in client.cookies
                account_only = await client.get(route + "/session")
                assert account_only.status_code == 200
                assert account_only.json()["state"] == "account"
                assert account_only.json()["allowance"]["available_seconds"] == 3539
                async with sessions() as db:
                    visitor_count_before = await db.scalar(
                        select(func.count()).select_from(ConversationVisitor)
                    )
                # A signed-in browser without a guest cookie reads the
                # account ledger; GET never issues an unclaimed visitor.
                assert visitor_count_before is not None
                client.cookies.set(
                    "__Host-ac_xray_guest",
                    visitor_token,
                    domain="salesxray.example.test",
                    path="/",
                )
                claimed_cookie = await client.get(route + "/session")
                assert claimed_cookie.status_code == 200, claimed_cookie.text
                assert claimed_cookie.json()["state"] == "account"
                assert claimed_cookie.json()["allowance"]["available_seconds"] == 3539
                async with sessions() as db:
                    visitor_count_after = await db.scalar(
                        select(func.count()).select_from(ConversationVisitor)
                    )
                assert visitor_count_after == visitor_count_before
                client.cookies.clear()
                client.cookies.set(
                    "__Host-ac_xray_guest",
                    visitor_token,
                    domain="salesxray.example.test",
                    path="/",
                )
                old_cookie = await client.get(route + "/session")
                assert old_cookie.status_code == 403
        finally:
            await engine.dispose()

    run(exercise())


@pytest.mark.parametrize("verified", [True, False])
def test_google_entry_creates_one_canonical_learner_and_retains_guest_usage(
    postgres_harness, verified
):
    """Real HTTP/identity/PG with a synthetic provider, never a Google network call."""

    async def exercise():
        engine = create_async_engine(postgres_harness.url)
        try:
            state = await seed(engine)
            sessions = async_sessionmaker(engine, expire_on_commit=False)
            origin = "https://salesxray.example.test"
            provider_subject = uuid4().hex

            class SyntheticProvider:
                audience = "synthetic-google-acquisition"

                def authorization_url(self, transaction, *, redirect_uri):
                    return origin + "/synthetic-provider?" + urlencode({"state": transaction.state})

                async def exchange_code(self, code, transaction, *, callback_state, redirect_uri):
                    assert code == "synthetic-code"
                    assert redirect_uri == origin + "/v1/auth/google/callback"
                    return VerifiedProviderAssertion(
                        issuer="https://accounts.google.com",
                        subject=provider_subject,
                        audience=self.audience,
                        state=callback_state,
                        nonce=transaction.nonce,
                        authorization_type=transaction.authorization_type,
                        email=f"{provider_subject}@example.test",
                        email_verified=verified,
                    )

            settings = Settings(
                _env_file=None,
                environment="test",
                public_app_url="https://learner.example.test",
                admin_app_url="https://admin.example.test",
                coach_app_url="https://coach.example.test",
                api_url="https://api.example.test",
                sales_xray_app_url=origin,
                public_learner_tenant_id=state.tenant_id,
                operations_tenant_id=uuid4(),
                session_token_pepper=SecretStr(secrets.token_urlsafe(32)),
                oauth_transaction_secret=SecretStr(secrets.token_urlsafe(32)),
                learner_consent_version="synthetic-acquisition-consent-v1",
            )
            app = FastAPI()
            register_problem_handlers(app)
            require_actor = install_identity_http(
                app, settings=settings, sessions=sessions, provider=SyntheticProvider()
            )
            install_acquisition_http(
                app,
                settings=settings,
                sessions=sessions,
                require_actor=require_actor,
                factory=lambda db: service(db, state),
                challenge=UploadChallenge(
                    secret=SecretStr(secrets.token_urlsafe(32)), hostname="salesxray.example.test"
                ),
            )
            guest = await issue(engine, state)
            async with sessions() as db, db.begin():
                await service(db, state).reserve(source(124), token=guest.token)
                before = await db.scalar(select(func.count()).select_from(Person))

            async with httpx.AsyncClient(
                transport=httpx.ASGITransport(app=app), base_url=origin
            ) as client:
                client.cookies.set(
                    "ac_xray_guest", guest.token, domain="salesxray.example.test", path="/"
                )
                person_id = None
                for _ in range(2 if verified else 1):
                    start = await client.get(
                        "/v1/auth/google/start",
                        params={
                            "action": "authenticate",
                            "surface": "sales_xray",
                            "consent": "true",
                            "consent_version": settings.learner_consent_version,
                            "return_path": "/?report=synthetic-owned-report&continue=claim",
                        },
                    )
                    assert start.status_code == 303
                    callback_state = parse_qs(urlsplit(start.headers["location"]).query)["state"][0]
                    callback = await client.get(
                        "/v1/auth/google/callback",
                        params={"state": callback_state, "code": "synthetic-code"},
                    )
                    if not verified:
                        assert callback.status_code == 401, callback.text
                        assert settings.session_cookie_name not in client.cookies
                        async with sessions() as db:
                            assert (
                                await db.scalar(select(func.count()).select_from(Person)) == before
                            )
                        return
                    assert callback.status_code == 303, callback.text
                    assert (
                        callback.headers["location"]
                        == origin + "/?report=synthetic-owned-report&continue=claim"
                    )
                    me = await client.get("/v1/me")
                    assert me.status_code == 200, me.text
                    assert me.json()["selected_tenant_id"] == str(state.tenant_id)
                    assert me.json()["membership_role"] == "learner"
                    if person_id is None:
                        person_id = me.json()["person_id"]
                        claim = await client.post(
                            "/v1/conversation/acquisition/claim", headers={"Origin": origin}
                        )
                        assert claim.status_code == 200, claim.text
                        assert claim.json()["allowance"]["available_seconds"] == 3476
                    else:
                        assert me.json()["person_id"] == person_id
                    async with sessions() as db:
                        assert (
                            await db.scalar(select(func.count()).select_from(Person)) == before + 1
                        )
                    client.cookies.clear()
        finally:
            await engine.dispose()

    run(exercise())
