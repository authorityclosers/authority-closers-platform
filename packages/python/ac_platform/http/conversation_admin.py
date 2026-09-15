"""Separate admin-only provider settings; no inference or secret-value input."""

from __future__ import annotations

from typing import Annotated, Any
from uuid import UUID

from fastapi import APIRouter, Depends, FastAPI, Header, HTTPException, Query, Request, Response
from pydantic import BaseModel, ConfigDict, Field

from ac_platform.application.settings import Settings
from ac_platform.conversation_intelligence.admin_recordings import AdminConversationRecordings
from ac_platform.conversation_intelligence.admin_reports import AdminConversationReports
from ac_platform.conversation_intelligence.analysis_settings import AnalysisSettings
from ac_platform.conversation_intelligence.analysis_settings_admin import (
    ConversationAnalysisSettingsAdmin,
)
from ac_platform.conversation_intelligence.application import (
    ConversationApplication,
    ConversationError,
)
from ac_platform.conversation_intelligence.hosted_runtime import load_pinned_approval
from ac_platform.conversation_intelligence.internal_tester import internal_tester_view
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
from ac_platform.conversation_intelligence.retained_c5_recovery import (
    RetainedC5CorrectionIntent,
    RetainedC5RecoveryService,
    RetainedC5RevalidationIntent,
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


class ProviderActivationIntent(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    expected_revision: int = Field(ge=0, lt=2_147_483_647)
    target_revision: int = Field(ge=1, lt=2_147_483_647)


class AnalysisSettingsIntent(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    expected_revision: int = Field(ge=0, lt=2_147_483_647)
    settings: AnalysisSettings


def install_conversation_admin_http(
    app: FastAPI,
    *,
    settings: Settings,
    require_actor: RequireActor,
    import_storage: PrivateLocalRecordingStorage | None = None,
    recovery_storage: PrivateLocalRecordingStorage | None = None,
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
            bundle = None
            if settings.sales_xray_enabled and settings.sales_xray_approval_path:
                try:
                    bundle = load_pinned_approval(settings)
                except ValueError:
                    # The settings surface remains readable while activation
                    # stays unavailable until the release approval is present.
                    bundle = None
            current = await service.current(auth.resolved.actor, bundle=bundle)
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
            "approved_budget_cap_paise": None if bundle is None else bundle.budget_cap_paise,
            "execution_activated": bool(current and current.get("activation")),
            "internal_tester_policy": internal_tester_view(bundle)
            if bundle is not None
            else {
                "enabled": False,
                "accounts": [],
                "scopes": [],
                "source": "hash_pinned_hosted_approval",
                "bundle_digest": None,
                "limits_remaining_bounded": [
                    "provider_stage_approval",
                    "provider_budget_and_usage",
                    "source_size_and_retention_storage",
                    "guest_session_ip_rate_limit_without_named_account_session",
                ],
            },
            "message": (
                "Settings are saved as revisions. Activate a pinned-approved revision "
                "for new plans; provider calls remain worker-owned."
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
            recording_tenant_ids = (
                (settings.public_learner_tenant_id,)
                if settings.public_learner_tenant_id is not None
                else ()
            )
            return await AdminConversationRecordings(
                ConversationApplication(auth.database),
                operations_tenant_id,
                recording_tenant_ids=recording_tenant_ids,
                recovery_enabled=recovery_storage is not None,
            ).list(
                auth.resolved.actor,
                limit=limit,
                cursor=cursor,
                search=search,
            )
        except ConversationError as error:
            raise HTTPException(error.status, str(error)) from None

    @router.get("/runs/{run_id}/report")
    async def admin_report(
        run_id: UUID,
        request: Request,
        response: Response,
        auth: AuthenticatedTransaction = dependency,
    ) -> dict[str, Any]:
        """Open a retained report for an authorized operations reviewer."""

        surface(request, response)
        operations_tenant_id = settings.operations_tenant_id
        if operations_tenant_id is None:
            raise HTTPException(503, "Conversation reports are not configured.")
        try:
            recording_tenant_ids = (
                (settings.public_learner_tenant_id,)
                if settings.public_learner_tenant_id is not None
                else ()
            )
            if recovery_storage is not None:
                recovered = await RetainedC5RecoveryService(
                    ConversationApplication(auth.database),
                    operations_tenant_id=operations_tenant_id,
                    recording_tenant_ids=recording_tenant_ids,
                ).admin_report(auth.resolved.actor, run_id)
                if recovered is not None:
                    return recovered
            return await AdminConversationReports(
                ConversationApplication(auth.database),
                operations_tenant_id,
                recording_tenant_ids=recording_tenant_ids,
            ).get(auth.resolved.actor, run_id)
        except ConversationError as error:
            raise HTTPException(error.status, str(error)) from None

    @router.get("/analysis-settings")
    async def analysis_settings(
        request: Request,
        response: Response,
        auth: AuthenticatedTransaction = dependency,
    ) -> dict[str, Any]:
        surface(request, response)
        operations_tenant_id = settings.operations_tenant_id
        if operations_tenant_id is None:
            raise HTTPException(503, "Analysis settings are not configured.")
        try:
            return await ConversationAnalysisSettingsAdmin(
                ConversationApplication(auth.database),
                operations_tenant_id=operations_tenant_id,
            ).current(auth.resolved.actor)
        except ConversationError as error:
            raise HTTPException(error.status, str(error)) from None

    @router.post("/analysis-settings", status_code=201)
    async def save_analysis_settings(
        intent: AnalysisSettingsIntent,
        request: Request,
        response: Response,
        key: Annotated[str, Header(alias="Idempotency-Key", min_length=1, max_length=128)],
        auth: AuthenticatedTransaction = dependency,
    ) -> dict[str, Any]:
        surface(request, response)
        require_safe_origin(request, settings)
        operations_tenant_id = settings.operations_tenant_id
        if operations_tenant_id is None:
            raise HTTPException(503, "Analysis settings are not configured.")
        try:
            return await ConversationAnalysisSettingsAdmin(
                ConversationApplication(auth.database),
                operations_tenant_id=operations_tenant_id,
            ).save(
                auth.resolved.actor,
                intent.settings,
                expected_revision=intent.expected_revision,
                key=key,
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
            service = ConversationProviderAdmin(ConversationApplication(auth.database))
            saved = await service.save(
                auth.resolved.actor,
                intent.configuration,
                expected_revision=intent.expected_revision,
                key=key,
            )
            bundle = None
            if settings.sales_xray_enabled and settings.sales_xray_approval_path:
                try:
                    bundle = load_pinned_approval(settings)
                except ValueError:
                    bundle = None
            current = await service.current(auth.resolved.actor, bundle=bundle)
            return current or saved
        except ConversationError as error:
            raise HTTPException(error.status, str(error)) from None

    @router.post("/providers/activate", status_code=200)
    async def activate_providers(
        intent: ProviderActivationIntent,
        request: Request,
        response: Response,
        key: Annotated[str, Header(alias="Idempotency-Key", min_length=1, max_length=128)],
        auth: AuthenticatedTransaction = dependency,
    ) -> dict[str, Any]:
        surface(request, response)
        require_safe_origin(request, settings)
        if not settings.sales_xray_enabled:
            raise HTTPException(503, "Provider activation is not enabled in this release.")
        try:
            bundle = load_pinned_approval(settings)
        except ValueError:
            raise HTTPException(503, "The pinned provider approval is unavailable.") from None
        try:
            return await ConversationProviderAdmin(ConversationApplication(auth.database)).activate(
                auth.resolved.actor,
                target_revision=intent.target_revision,
                expected_revision=intent.expected_revision,
                key=key,
                bundle=bundle,
            )
        except ConversationError as error:
            raise HTTPException(error.status, str(error)) from None

    if recovery_storage is not None:

        @router.post("/runs/{run_id}/retained-c5/revalidate", status_code=201)
        async def revalidate_retained_c5(
            run_id: UUID,
            intent: RetainedC5RevalidationIntent,
            request: Request,
            response: Response,
            key: Annotated[str, Header(alias="Idempotency-Key", min_length=1, max_length=128)],
            auth: AuthenticatedTransaction = dependency,
        ) -> dict[str, Any]:
            surface(request, response)
            require_safe_origin(request, settings)
            operations_tenant_id = settings.operations_tenant_id
            if operations_tenant_id is None:
                raise HTTPException(503, "Conversation recovery is not configured.")
            try:
                return await RetainedC5RecoveryService(
                    ConversationApplication(auth.database),
                    operations_tenant_id=operations_tenant_id,
                    recording_tenant_ids=(
                        (settings.public_learner_tenant_id,)
                        if settings.public_learner_tenant_id is not None
                        else ()
                    ),
                ).revalidate(
                    auth.resolved.actor,
                    run_id,
                    original_raw_sha256=intent.original_raw_sha256,
                    key=key,
                    storage=recovery_storage,
                )
            except ConversationError as error:
                raise HTTPException(error.status, str(error)) from None

        @router.post("/runs/{run_id}/retained-c5/correct", status_code=201)
        async def correct_retained_c5(
            run_id: UUID,
            intent: RetainedC5CorrectionIntent,
            request: Request,
            response: Response,
            key: Annotated[str, Header(alias="Idempotency-Key", min_length=1, max_length=128)],
            auth: AuthenticatedTransaction = dependency,
        ) -> dict[str, Any]:
            surface(request, response)
            require_safe_origin(request, settings)
            operations_tenant_id = settings.operations_tenant_id
            if operations_tenant_id is None:
                raise HTTPException(503, "Conversation recovery is not configured.")
            try:
                return await RetainedC5RecoveryService(
                    ConversationApplication(auth.database),
                    operations_tenant_id=operations_tenant_id,
                    recording_tenant_ids=(
                        (settings.public_learner_tenant_id,)
                        if settings.public_learner_tenant_id is not None
                        else ()
                    ),
                ).revalidate(
                    auth.resolved.actor,
                    run_id,
                    original_raw_sha256=intent.original_raw_sha256,
                    key=key,
                    storage=recovery_storage,
                    correction=intent,
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
