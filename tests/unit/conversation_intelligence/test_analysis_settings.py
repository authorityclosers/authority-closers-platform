from __future__ import annotations

from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest

from ac_platform.conversation_intelligence.analysis_settings import (
    DEFAULT_ANALYSIS_SETTINGS,
    AnalysisSettings,
    settings_view,
)
from ac_platform.conversation_intelligence.analysis_settings_admin import (
    ConversationAnalysisSettingsAdmin,
)
from ac_platform.conversation_intelligence.processing_plan import PlanManifest
from ac_platform.conversation_intelligence.reporting_pipeline import StageRequest
from ac_platform.http.conversation_admin import AnalysisSettingsIntent
from ac_platform.kernel.authz import ActorContext


def test_settings_are_bounded_and_select_a_known_report_profile() -> None:
    assert DEFAULT_ANALYSIS_SETTINGS.c4_max_requests == 64
    assert DEFAULT_ANALYSIS_SETTINGS.c5_output_profile == "detailed"
    with pytest.raises(ValueError):
        AnalysisSettings(
            c4_max_requests=65,
            c4_max_completion_tokens=1400,
            c5_max_completion_tokens=3200,
            c5_output_profile="detailed",
        )
    with pytest.raises(ValueError):
        AnalysisSettings(
            c4_max_requests=4,
            c4_max_completion_tokens=1400,
            c5_max_completion_tokens=3200,
            c5_output_profile="expanded",
        )


def test_settings_view_exposes_defaults_without_inventing_a_revision() -> None:
    view = settings_view(None, DEFAULT_ANALYSIS_SETTINGS)
    assert view["revision"] == 0
    assert view["created_at"] is None
    assert view["settings"] == DEFAULT_ANALYSIS_SETTINGS.model_dump()
    assert view["bounds"]["c5_output_profile"]["values"] == ["standard", "detailed"]


def test_standard_output_is_a_c5_only_stage_option() -> None:
    request = StageRequest(
        stage="C5",
        transcript_checkpoint_id=uuid4(),
        fact_checkpoint_ids=(uuid4(),),
        output_profile="standard",
    )
    assert request.output_profile == "standard"
    with pytest.raises(ValueError):
        StageRequest(
            stage="C4",
            transcript_checkpoint_id=uuid4(),
            output_profile="standard",
        )


def test_manifest_omits_unchanged_default_settings_fields() -> None:
    assert PlanManifest.model_fields["analysis_settings_revision"].default is None
    assert PlanManifest.model_fields["output_profile"].default == "detailed"


def test_admin_intent_requires_a_revision_and_rejects_unknown_controls() -> None:
    value = AnalysisSettingsIntent.model_validate(
        {
            "expected_revision": 0,
            "settings": DEFAULT_ANALYSIS_SETTINGS.model_dump(),
        }
    )
    assert value.settings.c5_output_profile == "detailed"
    with pytest.raises(ValueError):
        AnalysisSettingsIntent.model_validate(
            {
                "expected_revision": 0,
                "settings": {
                    **DEFAULT_ANALYSIS_SETTINGS.model_dump(),
                    "budget_paise": 1000,
                },
            }
        )


async def test_replayed_admin_save_returns_the_original_revision() -> None:
    result_id = uuid4()
    row = SimpleNamespace(
        id=result_id,
        tenant_id=uuid4(),
        revision=3,
        c4_max_requests=2,
        c4_max_completion_tokens=1024,
        c5_max_completion_tokens=4096,
        c5_output_profile="standard",
        created_at=datetime.now(UTC),
    )
    database = SimpleNamespace(execute=AsyncMock(), get=AsyncMock(return_value=row))
    application = SimpleNamespace(
        database=database,
        _replay=AsyncMock(return_value=SimpleNamespace(result_id=result_id)),
    )
    service = ConversationAnalysisSettingsAdmin(
        application=application, operations_tenant_id=row.tenant_id
    )
    service.admit = AsyncMock()
    settings = AnalysisSettings(
        c4_max_requests=2,
        c4_max_completion_tokens=1024,
        c5_max_completion_tokens=4096,
        c5_output_profile="standard",
    )
    actor = ActorContext(uuid4(), uuid4(), row.tenant_id)
    value = await service.save(actor, settings, expected_revision=2, key="settings-replay")
    assert value["revision"] == 3
    assert value["settings"]["c5_output_profile"] == "standard"
    application._replay.assert_awaited_once()
