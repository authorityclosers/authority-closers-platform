"""Batch preview reuses the private submission router's account and origin guards."""

from __future__ import annotations

import re
from collections.abc import AsyncIterator, Callable
from contextlib import asynccontextmanager
from dataclasses import replace
from typing import TYPE_CHECKING, Any, Protocol
from uuid import UUID

from fastapi import APIRouter, Header, HTTPException, Request, Response

from ac_platform.conversation_intelligence.application import ConversationError
from ac_platform.conversation_intelligence.bulk_import_contracts import ImportConfirmation
from ac_platform.conversation_intelligence.bulk_import_ownership import ImportOwnership
from ac_platform.conversation_intelligence.bulk_import_preview import BatchManifest, preview_import
from ac_platform.conversation_intelligence.bulk_imports import ImportReference, RecordingImports
from ac_platform.http.sales_xray_profile import require_sales_xray_write_profile

if TYPE_CHECKING:
    from ac_platform.http.conversation_submissions import _Owner


class _Guard(Protocol):
    def __call__(self, request: Request, response: Response, *, write: bool = False) -> str: ...


def assert_import_tenant(owner: _Owner, request: Request) -> None:
    values = request.headers.getlist("x-recording-import-tenant")
    if not values:
        return
    if (
        len(values) != 1
        or owner.actor is None
        or values[0] != str(owner.actor.tenant_id)
        or values[0] != str(owner.ownership.tenant_id)
    ):
        raise HTTPException(
            403,
            "The selected import organisation changed.",
            headers={"Cache-Control": "private, no-store", "Vary": "Cookie"},
        )


async def bind_import_request(owner: _Owner, request: Request, *, policy_sha256: str) -> _Owner:
    assert_import_tenant(owner, request)
    batches = request.headers.getlist("x-recording-import")
    indices = request.headers.getlist("x-recording-import-item")
    if not batches and not indices:
        return owner
    private = {"Cache-Control": "private, no-store", "Vary": "Cookie"}
    if (
        len(batches) != 1
        or len(indices) != 1
        or re.fullmatch(r"[0-9a-f]{8}-(?:[0-9a-f]{4}-){3}[0-9a-f]{12}", batches[0]) is None
        or re.fullmatch(r"0|[1-9][0-9]{0,2}", indices[0]) is None
        or int(indices[0]) > 255
    ):
        raise HTTPException(422, "Choose one exact recording import item.", headers=private)
    selected = re.fullmatch(
        r"/v1/conversation/acquisition/submissions/([0-9a-f-]{36})(?:/(source|plan/quote|plan|retry))?",
        request.url.path,
    )
    allowed = {
        "source": {"PUT"},
        "plan/quote": {"POST"},
        "plan": {"GET", "POST"},
        "retry": {"POST"},
        None: {"GET"},
    }
    if selected is None or request.method not in allowed.get(selected[2], set()):
        raise HTTPException(
            403,
            "Recording import authority applies only to its exact source, plan and safe retry.",
            headers=private,
        )
    if owner.actor is None or owner.token is not None:
        raise HTTPException(
            403, "Use this batch's current organisation uploader session.", headers=private
        )
    reference = ImportReference(UUID(batches[0]), int(indices[0]))
    imports = RecordingImports(owner.ownership)
    batch, item = await imports.authorize(
        owner.actor, reference, shared_identity_locks=owner.shared_identity_locks
    )
    if item.submission_id != UUID(selected[1]) or batch.policy_sha256 != policy_sha256:
        raise HTTPException(
            409,
            "The import source or upload terms changed. Preview the folder again.",
            headers=private,
        )
    if item.reused and selected[2] != "source":
        raise HTTPException(
            403, "An already imported call keeps its original owner and analysis.", headers=private
        )
    return replace(owner, ownership=ImportOwnership(owner.ownership, owner.actor, reference))


def install_import_http(
    router: APIRouter,
    *,
    current_owner: Callable[[Request], AsyncIterator[_Owner]],
    guard: _Guard,
    fail: Callable[[int, str], HTTPException],
    policy_sha256: Callable[[], str] | None = None,
    read_only_owner: Callable[[Request], AsyncIterator[_Owner]] | None = None,
) -> None:
    @router.post("/imports/preview")
    async def preview(
        manifest: BatchManifest, request: Request, response: Response
    ) -> dict[str, Any]:
        guard(request, response, write=True)
        try:
            async with asynccontextmanager(current_owner)(request) as owner:
                assert_import_tenant(owner, request)
                return await preview_import(owner.ownership, owner.actor, manifest)
        except ConversationError as error:
            raise fail(error.status, str(error)) from None

    if policy_sha256 is None:
        return

    @router.post("/imports", status_code=201)
    async def confirm(
        confirmation: ImportConfirmation,
        request: Request,
        response: Response,
        key: str = Header(alias="Idempotency-Key", min_length=1, max_length=128),
    ) -> dict[str, Any]:
        guard(request, response, write=True)
        try:
            async with asynccontextmanager(current_owner)(request) as owner:
                assert_import_tenant(owner, request)
                if owner.actor is None:
                    raise fail(401, "Sign in to import your organisation's recording folder.")
                await require_sales_xray_write_profile(owner.ownership.database, owner.actor)
                return await RecordingImports(owner.ownership).create(
                    owner.actor, confirmation, key=key, policy_sha256=policy_sha256()
                )
        except ConversationError as error:
            raise fail(error.status, str(error)) from None

    @router.get("/imports/{batch_id}")
    async def progress(batch_id: UUID, request: Request, response: Response) -> dict[str, Any]:
        guard(request, response)
        try:
            async with asynccontextmanager(read_only_owner or current_owner)(request) as owner:
                assert_import_tenant(owner, request)
                if owner.actor is None:
                    raise fail(401, "Sign in to view your organisation's recording import.")
                return await RecordingImports(owner.ownership).progress(owner.actor, batch_id)
        except ConversationError as error:
            raise fail(error.status, str(error)) from None
