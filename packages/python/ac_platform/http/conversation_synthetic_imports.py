"""Private sandbox import uses the existing cookie, tenant, origin and profile gates."""

from __future__ import annotations

from collections.abc import AsyncIterator, Callable
from contextlib import asynccontextmanager
from typing import TYPE_CHECKING, Any

from fastapi import APIRouter, Header, Path, Request, Response

from ac_platform.conversation_intelligence.application import ConversationError
from ac_platform.conversation_intelligence.synthetic_import_contracts import (
    SYNTHETIC_KEY,
    SyntheticCallBundle,
    SyntheticRecordBatch,
)
from ac_platform.conversation_intelligence.synthetic_imports import SyntheticImports
from ac_platform.http.sales_xray_profile import require_sales_xray_write_profile

if TYPE_CHECKING:
    from ac_platform.conversation_intelligence.acquisition_source import NativeUploadPreflight
    from ac_platform.http.conversation_imports import _Guard
    from ac_platform.http.conversation_intake import ConversationIntakeRuntime
    from ac_platform.http.conversation_submissions import _Owner


def install_synthetic_import_http(
    router: APIRouter,
    *,
    current_owner: Callable[[Request], AsyncIterator[_Owner]],
    read_only_owner: Callable[[Request], AsyncIterator[_Owner]],
    guard: _Guard,
    fail: Callable[..., Any],
    runtime: ConversationIntakeRuntime,
    preflight: NativeUploadPreflight | None,
) -> None:
    from ac_platform.http.conversation_synthetic_audio import install_synthetic_audio_http

    install_synthetic_audio_http(
        router,
        runtime=runtime,
        current_owner=current_owner,
        read_only_owner=read_only_owner,
        guard=guard,
        fail=fail,
        preflight=preflight,
    )

    @router.post("/imports/sandbox/calls", status_code=201)
    async def import_call(
        bundle: SyntheticCallBundle,
        request: Request,
        response: Response,
        key: str = Header(alias="Idempotency-Key", min_length=1, max_length=128),
    ) -> dict[str, Any]:
        guard(request, response, write=True)
        try:
            async with asynccontextmanager(current_owner)(request) as owner:
                if owner.actor is None or owner.token is not None:
                    raise fail(401, "Sign in to the sandbox organisation.")
                await require_sales_xray_write_profile(owner.ownership.database, owner.actor)
                return await SyntheticImports(owner.ownership).call(owner.actor, bundle, key=key)
        except ConversationError as error:
            raise fail(error.status, str(error)) from None

    @router.post("/imports/sandbox/records", status_code=201)
    async def import_records(
        batch: SyntheticRecordBatch,
        request: Request,
        response: Response,
        key: str = Header(alias="Idempotency-Key", min_length=1, max_length=128),
    ) -> dict[str, Any]:
        guard(request, response, write=True)
        try:
            async with asynccontextmanager(current_owner)(request) as owner:
                if owner.actor is None or owner.token is not None:
                    raise fail(401, "Sign in to the sandbox organisation.")
                await require_sales_xray_write_profile(owner.ownership.database, owner.actor)
                return await SyntheticImports(owner.ownership).records(owner.actor, batch, key=key)
        except ConversationError as error:
            raise fail(error.status, str(error)) from None

    @router.get("/imports/sandbox")
    async def progress(request: Request, response: Response) -> dict[str, Any]:
        guard(request, response)
        try:
            async with asynccontextmanager(read_only_owner)(request) as owner:
                if owner.actor is None:
                    raise fail(401, "Sign in to the sandbox organisation.")
                return await SyntheticImports(owner.ownership).progress(owner.actor)
        except ConversationError as error:
            raise fail(error.status, str(error)) from None

    @router.get("/imports/sandbox/records/{kind}")
    @router.get("/imports/sandbox/records/{kind}/after/{cursor}")
    async def records(
        request: Request,
        response: Response,
        kind: str = Path(
            pattern=r"^(call|world|business_history|people|companies|contacts|leads|deals|invoices|payments|calendar|people_events|rep_weeks|sales_events|skills|missions|call_summary)$"
        ),
        cursor: str | None = None,
    ) -> dict[str, Any]:
        guard(request, response)
        if cursor is not None and not SYNTHETIC_KEY.fullmatch(cursor):
            raise fail(422, "Choose one exact synthetic record cursor.")
        try:
            async with asynccontextmanager(read_only_owner)(request) as owner:
                if owner.actor is None:
                    raise fail(401, "Sign in to the sandbox organisation.")
                return await SyntheticImports(owner.ownership).list_records(
                    owner.actor, kind=kind, after=cursor, limit=100
                )
        except ConversationError as error:
            raise fail(error.status, str(error)) from None

    @router.get("/imports/sandbox/calls/{call_id}")
    @router.get("/imports/sandbox/calls/{call_id}/coaching")
    async def call(call_id: str, request: Request, response: Response) -> dict[str, Any]:
        guard(request, response)
        try:
            async with asynccontextmanager(read_only_owner)(request) as owner:
                if owner.actor is None:
                    raise fail(401, "Sign in to the sandbox organisation.")
                return await SyntheticImports(owner.ownership).read_call(
                    owner.actor, call_id, coaching=request.url.path.endswith("/coaching")
                )
        except ConversationError as error:
            raise fail(error.status, str(error)) from None
