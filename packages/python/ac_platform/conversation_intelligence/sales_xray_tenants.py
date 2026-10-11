"""Presentation enablement derived from the composed Sales Xray intake."""

from __future__ import annotations

from typing import TYPE_CHECKING
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ac_platform.application.settings import Settings
from ac_platform.tenancy.models import Organisation, Tenant

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


async def sales_xray_served_tenant_ids(
    settings: Settings, intake: ConversationIntakeRuntime | None, database: AsyncSession
) -> frozenset[UUID]:
    """Personal plus every active registered organisation, excluding operations.

    Availability comes from the live registry, independently of provider approval.
    Query per request so creation and suspension never need an API restart.
    """

    rows = await database.scalars(
        select(Organisation.tenant_id)
        .join(Tenant, Tenant.id == Organisation.tenant_id)
        .where(Tenant.status == "active")
    )
    tenant_ids = set(rows.all())
    if settings.public_learner_tenant_id is not None:
        tenant_ids.add(settings.public_learner_tenant_id)
    tenant_ids.discard(settings.operations_tenant_id)
    return frozenset(tenant_ids)


async def sales_xray_workspace_served(
    database: AsyncSession, settings: Settings, tenant_id: UUID | None
) -> bool:
    """Resolve selected workspace eligibility without loading the whole registry."""
    if tenant_id is None or tenant_id == settings.operations_tenant_id:
        return False
    if tenant_id == settings.public_learner_tenant_id:
        return True
    return (
        await database.scalar(
            select(Organisation.tenant_id)
            .join(Tenant, Tenant.id == Organisation.tenant_id)
            .where(Organisation.tenant_id == tenant_id, Tenant.status == "active")
        )
        is not None
    )
