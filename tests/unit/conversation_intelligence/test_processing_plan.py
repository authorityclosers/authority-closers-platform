from __future__ import annotations

from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock
from uuid import uuid4

import pytest

from ac_platform.conversation_intelligence.activation_contract import StageApproval
from ac_platform.conversation_intelligence.analysis_settings import AnalysisSettings
from ac_platform.conversation_intelligence.application import (
    ConversationConflict,
    ConversationDenied,
    ConversationNotFound,
)
from ac_platform.conversation_intelligence.checkpoints import canonical, content_hash
from ac_platform.conversation_intelligence.inference import DEEPGRAM_TRANSCRIPT_RECIPE
from ac_platform.conversation_intelligence.inference_tasks import InferenceTaskError
from ac_platform.conversation_intelligence.models import ConversationProcessingPlan
from ac_platform.conversation_intelligence.processing_plan import (
    PLAN_PRIVACY_REVISION,
    ConversationProcessingPlans,
    PlanAcceptance,
    PlanManifest,
    _implemented_text_provider,
    _processing_failure_diagnostic,
    automatic_c5_repair_cost,
    c5_repair_intent,
    manifest_for,
    maximum_plan_cost_with_repair,
    parse_report_language_preference,
    plan_cost_label,
    planned_c5_requests,
)
from ac_platform.conversation_intelligence.qualitative_pack import (
    load_qualitative_pack_for_revision,
)
from ac_platform.conversation_intelligence.reporting_pipeline import COACHING_RECIPE, FACT_RECIPE
from ac_platform.conversation_intelligence.reports import FACT_PROMPT_COMPACT
from ac_platform.kernel.authz import ActorContext
from tests.unit.conversation_intelligence.test_activation_contract import (
    PERSON_ID,
    TENANT_ID,
    _stage,
)


def saved_plan() -> ConversationProcessingPlan:
    profile = {"revision": "frozen-fixture-v1", "weights_actual": 95, "weights_declared": 100}
    stages = (
        _stage(),
        _stage(stage="C4", entitlement_seconds=0, max_completion_tokens=1400).model_copy(
            update={"recipe_revision": FACT_RECIPE}
        ),
        _stage(
            stage="C5",
            entitlement_seconds=0,
            max_completion_tokens=1400,
            profile_sha256=content_hash(profile),
        ).model_copy(update={"recipe_revision": COACHING_RECIPE}),
    )
    value = PlanManifest(
        schema_id="ac.sales-xray.processing-plan/1",
        recording_id=uuid4(),
        tenant_id=TENANT_ID,
        person_id=PERSON_ID,
        session_id=uuid4(),
        generation=1,
        source_sha256="a" * 64,
        source_revision=1,
        authority_sha256="b" * 64,
        transcription_cache_key="c" * 64,
        duration_ms=61000,
        stages=stages,
        profile=profile,
        created_at_epoch=1000,
        expires_at_epoch=1800,
        max_entitlement_seconds=0,
    )
    return ConversationProcessingPlan(
        id=uuid4(),
        tenant_id=value.tenant_id,
        person_id=value.person_id,
        recording_id=value.recording_id,
        session_id=value.session_id,
        generation=1,
        manifest=value.as_dict(),
        plan_sha256=content_hash(value.as_dict()),
        state="quoted",
        progress={},
        created_at=datetime.fromtimestamp(1000, UTC),
        expires_at=datetime.fromtimestamp(1800, UTC),
        next_check_at=datetime.fromtimestamp(1000, UTC),
    )


@pytest.mark.parametrize("value", [False, 1, "true", None])
def test_one_explicit_boolean_click_is_required(value: object) -> None:
    with pytest.raises(ValueError):
        PlanAcceptance.model_validate(
            {
                "plan_id": str(uuid4()),
                "plan_fingerprint": "a" * 64,
                "privacy_revision": PLAN_PRIVACY_REVISION,
                "accepted": value,
            }
        )


def test_optional_report_language_body_is_exact_and_legacy_empty_body_defaults() -> None:
    assert parse_report_language_preference(b"") is None
    for language in ("en", "hi-Deva+en", "mr-Deva+en"):
        assert (
            parse_report_language_preference(canonical({"report_language": language})) == language
        )
    for raw in (
        b"not-json",
        canonical({}),
        canonical({"report_language": "Hindi"}),
        canonical({"report_language": "mr-Deva+en", "coaching_prompt_revision": "coaching-v4"}),
    ):
        with pytest.raises(ValueError, match="report language preference"):
            parse_report_language_preference(raw)


@pytest.mark.parametrize(
    ("phase", "error", "expected"),
    [
        (
            "approval_evaluation",
            ConversationDenied("private denial detail"),
            "processing_approval_evaluation_authorization_denied",
        ),
        (
            "quote_usage_reservation",
            ConversationConflict("private conflict detail"),
            "processing_quote_usage_reservation_state_conflict",
        ),
        (
            "request_stage",
            ConversationNotFound("private resource detail"),
            "processing_request_stage_resource_unavailable",
        ),
        (
            "request_stage",
            InferenceTaskError("private local validation detail"),
            "processing_request_stage_local_input_invalid",
        ),
    ],
)
def test_enqueue_diagnostics_are_phase_bounded_and_content_free(
    phase: str, error: BaseException, expected: str
) -> None:
    diagnostic = _processing_failure_diagnostic(phase, error)
    assert diagnostic == expected
    assert "private" not in diagnostic
    assert _processing_failure_diagnostic("unexpected_phase", error) is None
    assert _processing_failure_diagnostic(phase, RuntimeError("arbitrary error")) is None


@pytest.mark.parametrize("field", ["provider", "model", "max_cost_paise", "profile"])
def test_learner_acceptance_cannot_change_provider_or_scope(field: str) -> None:
    with pytest.raises(ValueError):
        PlanAcceptance.model_validate(
            {
                "plan_id": str(uuid4()),
                "plan_fingerprint": "a" * 64,
                "privacy_revision": PLAN_PRIVACY_REVISION,
                "accepted": True,
                field: "replacement",
            }
        )


def test_saved_plan_preserves_actual_weight_discrepancy_and_finite_bound() -> None:
    value = manifest_for(saved_plan())
    assert value.profile["weights_actual"] == 95
    assert value.profile["weights_declared"] == 100
    assert value.max_entitlement_seconds == 0


def test_saved_legacy_plan_omits_compact_prompt_revision_and_new_plan_roundtrips_it() -> None:
    legacy = manifest_for(saved_plan())
    assert legacy.fact_prompt_revision != FACT_PROMPT_COMPACT
    assert "fact_prompt_revision" not in legacy.as_dict()

    compact = legacy.model_copy(update={"fact_prompt_revision": FACT_PROMPT_COMPACT})
    data = compact.as_dict()
    assert data["fact_prompt_revision"] == FACT_PROMPT_COMPACT
    assert PlanManifest.model_validate_json(canonical(data)).fact_prompt_revision == (
        FACT_PROMPT_COMPACT
    )


def test_explicit_v6_plan_binds_language_and_exact_pack_hash_without_changing_defaults() -> None:
    original = manifest_for(saved_plan())
    assert original.coaching_prompt_revision == "coaching-v1"
    assert original.qualitative_pack_sha256 is None
    assert "coaching_prompt_revision" not in original.as_dict()

    pack = load_qualitative_pack_for_revision("coaching-v6")
    data = original.as_dict()
    data["stages"][2].update(provider_id="openai", model_id="gpt-6-luna")
    data.update(
        {
            "coaching_prompt_revision": "coaching-v6",
            "report_language": "mr-Deva+en",
            "qualitative_pack_sha256": pack.sha256,
        }
    )
    selected = PlanManifest.model_validate_json(canonical(data))
    assert selected.coaching_prompt_revision == "coaching-v6"
    assert selected.report_language == "mr-Deva+en"
    assert selected.qualitative_pack_sha256 == pack.sha256
    assert selected.as_dict()["coaching_prompt_revision"] == "coaching-v6"

    data["qualitative_pack_sha256"] = "0" * 64
    with pytest.raises(ValueError, match="processing_plan_coaching_options_invalid"):
        PlanManifest.model_validate_json(canonical(data))


def plan_with_coaching_revision(revision: str) -> ConversationProcessingPlan:
    row = saved_plan()
    data = manifest_for(row).as_dict()
    if revision in {"coaching-v6", "coaching-v7"}:
        data["stages"][2].update(provider_id="openai", model_id="gpt-6-luna")
    data["coaching_prompt_revision"] = revision
    if revision in {"coaching-v4", "coaching-v5", "coaching-v6", "coaching-v7"}:
        pack = load_qualitative_pack_for_revision(revision)
        data.update({"report_language": "en", "qualitative_pack_sha256": pack.sha256})
    value = PlanManifest.model_validate_json(canonical(data))
    row.manifest = value.as_dict()
    row.plan_sha256 = content_hash(value.as_dict())
    return row


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("existing", "revision", "blocked"),
    [
        ("replay", "coaching-v6", True),
        ("active", "coaching-v6", True),
        ("replay", "coaching-v7", True),
        ("active", "coaching-v7", True),
        ("replay", "coaching-v5", False),
        ("active", "coaching-v5", False),
        ("replay", "coaching-v1", False),
    ],
)
async def test_quote_gates_stored_v6_replay_and_active_plan_without_blocking_frozen_history(
    existing: str, revision: str, blocked: bool, monkeypatch
) -> None:
    row = plan_with_coaching_revision(revision)
    recording = SimpleNamespace(
        id=row.recording_id,
        tenant_id=row.tenant_id,
        person_id=row.person_id,
        generation=row.generation,
        source_sha256="a" * 64,
        source_revision=1,
    )
    source = SimpleNamespace(
        duration_ms=60_000,
        checkpoint=SimpleNamespace(cache_key="c" * 64),
    )
    bundle = SimpleNamespace(digest="b" * 64)
    c2 = _stage(stage="C2")

    class Database:
        async def scalar(self, _statement):
            return row if existing == "active" else None

        async def scalars(self, _statement):
            return []  # no C2 checkpoints and no sensitive-segment marks

    replay = SimpleNamespace(result_id=row.id) if existing == "replay" else None
    app = SimpleNamespace(
        admit=AsyncMock(return_value=datetime.fromtimestamp(1_700_000_000, UTC)),
        get=AsyncMock(return_value=None),
        _recording=AsyncMock(return_value=recording),
        _replay=AsyncMock(return_value=replay),
    )
    authority = SimpleNamespace(approval=AsyncMock(return_value=(bundle, c2)))
    inference = SimpleNamespace(plan_transcription=AsyncMock(return_value=source))
    current_v6_settings = AsyncMock(
        return_value=(
            None,
            AnalysisSettings(
                c4_max_requests=64,
                c4_max_completion_tokens=1_400,
                c5_max_completion_tokens=3_200,
                c5_output_profile="detailed",
                c5_coaching_prompt_revision="coaching-v6",
            ),
        )
    )
    monkeypatch.setattr(
        "ac_platform.conversation_intelligence.processing_plan.latest_analysis_settings",
        current_v6_settings,
    )
    plans = object.__new__(ConversationProcessingPlans)
    plans.app = app
    plans.db = Database()
    plans.authority = authority
    plans.inference = inference
    plans._row = AsyncMock(return_value=row)
    plans.view = Mock(return_value={"plan_id": str(row.id)})

    if blocked:
        with pytest.raises(ConversationDenied, match="AC-SVAL-01 Gate 2"):
            await plans.quote(
                ActorContext(PERSON_ID, uuid4(), TENANT_ID), row.recording_id, key="reuse"
            )
        plans.view.assert_not_called()
    else:
        result = await plans.quote(
            ActorContext(PERSON_ID, uuid4(), TENANT_ID), row.recording_id, key="reuse"
        )
        assert result == {"plan_id": str(row.id)}
        plans.view.assert_called_once()

    assert app._replay.await_count == 1
    assert plans._row.await_count == int(existing == "replay")
    assert current_v6_settings.await_count == 0


def test_openai_is_admitted_only_for_c5_and_has_no_automatic_repair():
    assert _implemented_text_provider("C5", "openai") is True
    assert _implemented_text_provider("C4", "openai") is False
    assert _implemented_text_provider("C2", "openai") is False
    stage = saved_plan().manifest["stages"][2]
    approval = StageApproval.model_validate_json(canonical(stage)).model_copy(
        update={
            "provider_id": "openai",
            "model_id": "gpt-6-luna",
            "max_requests": 2,
            "max_cost_paise": 1_000,
            "zero_cost_basis": "paid_pricing_evidence",
            "free_allowance_ref": None,
        }
    )
    assert planned_c5_requests(approval) == 1
    assert automatic_c5_repair_cost(approval) == 0


def test_saved_plan_accepts_the_explicit_deepgram_c2_route() -> None:
    data = manifest_for(saved_plan()).as_dict()
    data["stages"][0].update(
        {
            "provider_id": "deepgram",
            "model_id": "nova-3",
            "recipe_revision": DEEPGRAM_TRANSCRIPT_RECIPE,
        }
    )

    parsed = PlanManifest.model_validate_json(canonical(data))

    assert (parsed.stages[0].provider_id, parsed.stages[0].model_id) == (
        "deepgram",
        "nova-3",
    )
    assert parsed.stages[0].recipe_revision == DEEPGRAM_TRANSCRIPT_RECIPE


@pytest.mark.asyncio
async def test_v6_quote_is_blocked_before_allowance_reads_or_plan_creation(monkeypatch) -> None:
    now = datetime.fromtimestamp(1_700_000_000, UTC)
    actor = ActorContext(PERSON_ID, uuid4(), TENANT_ID)
    recording = SimpleNamespace(
        id=uuid4(),
        tenant_id=TENANT_ID,
        person_id=PERSON_ID,
        generation=1,
        source_sha256="a" * 64,
        source_revision=1,
    )
    source = SimpleNamespace(
        duration_ms=60_000,
        checkpoint=SimpleNamespace(cache_key="c" * 64),
    )
    c2 = _stage(stage="C2")
    c4 = _stage(stage="C4", entitlement_seconds=0, max_completion_tokens=1_400).model_copy(
        update={"recipe_revision": FACT_RECIPE}
    )
    c5 = _stage(
        stage="C5",
        entitlement_seconds=0,
        max_completion_tokens=1_400,
        profile_sha256=content_hash(
            {"revision": "frozen-fixture-v1", "weights_actual": 95, "weights_declared": 100}
        ),
    ).model_copy(update={"model_id": "openai/gpt-oss-120b", "recipe_revision": COACHING_RECIPE})
    bundle = SimpleNamespace(
        digest="b" * 64,
        stages=(c2, c4, c5),
        expires_at_epoch=1_800_000_000,
        budget_scope_id=uuid4(),
        budget_cap_paise=0,
    )
    authority = SimpleNamespace(
        operations_tenant_id=TENANT_ID,
        approval=AsyncMock(return_value=(bundle, c2)),
        validate_route=AsyncMock(),
    )

    class Database:
        def __init__(self) -> None:
            self.get_calls: list[object] = []
            self.add_calls: list[object] = []

        async def scalar(self, _statement):
            return None

        async def scalars(self, _statement):
            return []  # no C2 checkpoints and no sensitive-segment marks

        async def get(self, model, key):
            self.get_calls.append((model, key))
            raise AssertionError("v6 runtime gate must precede allowance reads")

        def add(self, value) -> None:
            self.add_calls.append(value)

        async def flush(self) -> None:
            raise AssertionError("blocked v6 must not flush a plan")

    database = Database()
    app = SimpleNamespace(
        admit=AsyncMock(return_value=now),
        get=AsyncMock(return_value=None),
        _recording=AsyncMock(return_value=recording),
        _replay=AsyncMock(return_value=None),
        _receipt=AsyncMock(),
    )
    inference = SimpleNamespace(plan_transcription=AsyncMock(return_value=source))
    plans = object.__new__(ConversationProcessingPlans)
    plans.app = app
    plans.db = database
    plans.authority = authority
    plans.inference = inference

    monkeypatch.setattr(
        "ac_platform.conversation_intelligence.processing_plan.latest_analysis_settings",
        AsyncMock(
            return_value=(
                None,
                AnalysisSettings(
                    c4_max_requests=64,
                    c4_max_completion_tokens=1_400,
                    c5_max_completion_tokens=3_200,
                    c5_output_profile="detailed",
                    c5_coaching_prompt_revision="coaching-v6",
                ),
            )
        ),
    )

    with pytest.raises(ConversationDenied, match="AC-SVAL-01 Gate 2"):
        await plans.quote(actor, recording.id, key="v6-groq-route")

    assert database.get_calls == []
    assert database.add_calls == []
    assert app._receipt.await_count == 0
    assert authority.validate_route.await_count == 2


def test_paid_plan_adds_one_asr_all_fact_requests_and_one_judge() -> None:
    data = manifest_for(saved_plan()).as_dict()
    for stage, price in zip(data["stages"], (50, 7, 9), strict=True):
        stage.update(
            max_cost_paise=price, zero_cost_basis="paid_pricing_evidence", free_allowance_ref=None
        )
    # The fixture approves three requests per stage, but only C4 is chunked.
    data["max_cost_paise"] = 50 + 3 * 7 + 9
    parsed = PlanManifest.model_validate_json(canonical(data))
    assert parsed.max_cost_paise == 80
    assert plan_cost_label(parsed.max_cost_paise) == "Up to ₹0.80 · approved budget"
    for incorrect in (0, 79, 81, True, -1, 80.5):
        with pytest.raises(ValueError):
            PlanManifest.model_validate_json(canonical({**data, "max_cost_paise": incorrect}))


def test_new_plan_can_reserve_one_c5_repair_without_rewriting_old_costs() -> None:
    saved = manifest_for(saved_plan())
    stages = tuple(
        stage.model_copy(
            update={
                "max_cost_paise": price,
                "zero_cost_basis": "paid_pricing_evidence",
                "free_allowance_ref": None,
            }
        )
        for stage, price in zip(saved.stages, (50, 7, 9), strict=True)
    )
    assert automatic_c5_repair_cost(stages[2]) == 9
    assert maximum_plan_cost_with_repair(stages) == 89
    data = saved.model_copy(
        update={"stages": stages, "max_cost_paise": 89, "automatic_c5_repair_cost_paise": 9}
    ).as_dict()
    parsed = PlanManifest.model_validate_json(canonical(data))
    assert parsed.automatic_c5_repair_cost_paise == 9
    assert parsed.max_cost_paise == 89
    free_stages = (
        *stages[:2],
        stages[2].model_copy(
            update={
                "max_cost_paise": 0,
                "zero_cost_basis": "verified_free_allowance",
                "free_allowance_ref": "ref:free-c5",
            }
        ),
    )
    free_data = saved.model_copy(
        update={
            "stages": free_stages,
            "max_cost_paise": 71,
            "automatic_c5_repair_cost_paise": 0,
        }
    ).as_dict()
    free_parsed = PlanManifest.model_validate_json(canonical(free_data))
    assert free_parsed.automatic_c5_repair_cost_paise == 0


def test_c5_repair_requires_a_returned_known_validation_failure() -> None:
    task = SimpleNamespace(
        stage="C5", state="uncertain", intent={"request": {"stage": "C5"}}, run_id=uuid4()
    )
    job = SimpleNamespace(
        kind="conversation.infer_provider.v1",
        dispatch_started_at=datetime.now(UTC),
        provider_idempotency_key="conversation:provider:repair",
        dedupe_key="conversation:provider:repair",
        last_error="conversation_report_payload_missing_field",
        provider_receipt={
            "schema": "ac.sales-xray.provider-receipt/1",
            "validation_state": "provider_returned",
            "idempotency_key": "conversation:provider:repair",
            "raw_blob_id": "PLACEHOLDER",
            "response_sha256": "a" * 64,
        },
    )
    job.provider_receipt["raw_blob_id"] = str(task.run_id)
    repair = c5_repair_intent(task, job)
    assert repair is not None
    assert repair.attempt == 1
    assert repair.original_run_id == task.run_id
    task.intent["request"]["provider"] = "openai"
    assert c5_repair_intent(task, job) is None
    task.intent["request"].pop("provider")
    job.last_error = "conversation_provider_execution_timeout"
    assert c5_repair_intent(task, job) is None


@pytest.mark.parametrize(
    "failure_code",
    [
        "conversation_report_evidence_invalid",
        "conversation_gemini_response_json_invalid",
        "conversation_report_payload_missing_field",
        "conversation_report_overview_invalid",
    ],
)
def test_c5_repair_accepts_only_known_returned_provider_report_failures(
    failure_code: str,
) -> None:
    task = SimpleNamespace(
        stage="C5", state="uncertain", intent={"request": {"stage": "C5"}}, run_id=uuid4()
    )
    job = SimpleNamespace(
        kind="conversation.infer_provider.v1",
        dispatch_started_at=datetime.now(UTC),
        provider_idempotency_key="conversation:provider:original",
        dedupe_key="conversation:provider:original",
        last_error=failure_code,
        # A returned receipt is authoritative evidence even if acknowledgement
        # was separately marked ambiguous after validation failed.
        delivery_ambiguous_at=datetime.now(UTC),
        provider_receipt={
            "schema": "ac.sales-xray.provider-receipt/1",
            "validation_state": "provider_returned",
            "idempotency_key": "conversation:provider:original",
            "raw_blob_id": str(task.run_id),
            "response_sha256": "b" * 64,
        },
    )

    repair = c5_repair_intent(task, job)

    assert repair is not None
    assert repair.failure_code == failure_code
    assert repair.original_response_sha256 == "b" * 64


@pytest.mark.parametrize(
    "change",
    [
        {"last_error": "conversation_provider_result_validation_failed"},
        {"provider_receipt": None},
        {"dispatch_started_at": None},
        {"provider_idempotency_key": "conversation:provider:other"},
        {"provider_receipt": {"validation_state": "provider_returned"}},
    ],
)
def test_c5_repair_rejects_unproven_or_ambiguous_provider_failures(
    change: dict[str, object],
) -> None:
    task = SimpleNamespace(
        stage="C5", state="uncertain", intent={"request": {"stage": "C5"}}, run_id=uuid4()
    )
    job = SimpleNamespace(
        kind="conversation.infer_provider.v1",
        dispatch_started_at=datetime.now(UTC),
        provider_idempotency_key="conversation:provider:original",
        dedupe_key="conversation:provider:original",
        last_error="conversation_gemini_response_json_invalid",
        provider_receipt={
            "schema": "ac.sales-xray.provider-receipt/1",
            "validation_state": "provider_returned",
            "idempotency_key": "conversation:provider:original",
            "raw_blob_id": str(task.run_id),
            "response_sha256": "c" * 64,
        },
    )
    for name, value in change.items():
        setattr(job, name, value)

    assert c5_repair_intent(task, job) is None


@pytest.mark.parametrize(
    ("paise", "label"),
    [
        (0, "₹0 · approved allowance"),
        (1, "Up to ₹0.01 · approved budget"),
        (150_000, "Up to ₹1500.00 · approved budget"),
    ],
)
def test_price_labels_preserve_paise(paise: int, label: str) -> None:
    assert plan_cost_label(paise) == label


@pytest.mark.parametrize("alteration", ["source", "profile", "price", "recipient", "erased"])
def test_changed_saved_scope_cannot_become_authority(alteration: str) -> None:
    row = saved_plan()
    assert row.manifest is not None
    if alteration == "source":
        row.manifest["source_sha256"] = "d" * 64
    elif alteration == "profile":
        row.manifest["profile"]["weights_actual"] = 100
    elif alteration == "price":
        row.manifest["max_cost_paise"] = 100
    elif alteration == "recipient":
        row.person_id = uuid4()
    else:
        row.erased_at = datetime.now(UTC)
    with pytest.raises(ConversationDenied):
        manifest_for(row)
