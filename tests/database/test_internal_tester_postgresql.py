from __future__ import annotations

import hashlib
import hmac
import re
import secrets
from pathlib import Path
from uuid import UUID, uuid4

import httpx
import pytest
from fastapi import FastAPI
from pydantic import SecretStr
from sqlalchemy import update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from ac_platform.application.settings import Settings
from ac_platform.conversation_intelligence.acquisition_challenge import UploadChallenge
from ac_platform.conversation_intelligence.acquisition_sessions import AcquisitionSessions
from ac_platform.conversation_intelligence.activation_contract import InternalTesterApproval
from ac_platform.conversation_intelligence.application import (
    ConversationApplication,
    ConversationConflict,
)
from ac_platform.conversation_intelligence.authority import ConversationAuthority
from ac_platform.conversation_intelligence.contracts import IntakeIntent, QuoteAcceptance, RunIntent
from ac_platform.conversation_intelligence.entitlements import MinuteAccount
from ac_platform.conversation_intelligence.intake import ConversationIntake, IntakePolicy
from ac_platform.conversation_intelligence.internal_tester import (
    InternalTesterPolicy,
)
from ac_platform.conversation_intelligence.internal_tester import (
    tester_rate_limit_resolver as make_tester_rate_limit_resolver,
)
from ac_platform.conversation_intelligence.models import ConversationMinuteAccount
from ac_platform.conversation_intelligence.storage import PrivateLocalRecordingStorage
from ac_platform.http.auth import install_identity_http
from ac_platform.http.conversation_acquisition import install_acquisition_http
from ac_platform.http.problem import register_problem_handlers
from ac_platform.http.rate_limits import (
    InMemoryTokenBucketLimiter,
    RateLimitMiddleware,
    RateLimitRule,
)
from ac_platform.identity.models import Person
from ac_platform.identity.models import Session as IdentitySession
from tests.database.test_conversation_authority_postgresql import _bundle
from tests.database.test_conversation_postgresql import (
    postgres_harness as _postgres_harness,
)
from tests.database.test_conversation_postgresql import (
    run,
    seed,
)


@pytest.fixture
def postgres_harness():
    yield from _postgres_harness.__wrapped__()


def _token_hash(token: str, pepper: str) -> bytes:
    return hmac.new(pepper.encode("utf-8"), token.encode("ascii"), hashlib.sha256).digest()


def test_real_postgres_asgi_tester_identity_allowance_rate_limit_and_revoke(
    postgres_harness, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    async def exercise() -> None:
        engine = create_async_engine(postgres_harness.url)
        try:
            state = await seed(engine)
            neighbor = await seed(engine, tenant_id=state.tenant_id)
            pepper = secrets.token_urlsafe(32)
            tester_token = secrets.token_urlsafe(32)
            neighbor_token = secrets.token_urlsafe(32)
            async with AsyncSession(engine) as database, database.begin():
                await database.execute(
                    update(Person)
                    .where(Person.id == state.person_id)
                    .values(email="admin@authorityclosers.com", email_verified_at=state.now)
                )
                await database.execute(
                    update(IdentitySession)
                    .where(IdentitySession.id == state.session_id)
                    .values(token_hash=_token_hash(tester_token, pepper))
                )
                await database.execute(
                    update(Person)
                    .where(Person.id == neighbor.person_id)
                    .values(email="ordinary@example.com", email_verified_at=neighbor.now)
                )
                await database.execute(
                    update(IdentitySession)
                    .where(IdentitySession.id == neighbor.session_id)
                    .values(token_hash=_token_hash(neighbor_token, pepper))
                )

            source = b"synthetic local audio for tester reservation"
            source_sha256 = hashlib.sha256(source).hexdigest()
            approval = InternalTesterApproval(
                id=uuid4(),
                email="admin@authorityclosers.com",
                authorization_ref="ref:approval:tester-integration-20260915",
                scopes=("account_minutes", "analysis_count", "ip_session_issuance"),
                reason="Approved internal tester exemption",
            )
            finite_bundle = _bundle(
                state,
                source_sha256,
                "a" * 64,
                now_epoch=int(state.now.timestamp()),
            )
            bundle = finite_bundle.model_copy(update={"internal_tester_accounts": (approval,)})
            bundle_box = {"bundle": bundle}
            tester_policy = InternalTesterPolicy(lambda: bundle_box["bundle"], "test")
            authority = ConversationAuthority(
                lambda: bundle_box["bundle"],
                environment="test",
                operations_tenant_id=state.tenant_id,
                tester_policy=tester_policy,
            )
            sessions = async_sessionmaker(engine, expire_on_commit=False)
            learner_origin = "https://learner.example.test"
            sales_origin = "https://salesxray.example.test"
            settings = Settings(
                _env_file=None,
                environment="test",
                public_app_url=learner_origin,
                admin_app_url="https://admin.example.test",
                coach_app_url="https://coach.example.test",
                api_url="https://api.example.test",
                sales_xray_app_url=sales_origin,
                public_learner_tenant_id=state.tenant_id,
                operations_tenant_id=uuid4(),
                session_token_pepper=SecretStr(pepper),
            )

            verifier = UploadChallenge(
                secret=SecretStr(secrets.token_urlsafe(32)),
                hostname="salesxray.example.test",
            )

            async def verify(token: str) -> None:
                assert token == "synthetic-challenge"  # noqa: S105 - synthetic challenge fixture

            monkeypatch.setattr(verifier, "verify", verify)
            app = FastAPI()
            register_problem_handlers(app)
            require_actor = install_identity_http(app, settings=settings, sessions=sessions)
            install_acquisition_http(
                app,
                settings=settings,
                sessions=sessions,
                require_actor=require_actor,
                factory=lambda database: AcquisitionSessions(
                    database,
                    tenant_id=state.tenant_id,
                    policy_revision="tester-integration-v1",
                    clock=lambda: state.now,
                    tester_policy=tester_policy,
                ),
                challenge=verifier,
            )
            limited_app = RateLimitMiddleware(
                app,
                rules=(
                    RateLimitRule(
                        name="conversation-acquisition-session",
                        method="POST",
                        path=re.compile(r"^/v1/conversation/acquisition/session$"),
                        capacity=1,
                        refill_seconds=900,
                    ),
                ),
                limiter=InMemoryTokenBucketLimiter(),
                exemption=make_tester_rate_limit_resolver(
                    settings=settings,
                    sessions=sessions,
                    policy=tester_policy,
                ),
            )
            transport = httpx.ASGITransport(
                app=limited_app,
                client=("127.0.0.1", 43125),
            )
            tester_cookie = {"Cookie": f"{settings.session_cookie_name}={tester_token}"}
            neighbor_cookie = {"Cookie": f"{settings.session_cookie_name}={neighbor_token}"}

            async with httpx.AsyncClient(transport=transport, base_url=learner_origin) as client:
                tester_allowance = await client.get(
                    "/v1/conversation/acquisition/session", headers=tester_cookie
                )
                assert tester_allowance.status_code == 200, tester_allowance.text
                allowance = tester_allowance.json()["allowance"]
                assert allowance["unlimited"] is True

                neighbor_allowance = await client.get(
                    "/v1/conversation/acquisition/session", headers=neighbor_cookie
                )
                assert neighbor_allowance.status_code == 200, neighbor_allowance.text
                assert neighbor_allowance.json()["allowance"].get("unlimited") is not True

            async with httpx.AsyncClient(
                transport=transport, base_url=sales_origin
            ) as tester_client:
                first = await tester_client.post(
                    "/v1/conversation/acquisition/session",
                    json={"challenge_token": "synthetic-challenge"},
                    headers={**tester_cookie, "Origin": sales_origin},
                )
                second = await tester_client.post(
                    "/v1/conversation/acquisition/session",
                    json={"challenge_token": "synthetic-challenge"},
                    headers={**tester_cookie, "Origin": sales_origin},
                )
                assert first.status_code == 201, first.text
                assert second.status_code in {200, 201}, second.text

            async with httpx.AsyncClient(
                transport=transport, base_url=sales_origin
            ) as neighbor_client:
                first = await neighbor_client.post(
                    "/v1/conversation/acquisition/session",
                    json={"challenge_token": "synthetic-challenge"},
                    headers={**neighbor_cookie, "Origin": sales_origin},
                )
                second = await neighbor_client.post(
                    "/v1/conversation/acquisition/session",
                    json={"challenge_token": "synthetic-challenge"},
                    headers={**neighbor_cookie, "Origin": sales_origin},
                )
                assert first.status_code == 201, first.text
                assert second.status_code == 429, second.text

            async with AsyncSession(engine) as database, database.begin():
                await authority.claim_allowance(ConversationApplication(database), state.actor)
            async with AsyncSession(engine) as database:
                minute_row = await database.get(
                    ConversationMinuteAccount,
                    (state.tenant_id, state.person_id),
                )
                assert minute_row is not None
                assert MinuteAccount.from_dict(minute_row.snapshot).unlimited is True

            intake_policy = IntakePolicy(
                budget_scope_id=bundle.budget_scope_id,
                tenant_ids=frozenset({state.tenant_id}),
                authorization_ref=bundle.intake_authorization_ref,
                retention_ref=bundle.intake_retention_ref,
                retention_days=bundle.retention_days,
            )
            first_intent = IntakeIntent(
                source_sha256=source_sha256,
                source_bytes=len(source),
                content_type="audio/wav",
                duration_ms=240_000,
                purpose="internal_analysis",
            )
            async with AsyncSession(engine) as database, database.begin():
                intake = ConversationIntake(
                    ConversationApplication(database, clock=lambda: state.now),
                    intake_policy,
                    authority=authority,
                )
                first_quote = await intake.prepare(
                    state.actor, first_intent, key="tester-reservation-quote"
                )
                await intake.accept(
                    state.actor,
                    UUID(first_quote["id"]),
                    QuoteAcceptance(
                        quote_fingerprint=first_quote["quote_fingerprint"],
                        privacy_revision=first_quote["privacy_revision"],
                        accepted=True,
                    ),
                )

            storage = PrivateLocalRecordingStorage(tmp_path / "tester-source-storage")
            async with AsyncSession(engine) as database, database.begin():
                application = ConversationApplication(database, clock=lambda: state.now)
                await application.store_source(
                    state.actor,
                    UUID(first_quote["recording_id"]),
                    chunks=(source,),
                    storage=storage,
                )
                run_view = await application.request_run(
                    state.actor,
                    RunIntent(
                        recording_id=UUID(first_quote["recording_id"]),
                        source_revision=first_quote["source_revision"],
                        quote_id=UUID(first_quote["id"]),
                        recipe_revision=first_quote["recipe_revision"],
                    ),
                    key="tester-reservation-run",
                )
                assert run_view["state"] == "queued"

            bundle_box["bundle"] = bundle.model_copy(update={"internal_tester_accounts": ()})
            async with AsyncSession(engine) as database, database.begin():
                assert (
                    await tester_policy.for_actor(database, state.actor, "account_minutes") is None
                )
                await authority.claim_allowance(ConversationApplication(database), state.actor)
            async with AsyncSession(engine) as database:
                minute_row = await database.get(
                    ConversationMinuteAccount,
                    (state.tenant_id, state.person_id),
                )
                assert minute_row is not None
                finite = MinuteAccount.from_dict(minute_row.snapshot)
                assert finite.unlimited is False
                assert finite.available_seconds == 60

            second_source = b"second synthetic local audio"
            second_intent = IntakeIntent(
                source_sha256=hashlib.sha256(second_source).hexdigest(),
                source_bytes=len(second_source),
                content_type="audio/wav",
                duration_ms=120_000,
                purpose="internal_analysis",
            )
            async with AsyncSession(engine) as database, database.begin():
                intake = ConversationIntake(
                    ConversationApplication(database, clock=lambda: state.now),
                    intake_policy,
                    authority=authority,
                )
                with pytest.raises(
                    ConversationConflict,
                    match="exceeds your available processing allowance",
                ):
                    await intake.prepare(
                        state.actor, second_intent, key="tester-reservation-after-revoke"
                    )
        finally:
            await engine.dispose()

    run(exercise())
