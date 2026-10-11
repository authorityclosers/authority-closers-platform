"""Admin's read-only browser over the AC Sandbox's imported full calls (AUT-1798).

``GET /v1/admin/conversation/sandbox-calls`` pages through the sandbox's
fictional full calls (filters and facets like the dataset-folder browser at
``/synthetic``); ``GET /sandbox-calls/{call_id}`` returns one call's transcript
beside its answer key, never its fixture truth or the private coaching.
Admitted exactly like the call review console. The Admin page uses these when
the dataset folder isn't mounted in an environment.
"""

from __future__ import annotations

from typing import Annotated, Any

from fastapi import APIRouter, Depends, FastAPI, HTTPException, Path, Query, Request, Response

from ac_platform.application.settings import Settings
from ac_platform.conversation_intelligence.admin_call_review import AdminCallReview
from ac_platform.conversation_intelligence.application import (
    ConversationApplication,
    ConversationError,
)
from ac_platform.conversation_intelligence.synthetic_sandbox_browser import SandboxCallBrowser
from ac_platform.http.auth import AuthenticatedTransaction, RequireActor, require_admin_surface


def install_sandbox_browser_routes(
    application: FastAPI, *, settings: Settings, require_actor: RequireActor
) -> None:
    router = APIRouter(prefix="/v1/admin/conversation", tags=["conversation-sandbox-admin"])
    dependency = Depends(require_actor, scope="function")

    def scope(request: Request, response: Response, allowed: frozenset[str]) -> None:
        require_admin_surface(request, settings)
        response.headers["Cache-Control"] = "private, no-store"
        names = set(request.query_params)
        if names - allowed:
            raise HTTPException(422, "This view takes no other filters.")
        if any(len(request.query_params.getlist(name)) != 1 for name in names):
            raise HTTPException(422, "Give each filter once.")

    async def admit(auth: AuthenticatedTransaction) -> SandboxCallBrowser:
        if settings.operations_tenant_id is None:
            raise HTTPException(503, "Call review is not configured.")
        await AdminCallReview(
            ConversationApplication(auth.database),
            settings.operations_tenant_id,
            recording_tenant_ids=(),
        )._admit(auth.resolved.actor)
        return SandboxCallBrowser(auth.database)

    @router.get("/sandbox-calls")
    async def sandbox_calls(
        request: Request,
        response: Response,
        business: Annotated[str | None, Query(max_length=64)] = None,
        language: Annotated[str | None, Query(max_length=16)] = None,
        outcome: Annotated[str | None, Query(max_length=64)] = None,
        q: Annotated[str | None, Query(max_length=80)] = None,
        offset: Annotated[int, Query(ge=0, le=100_000)] = 0,
        limit: Annotated[int, Query(ge=1, le=100)] = 50,
        auth: AuthenticatedTransaction = dependency,
    ) -> dict[str, Any]:
        """The sandbox's fictional full calls, read-only and clearly labelled."""
        scope(
            request,
            response,
            frozenset({"business", "language", "outcome", "q", "offset", "limit"}),
        )
        try:
            browser = await admit(auth)
            return await browser.index(
                business=business,
                language=language,
                outcome=outcome,
                query=q,
                offset=offset,
                limit=limit,
            )
        except ConversationError as error:
            raise HTTPException(error.status, str(error)) from None

    @router.get("/sandbox-calls/{call_id}")
    async def sandbox_call(
        call_id: Annotated[str, Path(min_length=5, max_length=128)],
        request: Request,
        response: Response,
        auth: AuthenticatedTransaction = dependency,
    ) -> dict[str, Any]:
        """One sandbox call: transcript and answer key, never its fixture truth."""
        scope(request, response, frozenset())
        try:
            browser = await admit(auth)
            return await browser.call(call_id)
        except ConversationError as error:
            raise HTTPException(error.status, str(error)) from None

    application.include_router(router)
