"""Platform admission is an explicit capability, never an academy role alias."""

from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ac_platform.authorization.application import CapabilityApplication
from ac_platform.authorization.models import PLATFORM_CAPABILITIES
from ac_platform.authorization.policy import CapabilityDenied
from ac_platform.kernel.authz import ActorContext
from ac_platform.tenancy.models import Tenant


async def platform_projection(
    database: AsyncSession, actor: ActorContext, *, operations_tenant_id: UUID | None
) -> frozenset[str]:
    """Fresh read under the authenticated caller's transaction and person lock.

    This read does not take the management fence after identity locks. Grant and
    revoke commands take that fence first and then the same subject Person lock.
    No selected academy or legacy role is needed or changed by this projection.
    """
    if operations_tenant_id is None:
        raise CapabilityDenied("Platform administration is not configured.")
    application = CapabilityApplication(database, operations_tenant_id=operations_tenant_id)
    grants = await application.active_grants(actor.person_id)
    await application._session(actor)
    operations = await database.scalar(
        select(Tenant)
        .where(Tenant.id == operations_tenant_id)
        .execution_options(populate_existing=True)
        .with_for_update(read=True)
    )
    if operations is None or operations.status != "active":
        raise CapabilityDenied("Platform administration is unavailable.")
    return frozenset(
        grant.permission
        for grant in grants
        if grant.permission in PLATFORM_CAPABILITIES
        and grant.scope_kind == "platform"
        and grant.tenant_id is None
        and grant.program_id is None
    )
