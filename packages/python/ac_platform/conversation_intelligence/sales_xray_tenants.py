"""Presentation enablement derived from the composed Sales Xray intake."""

from __future__ import annotations

from typing import TYPE_CHECKING
from uuid import UUID

from ac_platform.application.settings import Settings

if TYPE_CHECKING:
    from ac_platform.http.conversation_intake import ConversationIntakeRuntime


def sales_xray_tenant_ids(
    settings: Settings, intake: ConversationIntakeRuntime | None
) -> frozenset[UUID]:
    if intake is None:
        return frozenset()
    tenant_ids = set(intake.policy.tenant_ids)
    if settings.public_learner_tenant_id is not None:
        tenant_ids.add(settings.public_learner_tenant_id)
    tenant_ids.discard(settings.operations_tenant_id)
    return frozenset(tenant_ids)
