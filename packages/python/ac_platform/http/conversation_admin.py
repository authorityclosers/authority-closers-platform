"""Separate admin-only provider settings; no inference or secret-value input."""

from __future__ import annotations

from typing import Annotated, Any
from uuid import UUID

from fastapi import APIRouter, Depends, FastAPI, Header, HTTPException, Query, Request, Response
from pydantic import BaseModel, ConfigDict, Field

from ac_platform.application.settings import Settings
from ac_platform.conversation_intelligence.admin_recordings import AdminConversationRecordings
from ac_platform.conversation_intelligence.application import (
    ConversationApplication,
    ConversationError,
)
from ac_platform.conversation_intelligence.provider_admin import ConversationProviderAdmin
from ac_platform.conversation_intelligence.provider_registry import (
    TASK_CONTRACTS,
    RegistryConfig,
    RegistryPolicy,
    catalog_public_view,
)
from ac_platform.conversation_intelligence.report_store import (
    ConversationReports,
    PrivateDraftIntent,
)
from ac_platform.conversation_intelligence.storage import PrivateLocalRecordingStorage
from ac_platform.http.auth import (
    AuthenticatedTransaction,
    RequireActor,
    require_admin_surface,
    require_safe_origin,
)


class ProviderConfigurationIntent(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    expected_revision: int = Field(ge=0, lt=2_147_483_647)
    configuration: dict[str, Any]


def install_conversation_admin_http(
    app: FastAPI,
    *,
    settings: Settings,
    require_actor: RequireActor,
    import_storage: PrivateLocalRecordingStorage | None = None,
) -> None:
    if import_storage is not None and settings.environment not in {"local", "test"}:
        raise ValueError("Internal proof import is limited to the local test composition.")
    router = APIRouter(prefix="/v1/admin/conversation", tags=["conversation-admin"])
    dependency = Depends(require_actor, scope="function")

    def surface(request: Request, response: Response) -> None:
        require_admin_surface(request, settings)
        if request.query_params:
            raise HTTPException(422, "Provider settings use your current AC workspace.")
        response.headers["Cache-Control"] = "private, no-store"

    def recordings_surface(request: Request, response: Response) -> None:
        require_admin_surface(request, settings)
        response.headers["Cache-Control"] = "private, no-store"
        allowed = {"limit", "cursor", "q"}
        if set(request.query_params) - allowed or any(
            len(request.query_params.getlist(name)) != 1 for name in request.query_params
        ):
            raise HTTPException(422, "Recordings accepts one bounded limit, cursor, and search.")

    @router.get("/providers")
    async def providers(
        request: Request, response: Response, auth: AuthenticatedTransaction = dependency
    ) -> dict[str, Any]:
        surface(request, response)
        service = ConversationProviderAdmin(ConversationApplication(auth.database))
        try:
            current = await service.current(auth.resolved.actor)
        except ConversationError as error:
            raise HTTPException(error.status, str(error)) from None
        return {
            "catalog": catalog_public_view(),
            "tasks": [task.as_dict() for task in TASK_CONTRACTS],
            "configuration_template": RegistryConfig(
                revision="admin-draft-v1",
                policy=RegistryPolicy(),
                providers=(),
                routes=(),
            ).as_dict(),
            "current": current,
            "max_paid_paise": 0,
            "execution_activated": False,
            "message": (
                "Settings are saved as revisions. Provider tests and activation are separate."
            ),
        }

    @router.get("/recordings")
    async def recordings(
        request: Request,
        response: Response,
        limit: Annotated[int, Query(ge=1, le=50)] = 25,
        cursor: Annotated[str | None, Query(min_length=1, max_length=256)] = None,
        search: Annotated[str | None, Query(alias="q", max_length=120)] = None,
        auth: AuthenticatedTransaction = dependency,
    ) -> dict[str, Any]:
        recordings_surface(request, response)
        operations_tenant_id = settings.operations_tenant_id
        if operations_tenant_id is None:
            raise HTTPException(503, "Conversation recordings are not configured.")
        try:
            return await AdminConversationRecordings(
                ConversationApplication(auth.database), operations_tenant_id
            ).list(
                auth.resolved.actor,
                limit=limit,
                cursor=cursor,
                search=search,
            )
        except ConversationError as error:
            raise HTTPException(error.status, str(error)) from None

    @router.post("/providers", status_code=201)
    async def save_providers(
        intent: ProviderConfigurationIntent,
        request: Request,
        response: Response,
        key: Annotated[str, Header(alias="Idempotency-Key", min_length=1, max_length=128)],
        auth: AuthenticatedTransaction = dependency,
    ) -> dict[str, Any]:
        surface(request, response)
        require_safe_origin(request, settings)
        try:
            return await ConversationProviderAdmin(ConversationApplication(auth.database)).save(
                auth.resolved.actor,
                intent.configuration,
                expected_revision=intent.expected_revision,
                key=key,
            )
        except ConversationError as error:
            raise HTTPException(error.status, str(error)) from None

    if import_storage is not None:

        @router.post("/runs/{run_id}/draft", status_code=201)
        async def import_draft(
            run_id: UUID,
            intent: PrivateDraftIntent,
            request: Request,
            response: Response,
            key: Annotated[str, Header(alias="Idempotency-Key", min_length=1, max_length=128)],
            auth: AuthenticatedTransaction = dependency,
        ) -> dict[str, Any]:
            surface(request, response)
            require_safe_origin(request, settings)
            assert import_storage is not None
            try:
                return await ConversationReports(
                    ConversationApplication(auth.database)
                ).import_internal_draft(
                    auth.resolved.actor,
                    run_id,
                    intent,
                    storage=import_storage,
                    key=key,
                )
            except ConversationError as error:
                raise HTTPException(error.status, str(error)) from None

    app.include_router(router)
