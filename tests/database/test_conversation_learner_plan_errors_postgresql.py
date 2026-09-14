"""Learner and standalone plan denials roll back and remain private HTTP errors."""

from pathlib import Path
from typing import Any
from uuid import UUID

import httpx
import pytest
from sqlalchemy import func, select

from ac_platform.conversation_intelligence.application import ConversationDenied
from ac_platform.conversation_intelligence.authority import ConversationAuthority
from ac_platform.conversation_intelligence.models import (
    ConversationInferenceTask,
    ConversationPlanStageAuthorization,
    ConversationProcessingPlan,
)
from tests.database.test_conversation_postgresql import run
from tests.database.test_conversation_submission_http_postgresql import (
    ORIGIN,
    _setup,
    _upload_for_read_test,
)
from tests.database.test_conversation_submission_http_postgresql import (
    postgres_harness as _postgres_harness,
)
from tests.database.test_conversation_worker_postgresql import (
    OfflineConversationWorker,
    _reconcile,
)


@pytest.fixture
def postgres_harness() -> Any:
    yield from _postgres_harness.__wrapped__()


@pytest.mark.parametrize("origin", ["https://learner.example.test", ORIGIN])
def test_plan_allowance_denial_is_private_403_and_rolls_back_acceptance(
    postgres_harness: Any, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, origin: str
) -> None:
    async def exercise() -> None:
        setup = await _setup(postgres_harness, tmp_path, gemini=True)
        try:
            transport = httpx.ASGITransport(app=setup.app, raise_app_exceptions=False)
            async with httpx.AsyncClient(transport=transport, base_url=ORIGIN) as guest:
                guest.cookies.set("ac_xray_guest", setup.guest.token)
                path, _ = await _upload_for_read_test(setup, guest)
            await _reconcile(setup.sessions, setup.state)
            local = OfflineConversationWorker(
                setup.sessions,
                storage=setup.runtime.storage,
                scratch=setup.runtime.scratch,
                environment="test",
            )
            assert await local.run_once()
            async with setup.sessions() as db, db.begin():
                await setup.factory(db).claim(setup.guest.token, setup.state.actor)
            async with httpx.AsyncClient(transport=transport, base_url=origin) as account:
                account.cookies.set(setup.settings.session_cookie_name, setup.token)
                quoted = await account.post(
                    path + "/plan/quote",
                    headers={"Origin": origin, "Idempotency-Key": "denied-plan-quote"},
                )
                assert quoted.status_code == 201, quoted.text
                plan = quoted.json()
                calls = 0

                async def exhausted(self: Any, *args: Any, **kwargs: Any) -> Any:
                    nonlocal calls
                    calls += 1
                    raise ConversationDenied(
                        "This recording's approved provider allowance is used."
                    )

                # The real acceptance and enqueue run up to their authority check.
                # No broker runs; the exception must unwind the owner transaction.
                monkeypatch.setattr(ConversationAuthority, "validate_quote", exhausted)
                denied = await account.post(
                    path + "/plan",
                    json={
                        "plan_id": plan["id"],
                        "plan_fingerprint": plan["plan_fingerprint"],
                        "privacy_revision": plan["privacy_revision"],
                        "accepted": True,
                    },
                    headers={"Origin": origin, "Idempotency-Key": "denied-plan-accept"},
                )
                assert calls == 1
                assert denied.status_code == 403, denied.text
                assert "approved provider allowance is used" in denied.text
                assert denied.headers["cache-control"] == "private, no-store"
                assert "Cookie" in denied.headers["vary"]
                assert setup.token not in denied.text
                async with setup.sessions() as db:
                    saved = await db.get(ConversationProcessingPlan, UUID(plan["id"]))
                    assert saved is not None
                    assert saved.state == "quoted"
                    assert saved.acceptance_command_id is None
                    for model in (ConversationInferenceTask, ConversationPlanStageAuthorization):
                        assert await db.scalar(select(func.count()).select_from(model)) == 0
        finally:
            await setup.engine.dispose()

    run(exercise())
