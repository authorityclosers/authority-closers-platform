"""One pass inside the sealed plan, on PostgreSQL: a configuration whose facts route is the
one-pass C4 request runs C2, ONE C4 request over the whole call and today's C5, through
the real broker router (prompt view and paid cap), with intercepted synthetic answers."""

from __future__ import annotations

import hashlib
import json
from dataclasses import replace
from typing import Any
from uuid import UUID

import pytest
from sqlalchemy import select

from ac_platform.conversation_intelligence.activation_contract import (
    StageApproval,
    load_hosted_approval_bundle,
)
from ac_platform.conversation_intelligence.admin_pricing import PRICING_SNAPSHOTS
from ac_platform.conversation_intelligence.application import ConversationApplication
from ac_platform.conversation_intelligence.broker_router import FixedProviderRouter, ProviderRoute
from ac_platform.conversation_intelligence.checkpoints import canonical
from ac_platform.conversation_intelligence.inference_worker import ConversationInferenceWorker
from ac_platform.conversation_intelligence.models import (
    ConversationCheckpoint,
    ConversationInferenceTask,
)
from ac_platform.conversation_intelligence.provider_admin import ConversationProviderAdmin
from ac_platform.conversation_intelligence.provider_registry import (
    RegistryConfig,
    parse_registry_config,
)
from ac_platform.conversation_intelligence.providers import ProviderResult
from ac_platform.conversation_intelligence.report_store import ConversationReports
from ac_platform.one_pass import markers
from tests.database.test_conversation_authority_postgresql import _setup
from tests.database.test_conversation_postgresql import run
from tests.database.test_conversation_processing_plan_postgresql import (
    _accept,
    _drive_to_completion,
    _quote,
)
from tests.database.test_conversation_reporting_pipeline_postgresql import ReportingBroker
from tests.database.test_conversation_worker_postgresql import _postgres_harness

MODEL = "gemini-3.8-flash"
COST = 3_000


@pytest.fixture
def postgres_harness() -> Any:
    yield from _postgres_harness.__wrapped__()


class OnePassBroker(ReportingBroker):
    """Answer the one-pass C4 request with call data, a note and a review; everything
    else as the reporting broker does."""

    async def execute(self, reservation: Any, payload: bytes) -> ProviderResult:
        if reservation.quote.provider_id == "gemini":
            body = json.loads(payload)
            system = body["systemInstruction"]["parts"][0]["text"]
            if system.startswith("AC_TASK_ADAPTER: gemini-json-v9\n"):
                self.routes.append("gemini")
                self.calls += 1
                self.payloads.append(payload)
                user = json.loads(body["contents"][0]["parts"][0]["text"])
                first = user["segments"][0]["id"]
                answer = {
                    "call_data": {"speakers": [], "facts": []},
                    "notes": [{"fact": "The speaker greeted the buyer.", "segments": [first]}],
                    "review": {},
                }
                envelope = {
                    "candidates": [
                        {
                            "finishReason": "STOP",
                            "content": {"role": "model", "parts": [{"text": json.dumps(answer)}]},
                        }
                    ]
                }
                raw = canonical(envelope)
                return ProviderResult(
                    provider="gemini",
                    model=reservation.quote.provider_model,
                    request_id="synthetic-one-pass",
                    response_sha256=hashlib.sha256(raw).hexdigest(),
                    raw_json=raw,
                    data=envelope,
                    usage={"total_tokens": 20},
                    input_sha256=reservation.quote.input_sha256,
                )
        return await super().execute(reservation, payload)


async def _one_pass(setup: Any) -> Any:
    """The setup's configuration with its facts route as the one-pass request, saved, and
    its bundle's stages bound to it (C4 one request at the one-pass bound, priced by the
    Gemini 3.8 Flash list-price evidence, as Root's seal does)."""
    snapshot = PRICING_SNAPSHOTS[("gemini", MODEL)]
    config: RegistryConfig = setup.config
    providers = tuple(
        replace(item, pricing_ref=snapshot.pricing_ref, max_cost_paise=COST)
        if (item.provider_id, item.model_id) == ("gemini", MODEL)
        else item
        for item in config.providers
    )
    routes = tuple(
        replace(route, recipe_revision=markers.RECIPE, prompt_revision=markers.PROMPT_REVISION)
        if route.task == "facts"
        else route
        for route in config.routes
    )
    one_pass = RegistryConfig(
        revision="hosted-test-config-one-pass",
        policy=config.policy,
        providers=providers,
        routes=routes,
    )
    async with setup.sessions() as database, database.begin():
        view = await ConversationProviderAdmin(
            ConversationApplication(database, clock=lambda: setup.prepared.state.now)
        ).save(setup.actor, one_pass.as_dict(), expected_revision=1, key="one-pass-config")
    saved = parse_registry_config(view["configuration"])
    stages = []
    for stage in setup.bundle.stages:
        update: dict[str, Any] = {"configuration_sha256": view["configuration_sha256"]}
        if stage.stage in {"C4", "C5"}:
            update.update(
                pricing_ref=snapshot.pricing_ref,
                price_evidence_sha256=snapshot.evidence_sha256,
                max_cost_paise=COST,
            )
        if stage.stage == "C4":
            update.update(
                recipe_revision=markers.RECIPE,
                max_requests=1,
                max_completion_tokens=16_000,
                max_input_bytes=max(stage.max_input_bytes, markers.MAX_INPUT_BYTES),
            )
        stages.append(StageApproval.model_validate({**stage.model_dump(), **update}))
    bundle = load_hosted_approval_bundle(
        setup.bundle.model_copy(update={"stages": tuple(stages)}).to_json()
    )
    setup.bundle_box["bundle"] = bundle
    broker = OnePassBroker(setup.prepared.data)
    router = FixedProviderRouter(
        {
            provider: ProviderRoute(provider, f"ref:credential:{provider}", broker)
            for provider in ("elevenlabs", "gemini")
        },
        authority=setup.authority,
    )
    worker = ConversationInferenceWorker(
        setup.sessions, setup.prepared.storage, router, authority=setup.authority
    )
    return replace(setup, config=saved, bundle=bundle, broker=broker, worker=worker)


def test_a_one_pass_plan_runs_one_c4_request_and_todays_c5(
    postgres_harness: Any, tmp_path: Any
) -> None:
    async def exercise() -> None:
        setup = await _setup(
            postgres_harness, tmp_path, text_provider="gemini", funded=True, text_cost_paise=COST
        )
        try:
            setup = await _one_pass(setup)
            quote = await _quote(setup, "one-pass-plan-quote")
            assert [stage["provider"] for stage in quote["stages"]] == [
                "elevenlabs",
                "gemini",
                "gemini",
            ]
            accepted = await _accept(setup, quote, "one-pass-plan-accept")
            assert accepted["accepted"] is True
            completed = await _drive_to_completion(setup, UUID(quote["id"]))
            assert completed["state"] == "completed"
            # One C4 request over the whole call, then today's C5.
            assert setup.broker.routes == ["elevenlabs", "gemini", "gemini"]
            async with setup.sessions() as db, db.begin():
                tasks = (await db.scalars(select(ConversationInferenceTask))).all()
                assert sorted(task.stage for task in tasks) == ["C2", "C4", "C5"]
                assert all(task.state == "completed" for task in tasks)
                c4 = next(task for task in tasks if task.stage == "C4")
                checkpoint = await db.get(ConversationCheckpoint, c4.checkpoint_id)
                assert checkpoint is not None
                assert checkpoint.manifest["revision"] == markers.RECIPE
                packet = checkpoint.payload
                assert (packet["chunk_index"], packet["chunk_count"]) == (1, 1)
                assert [item["statement"] for item in packet["observations"]] == [
                    "The speaker greeted the buyer."
                ]
                coaching = next(task for task in tasks if task.stage == "C5")
                report = await ConversationReports(ConversationApplication(db)).get(
                    setup.actor, coaching.run_id
                )
                assert report["report"]["source_sha256"] == setup.prepared.state.source_sha256
        finally:
            await setup.engine.dispose()

    run(exercise())
