"""Settings, Privacy: a person's and their workspace's usage-analytics switches (owner, 24 Oct
2026, option B: on by default, a per-person opt-out, and owners and admins can turn it off
for the workspace).

GET  /v1/telemetry/preferences            the notice, both switches and whether this person
                                          is being recorded now
PUT  /v1/telemetry/preferences/you        {"enabled": bool}, anyone, for themselves
PUT  /v1/telemetry/preferences/workspace  {"enabled": bool}, owners and admins only
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from fastapi import APIRouter, Depends, FastAPI, HTTPException, Request, Response
from pydantic import BaseModel, ConfigDict, StrictBool

from ac_platform.application.settings import Settings
from ac_platform.http.auth import AuthenticatedTransaction, RequireActor, require_safe_origin
from ac_platform.telemetry.sales_xray import NOTICE_VERSION, NOTICES
from ac_platform.telemetry.sales_xray_consent import (
    MANAGER_ROLES,
    Choice,
    Scope,
    record_choice,
    standing_for,
)


class AnalyticsChoice(BaseModel):
    model_config = ConfigDict(extra="forbid")

    # True or false only: "no" or 0 is refused, never read as off.
    enabled: StrictBool


def _when(choice: Choice) -> str | None:
    return choice.at.isoformat() if choice.at is not None else None


async def _view(auth: AuthenticatedTransaction) -> dict[str, Any]:
    actor = auth.resolved.actor
    standing = await standing_for(auth.database, actor)
    if standing is None:
        raise HTTPException(403, "Choose a workspace first.")
    return {
        "notice": {"version": NOTICE_VERSION, "paragraphs": list(NOTICES[NOTICE_VERSION])},
        "collecting": standing.collecting,
        "sandbox": standing.sandbox,
        "you": {"enabled": standing.person.enabled, "changed_at": _when(standing.person)},
        "workspace": {
            "enabled": standing.workspace.enabled,
            "changed_at": _when(standing.workspace),
            "can_change": (auth.resolved.membership_role or "") in MANAGER_ROLES,
        },
    }


def install_telemetry_preferences_http(
    application: FastAPI, *, settings: Settings, require_actor: RequireActor
) -> None:
    router = APIRouter(prefix="/v1/telemetry", tags=["telemetry"])
    actor_dependency = Depends(require_actor)

    async def change(
        request: Request,
        response: Response,
        auth: AuthenticatedTransaction,
        scope: Scope,
        body: AnalyticsChoice,
    ) -> dict[str, Any]:
        require_safe_origin(request, settings)
        response.headers["cache-control"] = "private, no-store"
        if auth.resolved.actor.tenant_id is None:
            raise HTTPException(403, "Choose a workspace first.")
        if scope == "workspace" and (auth.resolved.membership_role or "") not in MANAGER_ROLES:
            raise HTTPException(403, "Only an owner or admin can change this for the workspace.")
        await record_choice(
            auth.database,
            auth.resolved.actor,
            scope=scope,
            enabled=body.enabled,
            now=datetime.now(UTC),
        )
        return await _view(auth)

    @router.get("/preferences")
    async def read_preferences(
        response: Response, auth: AuthenticatedTransaction = actor_dependency
    ) -> dict[str, Any]:
        response.headers["cache-control"] = "private, no-store"
        return await _view(auth)

    @router.put("/preferences/you")
    async def change_yours(
        body: AnalyticsChoice,
        request: Request,
        response: Response,
        auth: AuthenticatedTransaction = actor_dependency,
    ) -> dict[str, Any]:
        return await change(request, response, auth, "person", body)

    @router.put("/preferences/workspace")
    async def change_workspace(
        body: AnalyticsChoice,
        request: Request,
        response: Response,
        auth: AuthenticatedTransaction = actor_dependency,
    ) -> dict[str, Any]:
        return await change(request, response, auth, "workspace", body)

    application.include_router(router)


__all__ = ["AnalyticsChoice", "install_telemetry_preferences_http"]
