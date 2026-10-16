"""Read-only Sales Xray directory; listing never selects a session context."""

from __future__ import annotations

from typing import Literal
from uuid import UUID

from fastapi import APIRouter, Depends, FastAPI, HTTPException, Request, Response
from pydantic import BaseModel, ConfigDict
from sqlalchemy import text

from ac_platform.application.settings import Settings
from ac_platform.conversation_intelligence.sales_xray_tenants import sales_xray_served_tenant_ids
from ac_platform.http.auth import AuthenticatedTransaction, RequireActor
from ac_platform.http.conversation_intake import ConversationIntakeRuntime
from ac_platform.kernel.errors import DomainError


class SalesXrayWorkspaceResponse(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    tenant_id: UUID
    kind: Literal["personal", "organisation"]
    name: str
    role: Literal["owner", "admin", "member"] | None
    sales_xray_enabled: bool


class SalesXrayWorkspacesResponse(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    selected_tenant_id: UUID | None
    workspaces: list[SalesXrayWorkspaceResponse]


class SalesXrayCallWorkspaceResponse(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    tenant_id: UUID


# The workspace holding one saved call; joins mirror the account library scope.
_CALL_HOME = text(
    """
    SELECT s.tenant_id, coalesce(u.person_id, c.person_id) AS owner_id
    FROM conversation_guest_submissions s
    JOIN conversation_acquisition_usage u
      ON u.id = s.usage_id AND u.tenant_id = s.tenant_id
     AND u.submission_id = s.submission_id
    LEFT JOIN conversation_visitor_claims c
      ON c.visitor_id = u.visitor_id AND c.tenant_id = u.tenant_id
    JOIN conversation_recordings r
      ON r.id = s.recording_id AND r.tenant_id = s.tenant_id
    WHERE s.submission_id = :submission AND r.state IN ('awaiting_upload', 'ready')
    """
)


def install_sales_xray_workspaces_http(
    application: FastAPI,
    *,
    settings: Settings,
    require_actor: RequireActor,
    intake: ConversationIntakeRuntime | None,
) -> None:
    router = APIRouter(prefix="/v1/me/sales-xray-workspaces", tags=["sales-xray-workspaces"])
    read_actor_dependency = Depends(require_actor.read_only, scope="function")  # type: ignore[attr-defined]

    async def choices_for(auth: AuthenticatedTransaction) -> list[SalesXrayWorkspaceResponse]:
        enabled = await sales_xray_served_tenant_ids(settings, intake, auth.database)
        public, operations = settings.public_learner_tenant_id, settings.operations_tenant_id
        choices = [
            SalesXrayWorkspaceResponse(
                tenant_id=tenant_id,
                kind="organisation",
                name=name,
                role="owner" if role == "owner" else "admin" if role == "admin" else "member",
                sales_xray_enabled=tenant_id in enabled,
            )
            for tenant_id, name, role in await auth.identity.repository.list_active_organisations(
                auth.resolved.actor.person_id
            )
            if tenant_id not in {public, operations}
        ]
        if public is not None and public != operations:
            choices.insert(
                0,
                SalesXrayWorkspaceResponse(
                    tenant_id=public,
                    kind="personal",
                    name="Personal",
                    role=None,
                    sales_xray_enabled=public in enabled,
                ),
            )
        return choices

    def private(response: Response) -> None:
        response.headers["cache-control"] = "private, no-store"
        response.headers["pragma"] = "no-cache"
        response.headers["vary"] = "Cookie"

    @router.get("", response_model=SalesXrayWorkspacesResponse)
    async def workspaces(
        request: Request,
        response: Response,
        auth: AuthenticatedTransaction = read_actor_dependency,
    ) -> SalesXrayWorkspacesResponse:
        if request.query_params:
            raise DomainError("Workspaces are resolved only for the authenticated person.")
        choices = await choices_for(auth)
        selected = auth.resolved.actor.tenant_id
        private(response)
        return SalesXrayWorkspacesResponse(
            selected_tenant_id=selected if selected in {c.tenant_id for c in choices} else None,
            workspaces=choices,
        )

    @router.get("/call/{submission_id}", response_model=SalesXrayCallWorkspaceResponse)
    async def call_workspace(
        submission_id: UUID,
        request: Request,
        response: Response,
        auth: AuthenticatedTransaction = read_actor_dependency,
    ) -> SalesXrayCallWorkspaceResponse:
        """Which of the person's Sales Xray workspaces holds a saved call (16 Oct).

        A link opened while another workspace is selected can then switch to the
        call's own workspace. Only a workspace the person belongs to and may read
        the call in is named: their own call, or any call there as an
        organisation owner or admin. Everything else is the same 404, so the
        answer says nothing about calls the person cannot read.
        """
        private(response)
        if request.query_params:
            raise DomainError("Workspaces are resolved only for the authenticated person.")
        missing = HTTPException(404, "Saved call not found.", headers={"cache-control": "no-store"})
        home = (await auth.database.execute(_CALL_HOME, {"submission": submission_id})).first()
        if home is None:
            raise missing
        workspace = next(
            (
                item
                for item in await choices_for(auth)
                if item.tenant_id == home.tenant_id and item.sales_xray_enabled
            ),
            None,
        )
        person = auth.resolved.actor.person_id
        readable = workspace is not None and (
            home.owner_id == person
            or (workspace.kind == "organisation" and workspace.role in {"owner", "admin"})
        )
        if not readable:
            raise missing
        return SalesXrayCallWorkspaceResponse(tenant_id=home.tenant_id)

    application.include_router(router)
