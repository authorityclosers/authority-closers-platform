"""Admin API service for append-only future-plan analysis limits."""

from __future__ import annotations

from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import select

from ac_platform.conversation_intelligence.analysis_settings import (
    AnalysisSettings,
    latest_analysis_settings,
    settings_from_row,
    settings_view,
)
from ac_platform.conversation_intelligence.application import (
    ConversationApplication,
    ConversationConflict,
    ConversationError,
    utc,
)
from ac_platform.conversation_intelligence.models import ConversationAnalysisSettings
from ac_platform.conversation_intelligence.provider_admin import (
    ConversationProviderAdmin,
    lock_provider_configuration,
)
from ac_platform.kernel.authz import ActorContext


class ConversationAnalysisSettingsAdmin:
    def __init__(self, application: ConversationApplication, *, operations_tenant_id: UUID) -> None:
        if not isinstance(operations_tenant_id, UUID):
            raise ValueError("hosted_operations_tenant_required")
        self.application = application
        self.database = application.database
        self.operations_tenant_id = operations_tenant_id

    async def admit(self, actor: ActorContext) -> None:
        tenant_id = actor.tenant_id
        if tenant_id is None or tenant_id != self.operations_tenant_id:
            raise ConversationError("Use the AC operations workspace for analysis settings.")
        await ConversationProviderAdmin(self.application).admit(actor)

    async def current(self, actor: ActorContext) -> dict[str, Any]:
        await self.admit(actor)
        tenant_id = actor.tenant_id
        assert tenant_id is not None
        row, settings = await latest_analysis_settings(self.database, tenant_id)
        return settings_view(row, settings)

    async def history(
        self,
        actor: ActorContext,
        *,
        limit: int = 10,
        before_revision: int | None = None,
    ) -> dict[str, Any]:
        """Read bounded immutable revisions under the same authority as editing."""
        await self.admit(actor)
        if type(limit) is not int or not 1 <= limit <= 50:
            raise ConversationError("Use a history limit from 1 to 50.")
        if before_revision is not None and (
            type(before_revision) is not int or before_revision < 1
        ):
            raise ConversationError("Use a positive history revision.")
        query = select(ConversationAnalysisSettings).where(
            ConversationAnalysisSettings.tenant_id == actor.tenant_id
        )
        if before_revision is not None:
            query = query.where(ConversationAnalysisSettings.revision < before_revision)
        rows = list(
            (
                await self.database.scalars(
                    query.order_by(ConversationAnalysisSettings.revision.desc()).limit(limit + 1)
                )
            ).all()
        )
        page = rows[:limit]
        return {
            "items": [settings_view(row, settings_from_row(row)) for row in page],
            "next_before_revision": page[-1].revision if len(rows) > limit else None,
        }

    async def save(
        self,
        actor: ActorContext,
        settings: AnalysisSettings,
        *,
        expected_revision: int,
        key: str,
    ) -> dict[str, Any]:
        await self.admit(actor)
        if type(expected_revision) is not int or expected_revision < 0:
            raise ConversationError("Use the current analysis-settings revision.")
        tenant_id = actor.tenant_id
        assert tenant_id is not None
        await lock_provider_configuration(self.database, tenant_id)
        payload = {
            "settings": settings.model_dump(mode="json"),
            "expected_revision": expected_revision,
        }
        replay = await self.application._replay(
            actor, key, "conversation_analysis_settings", payload
        )
        if replay is not None and replay.result_id is not None:
            row = await self.database.get(ConversationAnalysisSettings, replay.result_id)
            if row is None or row.tenant_id != tenant_id:
                raise ConversationConflict("The saved analysis-settings receipt is unavailable.")
            return settings_view(row, settings)
        row = await self.database.scalar(
            select(ConversationAnalysisSettings)
            .where(ConversationAnalysisSettings.tenant_id == tenant_id)
            .order_by(ConversationAnalysisSettings.revision.desc())
            .limit(1)
            .with_for_update(read=True)
        )
        current_revision = 0 if row is None else row.revision
        if current_revision != expected_revision:
            raise ConversationConflict("Analysis settings changed. Reload before saving.")
        if (
            row is not None
            and row.c5_coaching_prompt_revision in {"coaching-v4", "coaching-v5"}
            and not {"c5_coaching_prompt_revision", "report_language_default"}.issubset(
                settings.model_fields_set
            )
        ):
            raise ConversationConflict(
                "Include the current report engine and language when saving."
            )
        revision = expected_revision + 1
        now = utc(self.application.clock())
        saved = ConversationAnalysisSettings(
            id=uuid4(),
            tenant_id=tenant_id,
            person_id=actor.person_id,
            session_id=actor.session_id,
            revision=revision,
            c4_max_requests=settings.c4_max_requests,
            c4_max_completion_tokens=settings.c4_max_completion_tokens,
            c5_max_completion_tokens=settings.c5_max_completion_tokens,
            c5_output_profile=settings.c5_output_profile,
            c5_coaching_prompt_revision=settings.c5_coaching_prompt_revision,
            report_language_default=settings.report_language_default,
            created_at=now,
        )
        self.database.add(saved)
        await self.database.flush()
        await self.application._receipt(
            actor,
            key,
            "conversation_analysis_settings",
            payload,
            saved.id,
            now,
            resource_type="conversation_analysis_settings",
        )
        return settings_view(saved, settings)


__all__ = ["ConversationAnalysisSettingsAdmin"]
