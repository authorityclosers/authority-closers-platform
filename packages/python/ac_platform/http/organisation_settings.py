"""Selected-tenant organisation details and sanitised logo endpoints."""

import hashlib
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, FastAPI, Request, Response
from fastapi.params import Depends
from pydantic import ConfigDict, Field
from starlette.concurrency import run_in_threadpool

from ac_platform.application.settings import Settings
from ac_platform.http.auth import AuthenticatedTransaction
from ac_platform.kernel.errors import AuthorizationDenied, ResourceNotFound
from ac_platform.media.errors import MediaBadRequest, MediaProcessingError, MediaStorageUnavailable
from ac_platform.media.local_avatar_processing import MAX_LOGO_BYTES, sanitize_organisation_logo
from ac_platform.media.local_avatar_runtime import LocalAvatarRuntime
from ac_platform.organisations.settings import (
    OrganisationDetails,
    OrganisationSettingsService,
    branding,
    logo_key,
    settings_result,
)
from ac_platform.tenancy.models import Organisation, Tenant


class OrganisationSettingsResponse(OrganisationDetails):
    model_config = ConfigDict(extra="forbid", strict=True)
    tenant_id: UUID = Field(strict=False)
    logo_url: str | None


def install_organisation_settings_routes(
    router: APIRouter,
    application: FastAPI,
    *,
    settings: Settings,
    selected_dependency: Depends,
    command_dependency: Depends,
) -> None:
    def service(auth: AuthenticatedTransaction) -> OrganisationSettingsService:
        assert settings.operations_tenant_id is not None
        assert settings.public_learner_tenant_id is not None
        return OrganisationSettingsService(
            auth.database,
            operations_tenant_id=settings.operations_tenant_id,
            public_learner_tenant_id=settings.public_learner_tenant_id,
        )

    async def rows(auth: AuthenticatedTransaction) -> tuple[Tenant, Organisation]:
        tenant_id = auth.resolved.actor.tenant_id
        tenant = await auth.database.get(Tenant, tenant_id)
        organisation = await auth.database.get(Organisation, tenant_id)
        assert tenant is not None and organisation is not None
        return tenant, organisation

    def avatar() -> LocalAvatarRuntime:
        runtime = getattr(application.state, "organisation_avatar_runtime", None)
        if not isinstance(runtime, LocalAvatarRuntime):
            raise MediaStorageUnavailable("Organisation logo storage is unavailable.")
        return runtime

    @router.get("/settings", response_model=OrganisationSettingsResponse)
    async def read_settings(
        auth: Annotated[AuthenticatedTransaction, selected_dependency],
    ) -> OrganisationSettingsResponse:
        if auth.resolved.membership_role not in {"owner", "admin"}:
            raise AuthorizationDenied("Only owners and admins can read organisation settings.")
        return OrganisationSettingsResponse.model_validate(settings_result(*await rows(auth)))

    @router.get("/branding")
    async def read_branding(
        auth: Annotated[AuthenticatedTransaction, selected_dependency],
    ) -> dict[str, object]:
        return branding(*await rows(auth))

    @router.put("/settings", response_model=OrganisationSettingsResponse)
    async def write_settings(
        body: OrganisationDetails,
        auth: Annotated[AuthenticatedTransaction, selected_dependency],
        key: Annotated[UUID, command_dependency],
    ) -> OrganisationSettingsResponse:
        actor = auth.resolved.actor
        assert actor.tenant_id is not None
        result = await service(auth).save(
            actor.tenant_id, key, actor_person_id=actor.person_id, details=body
        )
        return OrganisationSettingsResponse.model_validate(result)

    @router.put("/logo", response_model=OrganisationSettingsResponse)
    async def write_logo(
        request: Request,
        auth: Annotated[AuthenticatedTransaction, selected_dependency],
        key: Annotated[UUID, command_dependency],
    ) -> OrganisationSettingsResponse:
        actor = auth.resolved.actor
        assert actor.tenant_id is not None
        commands = service(auth)
        await commands.authorize_edit(actor.tenant_id, actor.person_id)
        runtime = avatar()
        body = bytearray()
        async for chunk in request.stream():
            if len(body) + len(chunk) > MAX_LOGO_BYTES:
                raise MediaBadRequest("Organisation logos must be at most 2 MB.")
            body.extend(chunk)
        content_type = request.headers.get("content-type", "")
        try:
            pixels = await run_in_threadpool(sanitize_organisation_logo, bytes(body), content_type)
        except MediaProcessingError as error:
            raise MediaBadRequest("Use a valid still PNG, JPG or WebP image up to 2 MB.") from error
        object_key = logo_key(actor.tenant_id, key)

        def store_and_scan() -> None:
            metadata = runtime.storage.put(
                object_key=object_key, body=pixels, content_type="image/webp"
            )
            result = runtime.service.scanner.scan(
                storage=runtime.storage,
                object_key=object_key,
                declared_content_type="image/webp",
                content_length=len(pixels),
                checksum_sha256=metadata.checksum_sha256,
            )
            if not result.clean or result.verified_checksum_sha256 != metadata.checksum_sha256:
                raise MediaBadRequest("The organisation logo failed image inspection.")

        await run_in_threadpool(store_and_scan)
        result = await commands.save(
            actor.tenant_id,
            key,
            actor_person_id=actor.person_id,
            logo_id=key,
            image_sha256=hashlib.sha256(body).hexdigest(),
        )
        return OrganisationSettingsResponse.model_validate(result)

    @router.get("/logo/{logo_id}")
    async def read_logo(
        logo_id: UUID, auth: Annotated[AuthenticatedTransaction, selected_dependency]
    ) -> Response:
        tenant, organisation = await rows(auth)
        if organisation.logo_id != logo_id:
            raise ResourceNotFound("Organisation logo is unavailable.")
        body = await run_in_threadpool(avatar().storage.read, logo_key(tenant.id, logo_id))
        return Response(
            content=body,
            media_type="image/webp",
            headers={
                "cache-control": "private, no-store",
                "vary": "Cookie",
                "x-content-type-options": "nosniff",
                "cross-origin-resource-policy": "same-origin",
            },
        )
