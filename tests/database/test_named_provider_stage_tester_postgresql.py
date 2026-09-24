"""PostgreSQL proof for named-owner stage-count exemptions.

All provider effects use the existing synthetic broker and disposable schema.
This test never contacts an external provider or changes a hosted approval.
"""

from __future__ import annotations

import hashlib
import hmac
import secrets
from pathlib import Path
from typing import Any
from uuid import UUID, uuid4

import httpx
import pytest
from sqlalchemy import func, select, update

from ac_platform.conversation_intelligence.acquisition_models import (
    ConversationAcquisitionUsage,
)
from ac_platform.conversation_intelligence.activation_contract import InternalTesterApproval
from ac_platform.conversation_intelligence.application import (
    ConversationApplication,
    ConversationDenied,
)
from ac_platform.conversation_intelligence.guest_ownership import GuestOwnership
from ac_platform.conversation_intelligence.inference import ConversationInference
from ac_platform.conversation_intelligence.inference_worker import ConversationInferenceWorker
from ac_platform.conversation_intelligence.internal_tester import InternalTesterPolicy
from ac_platform.conversation_intelligence.models import ConversationInferenceTask
from ac_platform.conversation_intelligence.processing_actor import ProcessingActor
from ac_platform.identity.models import Person
from ac_platform.identity.models import Session as IdentitySession
from ac_platform.kernel.authz import ActorContext
from tests.database.test_conversation_postgresql import postgres_harness as _postgres_harness
from tests.database.test_conversation_postgresql import run, seed
from tests.database.test_conversation_reporting_pipeline_postgresql import ReportingBroker
from tests.database.test_conversation_submission_http_postgresql import (
    ORIGIN,
    PREFIX,
    _headers,
    _setup,
)
from tests.database.test_conversation_worker_postgresql import (
    OfflineConversationWorker,
    _reconcile,
    _wav_one_second_48k,
)


@pytest.fixture
def postgres_harness() -> Any:
    yield from _postgres_harness.__wrapped__()


async def _upload_as(setup: Any, data: bytes, token: str) -> tuple[UUID, UUID]:
    submission_id = uuid4()
    path = f"{PREFIX}/submissions/{submission_id}"
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=setup.app), base_url=ORIGIN
    ) as client:
        client.cookies.set(setup.settings.session_cookie_name, token)
        response = await client.put(
            path + "/source",
            content=data,
            headers=await _headers(client, data),
        )
    assert response.status_code == 202, response.text
    return submission_id, UUID(response.json()["recording_id"])


async def _processing_actor(
    setup: Any, submission_id: UUID, owner: ActorContext
) -> ProcessingActor:
    async with setup.sessions() as database, database.begin():
        app = ConversationApplication(database, clock=lambda: setup.clock[0])
        actor = await GuestOwnership(setup.factory(database)).resolve_processing_actor(
            submission_id, actor=owner
        )
        assert isinstance(actor, ProcessingActor)
        await setup.authority.claim_allowance(app, actor)
        return actor


async def _request_transcription(
    setup: Any,
    actor: ProcessingActor,
    recording_id: UUID,
    *,
    key: str,
) -> dict[str, Any]:
    async with setup.sessions() as database, database.begin():
        app = ConversationApplication(database, clock=lambda: setup.clock[0])
        service = ConversationInference(app, authority=setup.authority)
        quote = await setup.authority.issue(
            app, actor, recording_id, key=f"{key}-quote", request=None
        )
        from ac_platform.conversation_intelligence.contracts import QuoteAcceptance

        await service.accept(
            actor,
            recording_id,
            UUID(quote["id"]),
            QuoteAcceptance(
                quote_fingerprint=quote["quote_fingerprint"],
                privacy_revision=quote["privacy_revision"],
                accepted=True,
            ),
        )
        return await service.request_transcription(
            actor, recording_id, UUID(quote["id"]), key=f"{key}-run"
        )


def test_provider_request_scope_follows_submission_owner_not_shared_processor(
    postgres_harness: Any, tmp_path: Path
) -> None:
    async def exercise() -> None:
        setup = await _setup(
            postgres_harness,
            tmp_path,
            gemini=True,
            funded=False,
            c2_max_requests=1,
        )
        data = _wav_one_second_48k()
        tester = await seed(setup.engine, tenant_id=setup.state.tenant_id)
        tester_token = secrets.token_urlsafe(32)
        ordinary_token = secrets.token_urlsafe(32)
        try:
            token_pepper = setup.settings.session_token_pepper.get_secret_value().encode("utf-8")
            async with setup.sessions() as database, database.begin():
                await database.execute(
                    update(Person)
                    .where(Person.id == tester.person_id)
                    .values(email="dipak@authorityclosers.com")
                )
                await database.execute(
                    update(IdentitySession)
                    .where(IdentitySession.id == tester.session_id)
                    .values(
                        token_hash=hmac.new(
                            token_pepper, tester_token.encode("ascii"), hashlib.sha256
                        ).digest()
                    )
                )

            ordinary = await seed(setup.engine, tenant_id=setup.state.tenant_id)
            async with setup.sessions() as database, database.begin():
                await database.execute(
                    update(IdentitySession)
                    .where(IdentitySession.id == ordinary.session_id)
                    .values(
                        token_hash=hmac.new(
                            token_pepper, ordinary_token.encode("ascii"), hashlib.sha256
                        ).digest()
                    )
                )

            base_bundle = setup.bundle_box["bundle"]
            tester_scope = InternalTesterApproval(
                id=uuid4(),
                email="dipak@authorityclosers.com",
                authorization_ref="ref:approval:dipak-provider-count-test",
                scopes=("provider_stage_request_count",),
                reason="Approved internal tester exemption",
            )
            granted_bundle = base_bundle.model_copy(
                update={"internal_tester_accounts": (tester_scope,)}
            )
            setup.bundle_box["bundle"] = granted_bundle
            setup.authority.tester_policy = InternalTesterPolicy(
                lambda: setup.bundle_box["bundle"], "test"
            )

            primary_submission, primary_recording = await _upload_as(setup, data, tester_token)
            await _reconcile(setup.sessions, setup.state)
            local_worker = OfflineConversationWorker(
                setup.sessions,
                storage=setup.runtime.storage,
                scratch=setup.runtime.scratch,
                environment="test",
            )
            assert await local_worker.run_once()
            primary_actor = await _processing_actor(setup, primary_submission, tester.actor)
            broker = ReportingBroker(data)
            worker = ConversationInferenceWorker(
                setup.sessions,
                setup.runtime.storage,
                broker,
                authority=setup.authority,
            )
            first = await _request_transcription(
                setup,
                primary_actor,
                primary_recording,
                key="named-owner-shared-source-primary",
            )
            assert await worker.run_once()
            assert broker.calls == 1

            ordinary_submission, ordinary_recording = await _upload_as(setup, data, ordinary_token)
            await _reconcile(setup.sessions, setup.state)
            assert await local_worker.run_once()
            ordinary_actor = await _processing_actor(setup, ordinary_submission, ordinary.actor)
            assert ordinary_actor.person_id == primary_actor.person_id
            assert ordinary_actor.tenant_id == primary_actor.tenant_id
            assert ordinary_actor.processing_lease_id != primary_actor.processing_lease_id
            with pytest.raises(ConversationDenied, match="provider allowance is used"):
                await _request_transcription(
                    setup,
                    ordinary_actor,
                    ordinary_recording,
                    key="ordinary-owner-shared-source-denied",
                )
            async with setup.sessions() as database:
                assert (
                    await database.scalar(
                        select(func.count()).where(
                            ConversationInferenceTask.recording_id == ordinary_recording,
                            ConversationInferenceTask.stage == "C2",
                        )
                    )
                    == 0
                )
            assert broker.calls == 1

            second_tester_submission, second_tester_recording = await _upload_as(
                setup, data, tester_token
            )
            await _reconcile(setup.sessions, setup.state)
            assert await local_worker.run_once()
            second_tester_actor = await _processing_actor(
                setup, second_tester_submission, tester.actor
            )
            assert second_tester_actor.person_id == primary_actor.person_id
            second = await _request_transcription(
                setup,
                second_tester_actor,
                second_tester_recording,
                key="named-owner-shared-source-allowed",
            )
            assert first["id"] != second["id"]
            assert await worker.run_once()
            assert broker.calls == 2

            revoked_submission, revoked_recording = await _upload_as(setup, data, tester_token)
            await _reconcile(setup.sessions, setup.state)
            assert await local_worker.run_once()
            revoked_actor = await _processing_actor(setup, revoked_submission, tester.actor)
            async with setup.sessions() as database, database.begin():
                await database.execute(
                    update(Person)
                    .where(Person.id == tester.person_id)
                    .values(email_verified_at=None)
                )
            with pytest.raises(ConversationDenied, match="provider allowance is used"):
                await _request_transcription(
                    setup,
                    revoked_actor,
                    revoked_recording,
                    key="unverified-owner-scope-revoked",
                )
            assert broker.calls == 2

            async with setup.sessions() as database:
                usages = list(
                    (
                        await database.scalars(
                            select(ConversationAcquisitionUsage).where(
                                ConversationAcquisitionUsage.source_sha256
                                == hashlib.sha256(data).hexdigest()
                            )
                        )
                    ).all()
                )
                owners = {usage.person_id for usage in usages}
                assert tester.person_id in owners
                assert ordinary.person_id in owners
        finally:
            await setup.engine.dispose()

    run(exercise())
