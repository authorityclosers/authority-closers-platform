"""Ask Dipak progress over HTTP (Dipak's spec, 13 Nov 2026; migration 0153).

The signed-in person, on a Sales X-Ray address:

GET /v1/sales-xray/ask-dipak/progress
    Their saved lessons and the missions they have marked done: {saved, missions,
    missions_done}. Their own only; the same in every workspace and on every device.
PUT /v1/sales-xray/ask-dipak/progress/{question_id}   {item: saved|mission, on}
    Saves or clears a lesson's bookmark, or marks or undoes its Next-call mission, and answers
    as GET does. A repeat changes nothing. Only Dipak's 150 questions; a mission only where the
    question has a lesson.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any, Literal

from fastapi import APIRouter, Depends, FastAPI, HTTPException, Path, Request, Response
from pydantic import BaseModel, ConfigDict

from ac_platform.ask_dipak import store
from ac_platform.http.auth import AuthenticatedTransaction, require_safe_origin
from ac_platform.http.routes import RouteContext
from ac_platform.kernel.errors import DomainError

PRIVATE = {"Cache-Control": "private, no-store"}
QUESTION = r"^([A-Z]{2}[0-9]{2}|NEW-[0-9]{3})$"


class ProgressChange(BaseModel):
    model_config = ConfigDict(extra="forbid")

    item: Literal["saved", "mission"]
    on: bool


def install_ask_dipak_http(app: FastAPI, ctx: RouteContext) -> None:
    settings = ctx.settings
    dependency = Depends(ctx.require_actor, scope="function")
    read_dependency = Depends(
        getattr(ctx.require_actor, "read_only", ctx.require_actor), scope="function"
    )
    router = APIRouter(prefix="/v1/sales-xray/ask-dipak", tags=["sales-xray-ask-dipak"])

    def on_app_host(request: Request) -> None:
        hosts = {settings.public_app_url.host}
        hosts.update(settings.sales_xray_hosts)
        if request.url.hostname not in hosts or request.query_params:
            raise HTTPException(404, "Not found.", headers=PRIVATE)

    @router.get("/progress")
    async def progress(
        request: Request,
        response: Response,
        auth: AuthenticatedTransaction = read_dependency,
    ) -> dict[str, Any]:
        response.headers.update(PRIVATE)
        on_app_host(request)
        answer = await store.progress_for(auth.database, auth.resolved.actor.person_id)
        return answer.public()

    @router.put("/progress/{question_id}")
    async def change(
        command: ProgressChange,
        request: Request,
        response: Response,
        question_id: str = Path(pattern=QUESTION, max_length=16),
        auth: AuthenticatedTransaction = dependency,
    ) -> dict[str, Any]:
        response.headers.update(PRIVATE)
        on_app_host(request)
        try:
            require_safe_origin(request, settings)
        except DomainError:
            raise HTTPException(403, "Send this from Ask Dipak.", headers=PRIVATE) from None
        actor = auth.resolved.actor
        try:
            answer = await store.set_item(
                auth.database,
                person_id=actor.person_id,
                tenant_id=actor.tenant_id,
                question_id=question_id,
                item=command.item,
                on=command.on,
                now=datetime.now(UTC),
            )
        except store.UnknownQuestion:
            raise HTTPException(404, "No such question.", headers=PRIVATE) from None
        except store.NoMission:
            raise HTTPException(
                422, "This question has no Next-call mission yet.", headers=PRIVATE
            ) from None
        return answer.public()

    app.include_router(router)


__all__ = ["ProgressChange", "install_ask_dipak_http"]
