"""Organisation display settings over the existing transaction and audit path."""

from typing import cast
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select
from sqlalchemy.exc import DBAPIError

from ac_platform.kernel.errors import AuthorizationDenied, ResourceConflict
from ac_platform.organisations.service import OrganisationCommandError, OrganisationService
from ac_platform.tenancy.models import Organisation, Tenant


class OrganisationDetails(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, str_strip_whitespace=True)
    name: str = Field(min_length=2, max_length=80)
    legal_name: str = Field(default="", max_length=200)
    gstin: str = Field(default="", max_length=32)
    address: str = Field(default="", max_length=1000)
    industry: str = Field(default="", max_length=100)
    team_size: str = Field(default="", max_length=80)
    website: str = Field(default="", max_length=500)
    city: str = Field(default="", max_length=100)


def logo_key(tenant_id: UUID, logo_id: UUID) -> str:
    # Organisation logos share the avatar store's immutable namespace.
    return f"tenants/{tenant_id}/media/avatar/{tenant_id}/{logo_id}/original/avatar/512"


def branding(tenant: Tenant, organisation: Organisation | None) -> dict[str, object]:
    return {
        "tenant_id": str(tenant.id),
        "name": tenant.name,
        "logo_url": (
            f"/v1/organisation/logo/{organisation.logo_id}"
            if organisation is not None and organisation.logo_id
            else None
        ),
    }


def settings_result(tenant: Tenant, organisation: Organisation) -> dict[str, object]:
    return {
        **OrganisationDetails(name=tenant.name, **organisation.details).model_dump(),
        **branding(tenant, organisation),
    }


class OrganisationSettingsService(OrganisationService):
    async def authorize_edit(self, tenant_id: UUID, actor_person_id: UUID) -> Organisation:
        if (await self._actor(tenant_id, actor_person_id)).role not in {"owner", "admin"}:
            raise AuthorizationDenied("Only owners and admins can change organisation settings.")
        # The registry lock is held; refresh values loaded earlier by authentication.
        row = await self.session.scalar(
            select(Organisation)
            .where(Organisation.tenant_id == tenant_id)
            .execution_options(populate_existing=True)
        )
        assert row is not None
        return row

    async def save(
        self,
        tenant_id: UUID,
        command_id: UUID,
        *,
        actor_person_id: UUID,
        details: OrganisationDetails | None = None,
        logo_id: UUID | None = None,
        image_sha256: str = "",
    ) -> dict[str, object]:
        organisation = await self.authorize_edit(tenant_id, actor_person_id)
        if (details is None) == (logo_id is None):
            raise OrganisationCommandError("Choose one organisation settings change.")
        action = "organisation.details_changed" if details else "organisation.logo_changed"
        intent = {
            "action": action,
            "actor_person_id": str(actor_person_id),
            "details": details.model_dump_json() if details else "",
            "image_sha256": image_sha256,
        }
        prior = await self._replay(tenant_id, command_id, intent)
        if prior is not None:
            return cast(dict[str, object], prior.payload["result"])
        try:
            # Name changes upgrade authentication's shared tenant fence; never wait in a cycle.
            tenant = await self.session.scalar(
                select(Tenant)
                .where(Tenant.id == tenant_id)
                .with_for_update(nowait=True)
                .execution_options(populate_existing=True)
            )
        except DBAPIError as error:
            if getattr(error.orig, "sqlstate", None) == "55P03":
                raise ResourceConflict("Organisation is busy; retry with the same key.") from error
            raise
        assert tenant is not None
        before = settings_result(tenant, organisation)
        if details is not None:
            tenant.name = details.name
            organisation.details = details.model_dump(exclude={"name"})
        else:
            organisation.logo_id = logo_id
        tenant.revision += 1
        await self.session.flush()
        result = settings_result(tenant, organisation)
        await self._audit(
            tenant_id,
            command_id,
            action,
            "organisation",
            tenant_id,
            {"http_intent": intent, "result": result, "before": before, "after": result},
            None,
            actor_person_id=actor_person_id,
        )
        return result
