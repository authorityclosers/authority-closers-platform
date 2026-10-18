"""Admin routes for the call data engine (Admin host, operations control accounts only).

- GET /v1/admin/conversation/calls/{recording_id}/data-map  one call's stage map
- GET /v1/admin/call-data                                   settings, spend, recent runs
- PUT /v1/admin/call-data/settings                          swap the model, switch off, cap

Settings are append-only revisions; provider keys stay in Infisical.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any, Literal
from uuid import UUID

from fastapi import APIRouter, Depends, FastAPI, HTTPException, Request, Response
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import text

from ac_platform.audit.service import AuditRepository
from ac_platform.call_data import call_map, engine, facts
from ac_platform.call_data.settings import PIPELINES, SettingsError, public, raise_to
from ac_platform.conversation_intelligence.application import (
    ConversationApplication,
    ConversationError,
)
from ac_platform.conversation_intelligence.provider_admin import ConversationProviderAdmin
from ac_platform.http.auth import (
    AuthenticatedTransaction,
    require_admin_surface,
    require_safe_origin,
)
from ac_platform.http.routes import RouteContext
from ac_platform.kernel.errors import DomainError

PRIVATE = {"Cache-Control": "private, no-store"}


class SettingsCommand(BaseModel):
    model_config = ConfigDict(extra="forbid")
    expected_revision: int | None
    config: dict[str, Any]


class RaiseCommand(BaseModel):
    model_config = ConfigDict(extra="forbid")
    expected_revision: int | None
    pipeline: Literal["fast", "deep"]
    daily_cap_inr: int = Field(ge=1, le=5000)


def _caps(config: dict[str, Any]) -> dict[str, Any]:
    return {
        pipeline: {
            "enabled": config[pipeline]["enabled"],
            "model": config[pipeline]["model"],
            "daily_cap_inr": config[pipeline]["daily_cap_inr"],
        }
        for pipeline in PIPELINES
    }


def install_call_data_admin_http(application: FastAPI, ctx: RouteContext) -> None:
    settings = ctx.settings
    dependency = Depends(ctx.require_actor, scope="function")
    router = APIRouter(tags=["call-data-admin"])

    async def admit(request: Request, response: Response, auth: AuthenticatedTransaction) -> Any:
        require_admin_surface(request, settings)
        response.headers.update(PRIVATE)
        if request.query_params:
            raise HTTPException(422, "This view takes no filters.")
        actor = auth.resolved.actor
        if (
            settings.operations_tenant_id is None
            or actor.tenant_id != settings.operations_tenant_id
        ):
            raise HTTPException(403, "Use the AC operations workspace.")
        try:
            await ConversationProviderAdmin(ConversationApplication(auth.database)).admit(actor)
        except ConversationError as error:
            raise HTTPException(error.status, str(error)) from None
        return actor

    @router.get("/v1/admin/conversation/calls/{recording_id}/data-map")
    async def data_map(
        recording_id: UUID,
        request: Request,
        response: Response,
        auth: AuthenticatedTransaction = dependency,
    ) -> dict[str, Any]:
        await admit(request, response, auth)
        result = await auth.database.run_sync(
            lambda session: call_map.call_map(session.connection(), recording_id)
        )
        if result is None:
            raise HTTPException(404, "This call is not here.")
        return result

    @router.get("/v1/admin/conversation/calls/{recording_id}/data-objects")
    async def data_objects(
        recording_id: UUID,
        request: Request,
        response: Response,
        auth: AuthenticatedTransaction = dependency,
    ) -> dict[str, Any]:
        """What the engine found in one call: facts, segment labels, voice (content)."""
        await admit(request, response, auth)
        result: dict[str, Any] = await auth.database.run_sync(
            lambda session: facts.call_objects(session.connection(), recording_id)
        )
        return result

    @router.get("/v1/admin/call-data")
    async def overview(
        request: Request, response: Response, auth: AuthenticatedTransaction = dependency
    ) -> dict[str, Any]:
        await admit(request, response, auth)

        def read(session: Any) -> dict[str, Any]:
            connection = session.connection()
            config, revision = engine.read_settings(connection)
            now = datetime.now(UTC)
            recent = connection.execute(
                text(
                    """
                    SELECT r.recording_id, r.pipeline, r.state, r.reason_code, r.model_id,
                           r.cost_inr, r.duration_ms, r.counts, r.trigger, r.created_at,
                           t.name AS workspace
                    FROM call_data_runs r JOIN tenants t ON t.id = r.tenant_id
                    WHERE r.state <> 'running'
                    ORDER BY r.created_at DESC LIMIT 50
                    """
                )
            ).mappings()
            status = {}
            for pipeline in PIPELINES:
                spent = engine.spent_today(connection, pipeline, now)
                cap = config[pipeline]["daily_cap_inr"]
                at_cap = config[pipeline]["enabled"] and spent >= cap
                status[pipeline] = {
                    "spent_today_inr": float(spent),
                    "daily_cap_inr": cap,
                    "at_cap": bool(at_cap),
                    "waiting": engine.waiting_for_budget(connection, pipeline, now)
                    if config[pipeline]["enabled"]
                    else 0,
                    "raise_to_inr": raise_to(cap),
                }
            return {
                **public(config, revision=revision),
                "status": status,
                "history": engine.settings_history(connection),
                "spent_today_inr": {
                    pipeline: status[pipeline]["spent_today_inr"] for pipeline in PIPELINES
                },
                "recent": [
                    {
                        "recording_id": str(row["recording_id"]),
                        "pipeline": row["pipeline"],
                        "state": row["state"],
                        "reason": row["reason_code"],
                        "model": row["model_id"],
                        "cost_inr": None if row["cost_inr"] is None else float(row["cost_inr"]),
                        "duration_ms": row["duration_ms"],
                        "facts": (row["counts"] or {}).get("facts")
                        if isinstance(row["counts"], dict)
                        else None,
                        "trigger": row["trigger"],
                        "workspace": row["workspace"],
                        "at": row["created_at"].isoformat(),
                    }
                    for row in recent
                ],
            }

        return await auth.database.run_sync(read)

    async def save_audited(
        auth: AuthenticatedTransaction,
        actor: Any,
        expected: int | None,
        config: dict[str, Any],
        *,
        action: str,
    ) -> dict[str, Any]:
        def write(session: Any) -> tuple[dict[str, Any], dict[str, Any], int]:
            connection = session.connection()
            before, current = engine.read_settings(connection)
            if current != expected:
                raise HTTPException(409, "Someone changed these settings. Refresh and try again.")
            revision = engine.save_settings(
                connection, config, person_id=actor.person_id, now=datetime.now(UTC)
            )
            after, _ = engine.read_settings(connection)
            return before, after, revision

        try:
            before, after, revision = await auth.database.run_sync(write)
        except SettingsError as error:
            raise HTTPException(422, f"Check the settings ({error.code}).") from None
        # Who, when, old → new (the owner's rule for one-click caps).
        await AuditRepository(auth.database).append_for_actor(
            actor,
            action=action,
            resource_type="call_data_settings",
            resource_id=str(revision),
            payload={"revision": revision, "old": _caps(before), "new": _caps(after)},
        )
        return public(after, revision=revision)

    @router.put("/v1/admin/call-data/settings")
    async def save(
        command: SettingsCommand,
        request: Request,
        response: Response,
        auth: AuthenticatedTransaction = dependency,
    ) -> dict[str, Any]:
        try:
            require_safe_origin(request, settings)
        except DomainError:
            raise HTTPException(403, "Use this Admin page to continue.") from None
        actor = await admit(request, response, auth)
        return await save_audited(
            auth,
            actor,
            command.expected_revision,
            command.config,
            action="call_data.settings_saved",
        )

    @router.post("/v1/admin/call-data/raise")
    async def raise_cap(
        command: RaiseCommand,
        request: Request,
        response: Response,
        auth: AuthenticatedTransaction = dependency,
    ) -> dict[str, Any]:
        """One click: raise a pipeline's daily cap; the waiting calls resume on the next pass."""
        try:
            require_safe_origin(request, settings)
        except DomainError:
            raise HTTPException(403, "Use this Admin page to continue.") from None
        actor = await admit(request, response, auth)
        current, _ = await auth.database.run_sync(
            lambda session: engine.read_settings(session.connection())
        )
        config = {pipeline: dict(current[pipeline]) for pipeline in PIPELINES}
        config["streaming"] = dict(current["streaming"])
        config[command.pipeline]["daily_cap_inr"] = command.daily_cap_inr
        return await save_audited(
            auth, actor, command.expected_revision, config, action="call_data.cap_raised"
        )

    application.include_router(router)
