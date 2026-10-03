"""Presentation enablement derived from the composed Sales Xray intake."""

from __future__ import annotations

from typing import TYPE_CHECKING
from uuid import UUID

from ac_platform.application.settings import Settings

if TYPE_CHECKING:
    from ac_platform.http.conversation_intake import ConversationIntakeRuntime

WORKSPACE_UNAVAILABLE_MESSAGE = "Sales Xray isn't available in this workspace."
CLAIM_PERSONAL_ONLY_MESSAGE = "Switch to Personal to claim this call."
# Memberships that may hold Sales Xray minutes: Personal learners and the
# human roles of an approved organisation. The shared processing identity never
# qualifies.
SALES_XRAY_MEMBER_ROLES: frozenset[str] = frozenset({"learner", "owner", "admin", "member"})
# The historical scope of minute administration outside a served tenant.
LEARNER_ROLES: frozenset[str] = frozenset({"learner"})


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


def sales_xray_served_tenant_ids(
    settings: Settings, intake: ConversationIntakeRuntime | None
) -> frozenset[UUID]:
    """The tenants a Sales Xray route serves: Personal plus the approved organisations.

    Personal is served whenever it is configured, with or without a composed
    intake; the operations tenant never is.
    """

    tenant_ids = set(sales_xray_tenant_ids(settings, intake))
    if settings.public_learner_tenant_id is not None:
        tenant_ids.add(settings.public_learner_tenant_id)
    tenant_ids.discard(settings.operations_tenant_id)
    return frozenset(tenant_ids)
