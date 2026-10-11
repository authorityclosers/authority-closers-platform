"""Retained partial output uses the same owner and privacy guards as reports."""

from __future__ import annotations

import hashlib
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from uuid import UUID

import httpx
import pytest

from ac_platform.conversation_intelligence import partial_results
from ac_platform.conversation_intelligence.inference_worker import ConversationInferenceWorker
from ac_platform.conversation_intelligence.processing_plan import ProcessingPlanScheduler
from ac_platform.conversation_intelligence.sensitive_segments import WITHHELD_MARKER
from ac_platform.conversation_intelligence.sensitive_segments_store import SensitiveSegmentsStore
from tests.database.test_conversation_failure_observation_postgresql import seed_measured_fixture
from tests.database.test_conversation_postgresql import run
from tests.database.test_conversation_reporting_pipeline_postgresql import ReportingBroker
from tests.database.test_conversation_submission_http_postgresql import (
    ORIGIN,
    _setup,
    _sign_in,
    _upload_for_read_test,
)
from tests.database.test_conversation_worker_postgresql import (
    _postgres_harness,
    _reconcile,
    _wav_one_second_48k,
)
from tests.unit.conversation_intelligence.test_acquisition_source import ValidationFixtureRuntime
from tests.unit.conversation_intelligence.test_alignment import _signal


@pytest.fixture
def postgres_harness() -> Any:
    yield from _postgres_harness.__wrapped__()


def test_progress_publishes_c2_then_c4_before_report_and_refuses_corrupt_content(
    postgres_harness: Any, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    async def exercise() -> None:
        setup = await _setup(postgres_harness, tmp_path, gemini=True)
        setup.native.validate_source = ValidationFixtureRuntime().validate_source
        try:
            async with httpx.AsyncClient(
                transport=httpx.ASGITransport(app=setup.app), base_url=ORIGIN
            ) as client:
                _sign_in(setup, client)
                path, _ = await _upload_for_read_test(setup, client)
                await _reconcile(setup.sessions, setup.state)
                body = (await client.get(path)).json()
                assert body["partial_results"]["state"] == "waiting"
                recording_id = UUID(body["recording_id"])
                await seed_measured_fixture(
                    setup.sessions,
                    SimpleNamespace(recording_id=recording_id),
                    signal_payload=_signal(
                        source_sha256=hashlib.sha256(_wav_one_second_48k()).hexdigest()
                    ),
                )
                headers = {"Origin": ORIGIN, "Idempotency-Key": "partial:quote"}
                quoted = await client.post(path + "/plan/quote", headers=headers)
                assert quoted.status_code == 201, quoted.text
                quote = quoted.json()
                accepted = await client.post(
                    path + "/plan",
                    json={
                        "plan_id": quote["id"],
                        "plan_fingerprint": quote["plan_fingerprint"],
                        "privacy_revision": quote["privacy_revision"],
                        "accepted": True,
                    },
                    headers={"Origin": ORIGIN, "Idempotency-Key": "partial:accept"},
                )
                assert accepted.status_code == 202, accepted.text
                broker = ReportingBroker(_wav_one_second_48k())
                worker = ConversationInferenceWorker(
                    setup.sessions, setup.runtime.storage, broker, authority=setup.authority
                )
                scheduler = ProcessingPlanScheduler(setup.sessions, setup.authority)
                assert await worker.run_once()
                c2 = (await client.get(path)).json()
                assert c2["has_report"] is False
                assert c2["partial_results"]["state"] == "partial"
                assert c2["partial_results"]["transcript"]["segments"]
                assert c2["partial_results"]["key_moments"] == []
                assert await scheduler.step()
                assert await worker.run_once()
                c4 = (await client.get(path)).json()
                assert c4["has_report"] is False
                assert c4["partial_results"]["completed_fact_chunks"] == 1
                assert c4["partial_results"]["key_moments"]
                segment = c4["partial_results"]["transcript"]["segments"][0]
                async with setup.sessions() as db, db.begin():
                    await SensitiveSegmentsStore(db).mark_generation(
                        recording_id=recording_id,
                        transcript_revision=c4["partial_results"]["transcript"]["revision"],
                        model_segments=[(segment["id"], "SENSITIVE_FINANCIAL")],
                    )
                masked = (await client.get(path)).json()["partial_results"]
                assert masked["transcript"]["segments"][0]["text"] == WITHHELD_MARKER
                assert masked["key_moments"][0]["evidence"][0]["quote"] == WITHHELD_MARKER

                client.cookies.clear()
                client.cookies.set("ac_xray_guest", setup.stranger.token)
                assert (await client.get(path)).status_code == 404
                _sign_in(setup, client)
                original = partial_results.verified_checkpoint

                def damaged(checkpoint: Any, binding: Any) -> Any:
                    if checkpoint.stage == "C2":
                        checkpoint = SimpleNamespace(
                            manifest=checkpoint.manifest,
                            payload={**checkpoint.payload, "duration_ms": 9999},
                            stage=checkpoint.stage,
                            cache_key=checkpoint.cache_key,
                            manifest_sha256=checkpoint.manifest_sha256,
                            payload_sha256=checkpoint.payload_sha256,
                            erased_at=checkpoint.erased_at,
                        )
                    return original(checkpoint, binding)

                # Damage only a detached read; canonical history remains immutable.
                monkeypatch.setattr(partial_results, "verified_checkpoint", damaged)
                refused = await client.get(path)
                assert refused.status_code == 200
                assert refused.json()["partial_results"]["state"] == "unavailable"
                assert refused.json()["partial_results"]["transcript"] is None
                assert broker.calls == 2
        finally:
            await setup.engine.dispose()

    run(exercise())
