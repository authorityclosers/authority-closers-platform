"""Phone bytes reach a source-bound report through HTTP and disposable PostgreSQL.

The existing synthetic broker returns fictional transcript/report data; all
admission, storage, C1, planning and report reads use the real implementation.
"""

from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Any
from uuid import UUID, uuid4

import httpx
import pytest

from ac_platform.conversation_intelligence.broker_router import FixedProviderRouter, ProviderRoute
from ac_platform.conversation_intelligence.inference_worker import ConversationInferenceWorker
from ac_platform.conversation_intelligence.processing_plan import ProcessingPlanScheduler
from tests.database.test_conversation_postgresql import run
from tests.database.test_conversation_processing_plan_postgresql import _make_due
from tests.database.test_conversation_reporting_pipeline_postgresql import ReportingBroker
from tests.database.test_conversation_submission_http_postgresql import (
    ORIGIN,
    PREFIX,
    _headers,
    _setup,
    _sign_in,
)
from tests.database.test_conversation_submission_http_postgresql import (
    postgres_harness as _postgres_harness,
)
from tests.database.test_conversation_worker_postgresql import OfflineConversationWorker, _reconcile

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures" / "phone_audio"


@pytest.fixture
def postgres_harness() -> Any:
    yield from _postgres_harness.__wrapped__()


@pytest.mark.parametrize("filename", ["synthetic-nb.amr", "tone.3ga"])
def test_phone_source_put_reaches_original_bound_report(
    postgres_harness: Any, tmp_path: Path, filename: str
) -> None:
    async def exercise() -> None:
        setup = await _setup(postgres_harness, tmp_path, gemini=True)
        data = (FIXTURES / filename).read_bytes()
        # AAC adds codec padding beyond the helper's exact one-second WAV.
        # Permit two seconds in this fictional provider approval only.
        bundle = setup.bundle_box["bundle"]
        policy = bundle.acquisition_policy
        setup.bundle_box["bundle"] = type(bundle).model_validate_json(
            bundle.model_copy(
                update={
                    "acquisition_policy": policy.model_copy(
                        update={
                            "stages": tuple(
                                stage.model_copy(update={"max_source_duration_ms": 2000})
                                for stage in policy.stages
                            ),
                        }
                    ),
                }
            ).model_dump_json()
        )
        try:
            async with httpx.AsyncClient(
                transport=httpx.ASGITransport(app=setup.app), base_url=ORIGIN
            ) as client:
                _sign_in(setup, client)
                path = f"{PREFIX}/submissions/{uuid4()}"
                uploaded = await client.put(
                    path + "/source", content=data, headers=await _headers(client, data)
                )
                assert uploaded.status_code == 202, uploaded.text
                assert (await client.get(path + "/source")).content == data
                await _reconcile(setup.sessions, setup.state)
                local = OfflineConversationWorker(
                    setup.sessions,
                    storage=setup.runtime.storage,
                    scratch=setup.runtime.scratch,
                    environment="test",
                )
                assert await local.run_once()
                quoted = await client.post(
                    path + "/plan/quote",
                    headers={"Origin": ORIGIN, "Idempotency-Key": "phone-plan-quote"},
                )
                assert quoted.status_code == 201, quoted.text
                plan = quoted.json()
                accepted = await client.post(
                    path + "/plan",
                    json={
                        "plan_id": plan["id"],
                        "plan_fingerprint": plan["plan_fingerprint"],
                        "privacy_revision": plan["privacy_revision"],
                        "accepted": True,
                    },
                    headers={"Origin": ORIGIN, "Idempotency-Key": "phone-plan-accept"},
                )
                assert accepted.status_code == 202, accepted.text
                broker = ReportingBroker(data)
                router = FixedProviderRouter(
                    {
                        name: ProviderRoute(name, f"ref:credential:{name}", broker)
                        for name in ("elevenlabs", "gemini")
                    },
                    authority=setup.authority,
                )
                worker = ConversationInferenceWorker(
                    setup.sessions, setup.runtime.storage, router, authority=setup.authority
                )
                scheduler = ProcessingPlanScheduler(setup.sessions, setup.authority)
                for _ in range(8):
                    await worker.run_once()
                    await _make_due(setup, UUID(plan["id"]))
                    await scheduler.step()
                assert broker.routes == ["elevenlabs", "gemini", "gemini"]
                report = await client.get(path + "/report")
                assert report.status_code == 200, report.text
                assert report.json()["source_sha256"] == hashlib.sha256(data).hexdigest()
                assert (
                    report.json()["report"]["content"]["overview"]["version"] == "dipak-14-point-v1"
                )
                assert (await client.get(path + "/source")).content == data
        finally:
            await setup.engine.dispose()

    run(exercise())
