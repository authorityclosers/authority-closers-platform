"""Versioned, owner-managed limits for future Sales Xray processing plans.

These settings are an additional ceiling.  The release approval, provider route
and shared budget remain authoritative and are intersected when a plan is
quoted.  Accepted plans keep the revision that was used to create them.
"""

from __future__ import annotations

from datetime import UTC
from typing import Literal, cast
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ac_platform.conversation_intelligence.models import ConversationAnalysisSettings
from ac_platform.conversation_intelligence.qualitative_pack import ReportLanguage

AnalysisOutputProfile = Literal["standard", "detailed"]


class AnalysisSettings(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    c4_max_requests: int = Field(ge=1, le=64)
    c4_max_completion_tokens: int = Field(ge=256, le=4_000)
    c5_max_completion_tokens: int = Field(ge=256, le=8_000)
    c5_output_profile: AnalysisOutputProfile
    c5_coaching_prompt_revision: Literal["coaching-v3", "coaching-v4", "coaching-v5"] = Field(
        default="coaching-v3", exclude_if=lambda value: value == "coaching-v3"
    )
    report_language_default: ReportLanguage = Field(
        default="en", exclude_if=lambda value: value == "en"
    )

    @model_validator(mode="after")
    def language_requires_versioned_prompt(self) -> AnalysisSettings:
        if (
            self.c5_coaching_prompt_revision not in {"coaching-v4", "coaching-v5"}
            and self.report_language_default != "en"
        ):
            raise ValueError("Select coaching-v4 or coaching-v5 for a non-English report default.")
        return self

    def effective_values(self) -> dict[str, object]:
        # Full read projection; command serialization omits legacy defaults so
        # existing idempotency receipts keep their original payload fingerprint.
        return {
            **self.model_dump(mode="json"),
            "c5_coaching_prompt_revision": self.c5_coaching_prompt_revision,
            "report_language_default": self.report_language_default,
        }


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
    "c5_coaching_prompt_revision": {"values": ["coaching-v3", "coaching-v4", "coaching-v5"]},
    "report_language_default": {"values": ["en", "hi-Deva+en", "mr-Deva+en"]},
}


def settings_from_row(row: ConversationAnalysisSettings | None) -> AnalysisSettings:
    if row is None:
        return DEFAULT_ANALYSIS_SETTINGS
    return AnalysisSettings(
        c4_max_requests=row.c4_max_requests,
        c4_max_completion_tokens=row.c4_max_completion_tokens,
        c5_max_completion_tokens=row.c5_max_completion_tokens,
        c5_output_profile=cast(AnalysisOutputProfile, row.c5_output_profile),
        c5_coaching_prompt_revision=cast(
            Literal["coaching-v3", "coaching-v4", "coaching-v5"], row.c5_coaching_prompt_revision
        ),
        report_language_default=cast(ReportLanguage, row.report_language_default),
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
    message = (
        (
            "No Admin analysis-settings revision is saved. The values shown are starting "
            "values only; new plans remain governed by the pinned provider approval and "
            "route ceiling until a revision is saved. Accepted plans stay frozen."
        )
        if row is None
        else (
            "These limits apply to new plans. The server still intersects them with "
            "the pinned provider approval and route ceiling; accepted plans stay frozen."
        )
    )
    return {
        "revision": 0 if row is None else row.revision,
        "settings": settings.effective_values(),
        "bounds": ANALYSIS_SETTINGS_BOUNDS,
        "created_at": None if row is None else row.created_at.astimezone(UTC).isoformat(),
        "message": message,
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
