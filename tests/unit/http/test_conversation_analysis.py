from __future__ import annotations

import hashlib
from types import SimpleNamespace
from uuid import UUID

import pytest
from fastapi import HTTPException

import ac_platform.http.conversation_analysis as analysis_module
from ac_platform.conversation_intelligence.analysis_settings import AnalysisSettings
from ac_platform.conversation_intelligence.checkpoints import content_hash
from ac_platform.conversation_intelligence.reporting_pipeline import COACHING_RECIPE, FACT_RECIPE
from ac_platform.conversation_intelligence.reports import load_report_profile
from tests.unit.conversation_intelligence.test_broker_router import _bundle, _stage

TENANT_ID = UUID("10000000-0000-4000-8000-000000000001")
PERSON_ID = UUID("20000000-0000-4000-8000-000000000002")
RECORDING_ID = UUID("30000000-0000-4000-8000-000000000003")
TRANSCRIPT_ID = UUID("40000000-0000-4000-8000-000000000004")
FACT_ID = UUID("50000000-0000-4000-8000-000000000005")
SOURCE_SHA = hashlib.sha256(b"synthetic router audio").hexdigest()


class FakeApplication:
    database = object()

    async def get(self, actor: object, recording_id: UUID) -> None:
        assert recording_id == RECORDING_ID

    async def _recording(self, actor: object, recording_id: UUID) -> object:
        assert recording_id == RECORDING_ID
        return SimpleNamespace(source_sha256=SOURCE_SHA)


class FakeAuthority:
    operations_tenant_id = TENANT_ID

    def __init__(self, bundle: object) -> None:
        self.bundle = bundle

    async def admit(self, app: object, actor: object) -> object:
        return self.bundle


def settings(
    *, revision: str = "coaching-v5", output_profile: str = "detailed", maximum: int = 8_000
) -> AnalysisSettings:
    return AnalysisSettings(
        c4_max_requests=64,
        c4_max_completion_tokens=1_400,
        c5_max_completion_tokens=maximum,
        c5_output_profile=output_profile,
        c5_coaching_prompt_revision=revision,
        report_language_default="en",
    )


def openai_bundle(*, stage: str = "C5") -> object:
    profile_sha256 = content_hash(load_report_profile()) if stage == "C5" else None
    approval = _stage(
        stage=stage,
        provider_id="openai",
        model_id="gpt-6-luna",
        recipe_revision=COACHING_RECIPE if stage == "C5" else FACT_RECIPE,
        profile_sha256=profile_sha256,
    ).model_copy(update={"max_completion_tokens": 8_000 if stage == "C5" else 1_400})
    return _bundle(approval)


def patch_settings(monkeypatch: pytest.MonkeyPatch, current: AnalysisSettings) -> list[UUID]:
    seen: list[UUID] = []

    async def latest(_database: object, tenant_id: UUID) -> tuple[None, AnalysisSettings]:
        seen.append(tenant_id)
        return None, current

    monkeypatch.setattr(analysis_module, "latest_analysis_settings", latest)
    return seen


@pytest.mark.asyncio
async def test_openai_c5_http_selection_uses_canonical_settings_and_saved_checkpoints(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    selection = analysis_module.AnalysisSelection(
        stage="C5",
        transcript_checkpoint_id=TRANSCRIPT_ID,
        fact_checkpoint_ids=(FACT_ID,),
    )
    seen = patch_settings(monkeypatch, settings())
    actor = SimpleNamespace(tenant_id=TENANT_ID, person_id=PERSON_ID)

    request, configuration_sha256 = await selection.stage_request(
        FakeApplication(), actor, RECORDING_ID, FakeAuthority(openai_bundle())
    )

    assert request is not None
    assert configuration_sha256 == "b" * 64
    assert (request.stage, request.provider, request.model) == ("C5", "openai", "gpt-6-luna")
    assert request.max_completion_tokens == 8_000
    assert request.transcript_checkpoint_id == TRANSCRIPT_ID
    assert request.fact_checkpoint_ids == (FACT_ID,)
    assert request.coaching_prompt_revision == "coaching-v5"
    assert request.report_language == "en"
    assert request.qualitative_pack_sha256 is not None
    assert request.profile == load_report_profile()
    assert seen == [TENANT_ID]


@pytest.mark.asyncio
async def test_http_selection_fails_closed_on_ambiguous_approved_configurations(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    selection = analysis_module.AnalysisSelection(
        stage="C5",
        transcript_checkpoint_id=TRANSCRIPT_ID,
        fact_checkpoint_ids=(FACT_ID,),
    )
    patch_settings(monkeypatch, settings())
    bundle = openai_bundle()
    alternate = bundle.stages[0].model_copy(update={"configuration_sha256": "a" * 64})
    ambiguous = bundle.model_copy(update={"stages": (*bundle.stages, alternate)})

    with pytest.raises(HTTPException) as caught:
        await selection.stage_request(
            FakeApplication(),
            SimpleNamespace(tenant_id=TENANT_ID, person_id=PERSON_ID),
            RECORDING_ID,
            FakeAuthority(ambiguous),
        )

    assert caught.value.status_code == 403


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("revision", "output_profile"),
    [("coaching-v3", "detailed"), ("coaching-v5", "standard")],
)
async def test_openai_c5_http_selection_denies_unreviewed_prompt_shapes(
    monkeypatch: pytest.MonkeyPatch, revision: str, output_profile: str
) -> None:
    selection = analysis_module.AnalysisSelection(
        stage="C5",
        transcript_checkpoint_id=TRANSCRIPT_ID,
        fact_checkpoint_ids=(FACT_ID,),
    )
    patch_settings(monkeypatch, settings(revision=revision, output_profile=output_profile))
    actor = SimpleNamespace(tenant_id=TENANT_ID, person_id=PERSON_ID)

    with pytest.raises(HTTPException) as caught:
        await selection.stage_request(
            FakeApplication(), actor, RECORDING_ID, FakeAuthority(openai_bundle())
        )

    assert caught.value.status_code == 403


@pytest.mark.asyncio
async def test_openai_http_selection_cannot_run_facts_or_transcription(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    patch_settings(monkeypatch, settings())
    actor = SimpleNamespace(tenant_id=TENANT_ID, person_id=PERSON_ID)
    c4 = analysis_module.AnalysisSelection(stage="C4", transcript_checkpoint_id=TRANSCRIPT_ID)
    c2 = analysis_module.AnalysisSelection(stage="C2")

    with pytest.raises(HTTPException) as caught:
        await c4.stage_request(
            FakeApplication(), actor, RECORDING_ID, FakeAuthority(openai_bundle(stage="C4"))
        )
    assert caught.value.status_code == 403
    request, configuration_sha256 = await c2.stage_request(
        FakeApplication(), actor, RECORDING_ID, FakeAuthority(_bundle())
    )
    assert request is None
    assert configuration_sha256 == "b" * 64


def test_analysis_selection_does_not_accept_client_configuration_override() -> None:
    with pytest.raises(ValueError):
        analysis_module.AnalysisSelection.model_validate(
            {
                "stage": "C5",
                "transcript_checkpoint_id": str(TRANSCRIPT_ID),
                "fact_checkpoint_ids": [str(FACT_ID)],
                "configuration_sha256": "a" * 64,
            }
        )
