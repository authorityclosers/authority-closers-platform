"""Versioned, owner-managed limits for future Sales Xray processing plans.

These settings are an additional ceiling.  The release approval, provider route
and shared budget remain authoritative and are intersected when a plan is
quoted.  Accepted plans keep the revision that was used to create them.
"""

from __future__ import annotations

from typing import Literal, cast
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ac_platform.conversation_intelligence.models import ConversationAnalysisSettings

AnalysisOutputProfile = Literal["standard", "detailed"]


class AnalysisSettings(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    c4_max_requests: int = Field(ge=1, le=64)
    c4_max_completion_tokens: int = Field(ge=256, le=4_000)
    c5_max_completion_tokens: int = Field(ge=256, le=8_000)
    c5_output_profile: AnalysisOutputProfile


DEFAULT_ANALYSIS_SETTINGS = AnalysisSettings(
    c4_max_requests=64,
    c4_max_completion_tokens=1_400,
    c5_max_completion_tokens=3_200,
    c5_output_profile="detailed",
)

ANALYSIS_SETTINGS_BOUNDS = {
    "c4_max_requests": {"min": 1, "max": 64},
    "c4_max_completion_tokens": {"min": 256, "max": 4_000},
    "c5_max_completion_tokens": {"min": 256, "max": 8_000},
    "c5_output_profile": {"values": ["standard", "detailed"]},
}


def settings_from_row(row: ConversationAnalysisSettings | None) -> AnalysisSettings:
    if row is None:
        return DEFAULT_ANALYSIS_SETTINGS
    return AnalysisSettings(
        c4_max_requests=row.c4_max_requests,
        c4_max_completion_tokens=row.c4_max_completion_tokens,
        c5_max_completion_tokens=row.c5_max_completion_tokens,
        c5_output_profile=cast(AnalysisOutputProfile, row.c5_output_profile),
    )


async def latest_analysis_settings(
    database: AsyncSession, tenant_id: UUID
) -> tuple[ConversationAnalysisSettings | None, AnalysisSettings]:
    row = await database.scalar(
        select(ConversationAnalysisSettings)
        .where(ConversationAnalysisSettings.tenant_id == tenant_id)
        .order_by(ConversationAnalysisSettings.revision.desc())
        .limit(1)
    )
    return row, settings_from_row(row)


def settings_view(
    row: ConversationAnalysisSettings | None,
    settings: AnalysisSettings,
) -> dict[str, object]:
    return {
        "revision": 0 if row is None else row.revision,
        "settings": settings.model_dump(mode="json"),
        "bounds": ANALYSIS_SETTINGS_BOUNDS,
        "created_at": None if row is None else row.created_at.isoformat(),
        "message": (
            "These limits apply to new plans. The server still intersects them with "
            "the pinned provider approval and route ceiling; accepted plans stay frozen."
        ),
    }


__all__ = [
    "ANALYSIS_SETTINGS_BOUNDS",
    "AnalysisOutputProfile",
    "AnalysisSettings",
    "DEFAULT_ANALYSIS_SETTINGS",
    "latest_analysis_settings",
    "settings_from_row",
    "settings_view",
]
