"""One pass inside the sealed plan, on PostgreSQL: a configuration whose facts route is the
one-pass C4 request runs C2, ONE C4 request over the whole call and today's C5, through
the real broker router (prompt view and paid cap), with intercepted synthetic answers;
then the call's pointer review and deep call data are published from that same read
(one_pass.plan_publish), with no provider call."""

from __future__ import annotations

import hashlib
import json
from argparse import Namespace
from dataclasses import replace
from typing import Any
from uuid import UUID

import pytest
from sqlalchemy import select

from ac_platform.call_data.models import CallDataRun
from ac_platform.conversation_intelligence import pointer_review_cli
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
    ConversationReportDraft,
)
from ac_platform.conversation_intelligence.pointer_review_models import (
    ConversationPointerReview,
)
from ac_platform.conversation_intelligence.provider_admin import ConversationProviderAdmin
from ac_platform.conversation_intelligence.provider_registry import (
    RegistryConfig,
    parse_registry_config,
)
from ac_platform.conversation_intelligence.providers import ProviderResult
from ac_platform.conversation_intelligence.report_store import ConversationReports
from ac_platform.one_pass import calibration, markers, plan_publish
from tests.database.test_conversation_authority_postgresql import _provider, _refs, _setup
from tests.database.test_conversation_postgresql import run
from tests.database.test_conversation_processing_plan_postgresql import (
    _accept,
    _drive_to_completion,
    _quote,
)
from tests.database.test_conversation_reporting_pipeline_postgresql import ReportingBroker
from tests.database.test_conversation_worker_postgresql import _postgres_harness
from tests.unit.one_pass.test_one_pass import _review

MODEL = "gemini-3.8-flash"
LUNA = "gpt-6-luna"
LUNA_ENDPOINT = "https://api.openai.com/v1/responses"
COST = 3_000


@pytest.fixture
def postgres_harness() -> Any:
    yield from _postgres_harness.__wrapped__()


def _answer(segment: dict[str, Any]) -> dict[str, Any]:
    """Call data, a note and the fixture review, citing this call's own first segment."""
    first = segment["id"]
    review = json.loads(
        json.dumps(_review()).replace('"s1"', f'"{first}"').replace('"s3"', f'"{first}"')
    )
    review["prospect_profile"] = {
        **{key: {"value": None, "evidence": []} for key in plan_publish_profile_fields()},
        "follow_up": {"when": None, "about": None, "evidence": []},
        **review.pop("prospect"),
    }
    return {
        "call_data": {
            "speakers": [{"speaker_id": segment["speaker_id"], "role": "prospect"}],
            "facts": [
                {
                    "type": "company.name",
                    "value": {"text": "Synthetic Buyers"},
                    "confidence": 0.9,
                    "basis": "observed",
                    "segments": [first],
                }
            ],
        },
        "notes": [{"fact": "The speaker greeted the buyer.", "segments": [first]}],
        "review": review,
    }


class OnePassBroker(ReportingBroker):
    """Answer the one-pass C4 request (Gemini or GPT-6 Luna) with call data, a note and a
    review; everything else as the reporting broker does."""

    async def execute(self, reservation: Any, payload: bytes) -> ProviderResult:
        provider = reservation.quote.provider_id
        body = json.loads(payload) if provider in {"gemini", "openai"} else {}
        envelope: dict[str, Any] | None = None
        if provider == "gemini" and body["systemInstruction"]["parts"][0]["text"].startswith(
            "AC_TASK_ADAPTER: gemini-json-v9\n"
        ):
            user = json.loads(body["contents"][0]["parts"][0]["text"])
            envelope = {
                "candidates": [
                    {
                        "finishReason": "STOP",
                        "content": {
                            "role": "model",
                            "parts": [{"text": json.dumps(_answer(user["segments"][0]))}],
                        },
                    }
                ]
            }
        elif provider == "openai" and markers.is_one_pass(body.get("instructions")):
            user = json.loads(body["input"])
            envelope = {
                "id": "resp_synthetic",
                "object": "response",
                "model": body["model"],
                "status": "completed",
                "incomplete_details": None,
                "error": None,
                "store": False,
                "service_tier": "default",
                "output": [
                    {
                        "type": "message",
                        "role": "assistant",
                        "status": "completed",
                        "content": [
                            {
                                "type": "output_text",
                                "text": json.dumps(_answer(user["segments"][0])),
                            }
                        ],
                    }
                ],
            }
        if envelope is None:
            return await super().execute(reservation, payload)
        self.routes.append(provider)
        self.calls += 1
        self.payloads.append(payload)
        raw = canonical(envelope)
        return ProviderResult(
            provider=provider,
            model=reservation.quote.provider_model,
            request_id="synthetic-one-pass",
            response_sha256=hashlib.sha256(raw).hexdigest(),
            raw_json=raw,
            data=envelope,
            usage={"total_tokens": 20},
            input_sha256=reservation.quote.input_sha256,
        )


def plan_publish_profile_fields() -> tuple[str, ...]:
    from ac_platform.one_pass.analysis import PROFILE_FROM

    return tuple(PROFILE_FROM)


async def _one_pass(setup: Any, provider: str) -> Any:
    """The setup's configuration with its facts route as the one-pass request (on Gemini
    3.8 Flash, or on GPT-6 Luna with an OpenAI entry), saved, and its bundle's stages
    bound to it (C4 one request at the one-pass bound, priced by list-price evidence, as
    Root's seal does). C5 stays on Gemini."""
    gemini = PRICING_SNAPSHOTS[("gemini", MODEL)]
    luna = PRICING_SNAPSHOTS[("openai", LUNA)]
    config: RegistryConfig = setup.config
    providers = tuple(
        replace(item, pricing_ref=gemini.pricing_ref, max_cost_paise=COST)
        if (item.provider_id, item.model_id) == ("gemini", MODEL)
        else item
        for item in config.providers
    )
    if provider == "openai":
        providers += (
            replace(
                _provider("openai", LUNA, LUNA_ENDPOINT, max_cost_paise=COST),
                pricing_ref=luna.pricing_ref,
            ),
        )
    routes = tuple(
        replace(
            route,
            recipe_revision=markers.RECIPE,
            prompt_revision=markers.PROMPT_REVISION,
            **({"provider_id": "openai", "model_id": LUNA} if provider == "openai" else {}),
        )
        if route.task == "facts"
        else route
        for route in config.routes
    )
    one_pass = RegistryConfig(
        revision=f"hosted-test-config-one-pass-{provider}",
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
                pricing_ref=gemini.pricing_ref,
                price_evidence_sha256=gemini.evidence_sha256,
                max_cost_paise=COST,
            )
        if stage.stage == "C4":
            update.update(
                recipe_revision=markers.RECIPE,
                max_requests=1,
                max_completion_tokens=16_000,
                max_input_bytes=max(stage.max_input_bytes, markers.MAX_INPUT_BYTES),
            )
            if provider == "openai":
                refs = _refs("openai", paid=True)
                update.update(
                    provider_id="openai",
                    model_id=LUNA,
                    max_completion_tokens=20_000,
                    credential_ref=refs["credential_ref"],
                    provider_terms_ref=refs["provider_terms_ref"],
                    privacy_ref=refs["privacy_ref"],
                    permission_ref=refs["permission_ref"],
                    pricing_ref=luna.pricing_ref,
                    price_evidence_sha256=luna.evidence_sha256,
                )
        stages.append(StageApproval.model_validate({**stage.model_dump(), **update}))
    bundle = load_hosted_approval_bundle(
        setup.bundle.model_copy(update={"stages": tuple(stages)}).to_json()
    )
    setup.bundle_box["bundle"] = bundle
    broker = OnePassBroker(setup.prepared.data)
    router = FixedProviderRouter(
        {
            name: ProviderRoute(name, f"ref:credential:{name}", broker)
            for name in ("elevenlabs", "gemini", "openai")
        },
        authority=setup.authority,
    )
    worker = ConversationInferenceWorker(
        setup.sessions, setup.prepared.storage, router, authority=setup.authority
    )
    return replace(setup, config=saved, bundle=bundle, broker=broker, worker=worker)


@pytest.mark.parametrize("provider", ["gemini", "openai"])
def test_a_one_pass_plan_runs_one_c4_request_and_todays_c5(
    postgres_harness: Any, tmp_path: Any, provider: str
) -> None:
    async def exercise() -> None:
        setup = await _setup(
            postgres_harness, tmp_path, text_provider="gemini", funded=True, text_cost_paise=COST
        )
        try:
            setup = await _one_pass(setup, provider)
            quote = await _quote(setup, "one-pass-plan-quote")
            assert [stage["provider"] for stage in quote["stages"]] == [
                "elevenlabs",
                provider,
                "gemini",
            ]
            accepted = await _accept(setup, quote, "one-pass-plan-accept")
            assert accepted["accepted"] is True
            completed = await _drive_to_completion(setup, UUID(quote["id"]))
            assert completed["state"] == "completed"
            # One C4 request over the whole call, then today's C5.
            assert setup.broker.routes == ["elevenlabs", provider, "gemini"]
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
                statements = [item["statement"] for item in packet["observations"]]
                assert "The speaker greeted the buyer." in statements
                assert any(statement.endswith("Synthetic Buyers") for statement in statements)
                coaching = next(task for task in tasks if task.stage == "C5")
                report = await ConversationReports(ConversationApplication(db)).get(
                    setup.actor, coaching.run_id
                )
                assert report["report"]["source_sha256"] == setup.prepared.state.source_sha256
                draft = await db.scalar(
                    select(ConversationReportDraft).where(
                        ConversationReportDraft.run_id == coaching.run_id
                    )
                )
                assert draft is not None
                row = {
                    "draft_id": draft.id,
                    "tenant_id": draft.tenant_id,
                    "recording_id": draft.recording_id,
                    "run_id": draft.run_id,
                    "source_sha256": draft.source_sha256,
                    "transcript_revision": draft.payload["transcript_revision"],
                }
                segments = list(draft.transcript["normalized"]["segments"])
            # The review and call data, published from the plan's own C4 read.
            async with setup.sessions() as db, db.begin():
                planned = await db.run_sync(
                    lambda sync: plan_publish.one_pass_plans(
                        sync.connection(), [row["recording_id"]]
                    )
                )
                assert planned == {row["recording_id"]}
                read = await db.run_sync(lambda sync: plan_publish.c4_read(sync.connection(), row))
                assert read is not None and read.run_id == c4.run_id
                found = plan_publish.answer(setup.prepared.storage.root, read)
                assert found is not None and set(found) == {"call_data", "notes", "review"}

            def never(_body: Any) -> Any:
                raise AssertionError("a one-pass report needs no provider call")

            # The pointer review's own background job publishes it.
            line = await pointer_review_cli._review_one(
                setup.sessions,
                {**row, "submission_id": None},
                Namespace(
                    apply=True,
                    storage_root=setup.prepared.storage.root,
                    force=False,
                    daily_cap=10,
                    flex=False,
                ),
                mode="automatic",
                created_by=pointer_review_cli.AUTOMATIC,
                call_provider=never,
            )
            assert line["review"] == "published" and "attempt" not in line
            assert isinstance(line["call_data"], dict)
            async with setup.sessions() as db, db.begin():
                review = await db.scalar(
                    select(ConversationPointerReview).where(
                        ConversationPointerReview.run_id == coaching.run_id
                    )
                )
                assert review is not None and review.created_by == plan_publish.PUBLISHER
                assert review.prompt_sha256 == read.input_sha256
                # Calibrated to today's review and labelled beta (B3).
                assert review.payload["calibration"]["version"] == calibration.VERSION
                assert review.payload["calibration"]["label"] == "beta"
                deep = (
                    await db.scalars(
                        select(CallDataRun).where(
                            CallDataRun.recording_id == row["recording_id"],
                            CallDataRun.pipeline == "deep",
                        )
                    )
                ).all()
                # Append-only: the start, then its succeeded outcome.
                assert sorted((run.state, run.created_by) for run in deep) == [
                    ("running", plan_publish.PUBLISHER),
                    ("succeeded", plan_publish.PUBLISHER),
                ]
                # Published once: a second pass saves nothing more.
                again = await db.run_sync(
                    lambda sync: plan_publish.publish(
                        sync.connection(),
                        report=row,
                        read=read,
                        answer=found,
                        segments=segments,
                        withheld=set(),
                        storage_root=setup.prepared.storage.root,
                        now=setup.prepared.state.now,
                    )
                )
                assert (again["review"], again["call_data"]) == ("already_saved", "already_saved")
        finally:
            await setup.engine.dispose()

    run(exercise())
