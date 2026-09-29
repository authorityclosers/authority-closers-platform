"""Account HTTP, durable workers, and idempotence proof for fictional samples."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import httpx
import pytest

from ac_platform.conversation_intelligence.inference_worker import ConversationInferenceWorker
from ac_platform.conversation_intelligence.processing_plan import ProcessingPlanScheduler
from ac_platform.conversation_intelligence.worker import OfflineConversationWorker
from ac_platform.development.sales_xray_samples import build_fake_router, seed_account_samples
from tests.database.test_conversation_postgresql import run
from tests.database.test_conversation_submission_http_postgresql import (
    ORIGIN,
    _setup,
    _sign_in,
)
from tests.database.test_conversation_worker_postgresql import _postgres_harness, _reconcile


@pytest.fixture
def postgres_harness() -> Any:
    yield from _postgres_harness.__wrapped__()


def test_dev_samples_reach_real_routes_and_second_run_adds_nothing(
    postgres_harness: Any,
    tmp_path: Path,
) -> None:
    async def exercise() -> None:
        setup = await _setup(postgres_harness, tmp_path, gemini=True)
        try:
            bundle = setup.bundle_box["bundle"]
            router = build_fake_router(bundle, setup.authority)
            local = OfflineConversationWorker(
                setup.sessions,
                storage=setup.runtime.storage,
                scratch=setup.runtime.scratch,
                environment="test",
            )
            inference = ConversationInferenceWorker(
                setup.sessions, setup.runtime.storage, router, authority=setup.authority
            )
            scheduler = ProcessingPlanScheduler(
                setup.sessions, setup.authority, setup.runtime.storage
            )

            async def publish_pending() -> None:
                await _reconcile(setup.sessions, setup.state)

            async with httpx.AsyncClient(
                transport=httpx.ASGITransport(app=setup.app), base_url=ORIGIN
            ) as client:
                _sign_in(setup, client)
                first = await seed_account_samples(
                    client,
                    setup.sessions,
                    person_id=setup.state.person_id,
                    count=2,
                    settings=setup.settings,
                    local_worker=local,
                    inference_worker=inference,
                    scheduler=scheduler,
                    publish_pending=publish_pending,
                    wait_seconds=90,
                )
                listed = (await client.get("/v1/conversation/acquisition/submissions")).json()[
                    "submissions"
                ]
                samples = [
                    row
                    for row in listed
                    if row["display_name"]
                    in {
                        "Sample call 1 · fictional",
                        "Sample call 2 · fictional",
                    }
                ]
                assert len(samples) == 2
                assert {row["state"] for row in samples} == {"report_ready"}
                for row in samples:
                    submission = row["submission_id"]
                    for suffix in ("", "/report", "/transcript"):
                        response = await client.get(
                            f"/v1/conversation/acquisition/submissions/{submission}{suffix}"
                        )
                        assert response.status_code == 200, response.text

                second = await seed_account_samples(
                    client,
                    setup.sessions,
                    person_id=setup.state.person_id,
                    count=2,
                    settings=setup.settings,
                    local_worker=local,
                    inference_worker=inference,
                    scheduler=scheduler,
                    publish_pending=publish_pending,
                    wait_seconds=10,
                )
                after = (await client.get("/v1/conversation/acquisition/submissions")).json()[
                    "submissions"
                ]
                assert first == second
                assert (
                    len(
                        [
                            row
                            for row in after
                            if row["display_name"]
                            in {
                                "Sample call 1 · fictional",
                                "Sample call 2 · fictional",
                            }
                        ]
                    )
                    == 2
                )
        finally:
            await setup.engine.dispose()

    run(exercise())
