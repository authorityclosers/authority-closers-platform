"""Batch preview reuses the private submission router's account and origin guards."""

from __future__ import annotations

from collections.abc import AsyncIterator, Callable
from contextlib import asynccontextmanager
from typing import TYPE_CHECKING, Any, Protocol

from fastapi import APIRouter, HTTPException, Request, Response

from ac_platform.conversation_intelligence.application import ConversationError
from ac_platform.conversation_intelligence.bulk_import_preview import BatchManifest, preview_import

if TYPE_CHECKING:
    from ac_platform.http.conversation_submissions import _Owner


class _Guard(Protocol):
    def __call__(self, request: Request, response: Response, *, write: bool = False) -> str: ...


def install_import_http(
    router: APIRouter,
    *,
    current_owner: Callable[[Request], AsyncIterator[_Owner]],
    guard: _Guard,
    fail: Callable[[int, str], HTTPException],
) -> None:
    @router.post("/imports/preview")
    async def preview(
        manifest: BatchManifest, request: Request, response: Response
    ) -> dict[str, Any]:
        guard(request, response, write=True)
        try:
            async with asynccontextmanager(current_owner)(request) as owner:
                return await preview_import(owner.ownership, owner.actor, manifest)
        except ConversationError as error:
            raise fail(error.status, str(error)) from None
