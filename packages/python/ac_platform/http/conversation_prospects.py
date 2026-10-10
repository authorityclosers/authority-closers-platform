"""Private session/workspace prospect reads and explicit audited call links."""

import asyncio
from contextlib import asynccontextmanager
from typing import Any
from uuid import UUID

from fastapi import APIRouter, FastAPI, HTTPException, Query, Request, Response
from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator
from starlette.requests import ClientDisconnect

from ac_platform.application.settings import Settings
from ac_platform.conversation_intelligence.application import ConversationError
from ac_platform.conversation_intelligence.guest_ownership import GuestOwnership
from ac_platform.conversation_intelligence.prospect_fields import field_registry, validate_fields
from ac_platform.conversation_intelligence.prospect_library import ProspectLibrary, profile
from ac_platform.conversation_intelligence.prospect_store import ProspectStore, validated_tags
from ac_platform.conversation_intelligence.prospect_suggestions import (
    SCHEMA,
    membership_json,
    suggestions,
)
from ac_platform.conversation_intelligence.sales_xray_tenants import WORKSPACE_UNAVAILABLE_MESSAGE
from ac_platform.http.auth import RequireActor, require_safe_origin
from ac_platform.http.conversation_acquisition import Factory
from ac_platform.kernel.errors import DomainError

_PRIVATE = {"Cache-Control": "private, no-store", "Vary": "Cookie"}


class _Create(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    display_name: str = Field(min_length=1, max_length=160)


class _Confirm(BaseModel):
    model_config = ConfigDict(extra="forbid")
    prospect_id: UUID
    expected_membership_id: UUID | None


class _Edit(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    display_name: str = Field(min_length=1, max_length=160)
    expected_revision: int = Field(gt=0)

    @field_validator("display_name")
    @classmethod
    def trim_name(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("Supply a valid prospect name.")
        return value.strip()


class _EditTags(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    tags: list[str] = Field(max_length=10)
    expected_revision: int = Field(gt=0)

    @field_validator("tags")
    @classmethod
    def trim_tags(cls, value: list[str]) -> list[str]:
        return validated_tags(value)


class _EditFields(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    expected_revision: int = Field(gt=0)
    fields: dict[str, Any]

    @field_validator("fields")
    @classmethod
    def validated_fields(cls, value: dict[str, Any]) -> dict[str, Any]:
        return validate_fields(value)


async def _body(request: Request, model: type[BaseModel]) -> Any:
    if request.headers.getlist("content-type") != ["application/json"]:
        raise HTTPException(415, "Use JSON to confirm a prospect.", headers=_PRIVATE)
    raw = bytearray()
    try:
        async with asyncio.timeout(5):
            async for chunk in request.stream():
                if len(raw) + len(chunk) > (40_000 if model is _EditFields else 2048):
                    raise HTTPException(413, "The prospect request is too large.", headers=_PRIVATE)
                raw.extend(chunk)
        return model.model_validate_json(bytes(raw))
    except (ValidationError, ValueError):
        raise HTTPException(422, "Supply a valid prospect request.", headers=_PRIVATE) from None
    except (TimeoutError, ClientDisconnect):
        raise HTTPException(408, "Try the prospect request again.", headers=_PRIVATE) from None


def install_prospect_http(
    application: FastAPI,
    *,
    settings: Settings,
    require_actor: RequireActor,
    factory: Factory,
    served: frozenset[UUID],
) -> None:
    router = APIRouter(prefix="/v1/conversation/prospects", tags=["conversation-prospects"])
    read_actor = getattr(require_actor, "read_only", require_actor)

    async def call_link(
        request: Request,
        response: Response,
        submission_id: UUID,
        *,
        operation: str = "suggest",
        offset: int = 0,
    ) -> Any:
        response.headers.update(_PRIVATE)
        if (
            settings.sales_xray_app_url is None
            or request.url.hostname != settings.sales_xray_app_url.host
        ):
            raise HTTPException(404, "Prospects are unavailable.", headers=_PRIVATE)
        allowed = {"offset"} if operation == "suggest" else set()
        if any(
            key not in allowed or len(request.query_params.getlist(key)) != 1
            for key in request.query_params
        ):
            raise HTTPException(422, "Use the current call and workspace.", headers=_PRIVATE)
        body = None
        if operation != "suggest":
            try:
                require_safe_origin(request, settings)
            except DomainError:
                raise HTTPException(
                    403, "Confirm from this Sales Xray page.", headers=_PRIVATE
                ) from None
            body = await _body(request, _Create if operation == "create" else _Confirm)
        try:
            async with asynccontextmanager(read_actor if operation == "suggest" else require_actor)(
                request
            ) as auth:
                actor = auth.resolved.actor
                if actor.tenant_id is None or actor.tenant_id not in served:
                    raise HTTPException(403, WORKSPACE_UNAVAILABLE_MESSAGE, headers=_PRIVATE)
                sessions = factory(auth.database, actor.tenant_id)
                if sessions.tenant_id != actor.tenant_id:
                    raise RuntimeError("Prospect links must use the selected workspace.")
                store = ProspectStore(GuestOwnership(sessions))
                if operation == "suggest":
                    return await suggestions(store, actor, submission_id, offset=offset)
                if isinstance(body, _Create):
                    await store.create_from_call(
                        actor, submission_id, display_name=body.display_name
                    )
                    member = await store._active(await store._write_scope(actor, submission_id))
                else:
                    assert isinstance(body, _Confirm)
                    member = await store.confirm_link(
                        actor,
                        submission_id,
                        body.prospect_id,
                        expected_membership_id=body.expected_membership_id,
                    )
                return {
                    "schema": SCHEMA,
                    "submission_id": str(submission_id),
                    "membership": membership_json(member),
                }
        except ConversationError as error:
            raise HTTPException(error.status, str(error), headers=_PRIVATE) from None
        except DomainError:
            raise HTTPException(
                401, "Sign in to confirm your prospect.", headers=_PRIVATE
            ) from None

    @router.get("/calls/{submission_id}/suggestions")
    async def suggested_links(
        submission_id: UUID,
        request: Request,
        response: Response,
        offset: int = Query(0, ge=0, le=100_000),
    ) -> Any:
        return await call_link(request, response, submission_id, offset=offset)

    @router.post("/calls/{submission_id}/confirm")
    async def confirm_link(submission_id: UUID, request: Request, response: Response) -> Any:
        return await call_link(request, response, submission_id, operation="confirm")

    @router.post("/calls/{submission_id}/create", status_code=201)
    async def create_prospect(submission_id: UUID, request: Request, response: Response) -> Any:
        return await call_link(request, response, submission_id, operation="create")

    async def edit(
        prospect_id: str,
        request: Request,
        response: Response,
        *,
        tags: bool = False,
        fields: bool = False,
    ) -> Any:
        response.headers.update(_PRIVATE)
        if (
            settings.sales_xray_app_url is None
            or request.url.hostname != settings.sales_xray_app_url.host
        ):
            raise HTTPException(404, "Prospects are unavailable.", headers=_PRIVATE)
        if request.query_params:
            raise HTTPException(422, "Use the current prospect and workspace.", headers=_PRIVATE)
        try:
            target = UUID(prospect_id)
        except ValueError:
            raise HTTPException(422, "Supply a valid prospect request.", headers=_PRIVATE) from None
        try:
            require_safe_origin(request, settings)
        except DomainError:
            raise HTTPException(403, "Save from this Sales Xray page.", headers=_PRIVATE) from None
        body = await _body(request, _EditFields if fields else _EditTags if tags else _Edit)
        try:
            async with asynccontextmanager(require_actor)(request) as auth:
                actor = auth.resolved.actor
                if actor.tenant_id is None or actor.tenant_id not in served:
                    raise HTTPException(403, WORKSPACE_UNAVAILABLE_MESSAGE, headers=_PRIVATE)
                sessions = factory(auth.database, actor.tenant_id)
                if sessions.tenant_id != actor.tenant_id:
                    raise RuntimeError("Prospect edits must use the selected workspace.")
                store = ProspectStore(GuestOwnership(sessions))
                if fields:
                    row, history = await store.edit_fields_and_read(
                        actor, target, fields=body.fields, expected_revision=body.expected_revision
                    )
                    return {
                        "schema": "ac.sales-xray.prospect-fields/1",
                        "field_registry": field_registry(),
                        "prospect": profile(row, list(history)),
                    }
                if tags:
                    row = await store.edit_tags(
                        actor, target, tags=body.tags, expected_revision=body.expected_revision
                    )
                else:
                    row = await store.edit_name(
                        actor,
                        target,
                        display_name=body.display_name,
                        expected_revision=body.expected_revision,
                    )
                return {
                    "schema": "ac.sales-xray.prospect-tags/1"
                    if tags
                    else "ac.sales-xray.prospect-name/1",
                    "prospect": {
                        "prospect_id": str(row.id),
                        **({"tags": row.tags} if tags else {"name": row.display_name}),
                        "revision": row.revision,
                    },
                }
        except ConversationError as error:
            raise HTTPException(error.status, str(error), headers=_PRIVATE) from None
        except DomainError:
            raise HTTPException(401, "Sign in to edit your prospect.", headers=_PRIVATE) from None

    @router.patch("/{prospect_id}")
    async def edit_name(prospect_id: str, request: Request, response: Response) -> Any:
        return await edit(prospect_id, request, response)

    @router.patch("/{prospect_id}/tags")
    async def edit_tags(prospect_id: str, request: Request, response: Response) -> Any:
        return await edit(prospect_id, request, response, tags=True)

    @router.put("/{prospect_id}/fields")
    async def edit_fields(prospect_id: str, request: Request, response: Response) -> Any:
        return await edit(prospect_id, request, response, fields=True)

    async def read(
        request: Request,
        response: Response,
        *,
        prospect_id: UUID | None = None,
        search: str = "",
        stage: str | None = None,
        offset: int = 0,
    ) -> Any:
        response.headers.update(_PRIVATE)
        if (
            settings.sales_xray_app_url is None
            or request.url.hostname != settings.sales_xray_app_url.host
        ):
            raise HTTPException(404, "Prospects are unavailable.", headers=_PRIVATE)
        allowed = {"offset"} if prospect_id is not None else {"search", "stage", "offset"}
        if any(
            key not in allowed or len(request.query_params.getlist(key)) != 1
            for key in request.query_params
        ):
            raise HTTPException(422, "Use the prospect page's supported filters.", headers=_PRIVATE)
        try:
            async with asynccontextmanager(read_actor)(request) as auth:
                actor = auth.resolved.actor
                if actor.tenant_id is None or actor.tenant_id not in served:
                    raise HTTPException(403, WORKSPACE_UNAVAILABLE_MESSAGE, headers=_PRIVATE)
                sessions = factory(auth.database, actor.tenant_id)
                if sessions.tenant_id != actor.tenant_id:
                    raise RuntimeError("Prospects must use the selected workspace.")
                return await ProspectLibrary(ProspectStore(GuestOwnership(sessions))).read(
                    actor, prospect_id=prospect_id, search=search, stage=stage, offset=offset
                )
        except ConversationError as error:
            raise HTTPException(error.status, str(error), headers=_PRIVATE) from None
        except DomainError:
            raise HTTPException(401, "Sign in to read your prospects.", headers=_PRIVATE) from None

    @router.get("")
    async def listing(
        request: Request,
        response: Response,
        search: str = Query("", max_length=160),
        stage: str | None = Query(None, max_length=160),
        offset: int = Query(0, ge=0, le=100_000),
    ) -> Any:
        return await read(request, response, search=search, stage=stage, offset=offset)

    @router.get("/{prospect_id}")
    async def detail(
        prospect_id: UUID,
        request: Request,
        response: Response,
        offset: int = Query(0, ge=0, le=100_000),
    ) -> Any:
        return await read(request, response, prospect_id=prospect_id, offset=offset)

    application.include_router(router)
