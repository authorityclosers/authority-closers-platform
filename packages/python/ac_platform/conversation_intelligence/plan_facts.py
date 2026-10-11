"""What a processing plan's manifest says about how a call was analysed.

Shared by the Admin call review console and Analysis health (AUT-1798), so
both read the same prompt revision, provider and model from a plan.
"""

from __future__ import annotations

from typing import Any

from ac_platform.conversation_intelligence.models import ConversationProcessingPlan


def plan_facts(plan: ConversationProcessingPlan | None) -> dict[str, Any]:
    """What a plan says about how a call was analysed; missing fields stay None."""

    manifest: dict[str, Any] = (
        plan.manifest if plan is not None and isinstance(plan.manifest, dict) else {}
    )
    raw_stages = manifest.get("stages")
    stages: list[Any] = raw_stages if isinstance(raw_stages, list) else []
    by_stage = {
        item.get("stage"): item for item in stages if isinstance(item, dict) and item.get("stage")
    }
    coaching = by_stage.get("C5") or {}
    transcription = by_stage.get("C2") or {}
    language = manifest.get("report_language")
    duration = manifest.get("duration_ms")
    return {
        "plan_id": None if plan is None else str(plan.id),
        "plan_state": None if plan is None else plan.state,
        "language": language if isinstance(language, str) else "en" if manifest else None,
        "duration_ms": duration if isinstance(duration, int) else None,
        "prompt_revision": manifest.get("coaching_prompt_revision"),
        "fact_prompt_revision": manifest.get("fact_prompt_revision"),
        "analysis_settings_revision": manifest.get("analysis_settings_revision"),
        "output_profile": manifest.get("output_profile"),
        "retry_of": manifest.get("retry_of"),
        "provider": coaching.get("provider_id"),
        "model": coaching.get("model_id"),
        "transcription_provider": transcription.get("provider_id"),
        "transcription_model": transcription.get("model_id"),
    }
