"""Admin routes for the analysis pipeline switch and the one-pass comparison
(Admin host, operations control accounts only).

- GET /v1/admin/analysis-pipeline                    the switch, its history, recent runs
- PUT /v1/admin/analysis-pipeline/settings           classic | both (one_pass not yet)
- GET /v1/admin/analysis-pipeline/compare            every compared call and the summary
                                                      (numbers only)
- GET /v1/admin/analysis-pipeline/compare/{subject}  one call side by side (a recording id
                                                      or a benchmark call id); audited as
                                                      one_pass.admin_view for a real call

Settings are append-only revisions, every save audited with old, new and the reason.
Rupees are list-price estimates for Admin only, never shown to a person.
"""

from __future__ import annotations

import re
from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from fastapi import APIRouter, Depends, FastAPI, HTTPException, Request, Response
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import text

from ac_platform.audit.service import AuditRepository
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
from ac_platform.one_pass import compare
from ac_platform.one_pass import settings as choices

PRIVATE = {"Cache-Control": "private, no-store"}
_BENCH_CALL = re.compile(r"^[a-z]{2}-[0-9]{2}$")


class SettingsCommand(BaseModel):
    model_config = ConfigDict(extra="forbid")
    expected_revision: int | None
    config: dict[str, Any]
    reason: str | None = Field(default=None, max_length=200)


def _recent(connection: Any) -> list[dict[str, Any]]:
    rows = connection.execute(
        text(
            """
            SELECT r.recording_id, r.bench_call, r.source, r.state, r.reason_code, r.cost_inr,
                   r.duration_ms, r.audio_ms, r.transcription_tier, r.analysis_tier,
                   r.trigger, r.checks, r.created_at
            FROM one_pass_runs r
            WHERE r.state <> 'running' AND r.pipeline = 'one_pass'
            ORDER BY r.created_at DESC LIMIT 30
            """
        )
    ).mappings()
    return [
        {
            "subject": str(row["recording_id"] or row["bench_call"]),
            "source": row["source"],
            "state": row["state"],
            "reason": row["reason_code"],
            "cost_inr": None if row["cost_inr"] is None else float(row["cost_inr"]),
            "duration_ms": row["duration_ms"],
            "audio_ms": row["audio_ms"],
            "tiers": [row["transcription_tier"], row["analysis_tier"]],
            "trigger": row["trigger"],
            "contracts_ok": sum(1 for value in (row["checks"] or {}).values() if value == "ok")
            if isinstance(row["checks"], dict)
            else None,
            "at": row["created_at"].isoformat(),
        }
        for row in rows
    ]


def install_one_pass_admin_http(application: FastAPI, ctx: RouteContext) -> None:
    settings = ctx.settings
    environment = settings.environment
    dependency = Depends(ctx.require_actor, scope="function")
    router = APIRouter(tags=["analysis-pipeline-admin"])

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

    async def view(auth: AuthenticatedTransaction) -> dict[str, Any]:
        def read(session: Any) -> dict[str, Any]:
            connection = session.connection()
            config, revision = choices.read(connection, environment)
            return {
                **choices.public(environment, config, revision),
                "history": choices.history(connection),
                "recent": _recent(connection),
                "spend_feature": "one_pass",
                "spend_page": "/ai-spend",
            }

        result: dict[str, Any] = await auth.database.run_sync(read)
        return result

    @router.get("/v1/admin/analysis-pipeline")
    async def overview(
        request: Request, response: Response, auth: AuthenticatedTransaction = dependency
    ) -> dict[str, Any]:
        await admit(request, response, auth)
        return await view(auth)

    @router.put("/v1/admin/analysis-pipeline/settings")
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

        def write(session: Any) -> tuple[dict[str, Any], dict[str, Any], int]:
            connection = session.connection()
            before, current = choices.read(connection, environment)
            if current != command.expected_revision:
                raise HTTPException(409, "Someone changed these settings. Refresh and try again.")
            revision = choices.save(
                connection,
                environment,
                command.config,
                person_id=actor.person_id,
                reason=command.reason,
                now=datetime.now(UTC),
            )
            after, _ = choices.read(connection, environment)
            return before, after, revision

        try:
            before, after, revision = await auth.database.run_sync(write)
        except choices.SettingsError as error:
            message = (
                choices.why_not(environment, str(command.config.get("mode")))
                if error.code == "mode_not_here"
                else None
            )
            raise HTTPException(422, message or f"Check the settings ({error.code}).") from None
        await AuditRepository(auth.database).append_for_actor(
            actor,
            action="analysis_pipeline.settings_saved",
            resource_type="analysis_pipeline_settings",
            resource_id=str(revision),
            payload={"revision": revision, "old": before, "new": after, "reason": command.reason},
        )
        return await view(auth)

    @router.get("/v1/admin/analysis-pipeline/compare")
    async def compared(
        request: Request, response: Response, auth: AuthenticatedTransaction = dependency
    ) -> dict[str, Any]:
        """Every compared call (numbers and ids only) and the summary."""
        await admit(request, response, auth)
        result: dict[str, Any] = await auth.database.run_sync(
            lambda session: compare.overview(session.connection())
        )
        result["environment"] = environment
        return result

    @router.get("/v1/admin/analysis-pipeline/compare/{subject}")
    async def one_call(
        subject: str,
        request: Request,
        response: Response,
        auth: AuthenticatedTransaction = dependency,
    ) -> dict[str, Any]:
        """One call side by side, with its content: facts, scores, coaching, transcripts."""
        actor = await admit(request, response, auth)
        recording_id: UUID | None = None
        if _BENCH_CALL.fullmatch(subject) is None:
            try:
                recording_id = UUID(subject)
            except ValueError:
                raise HTTPException(404, "This call is not here.") from None
        result = await auth.database.run_sync(
            lambda session: compare.call_compare(
                session.connection(),
                recording_id=recording_id,
                bench_call=None if recording_id else subject,
            )
        )
        if result is None:
            raise HTTPException(404, "This call is not here.")
        if recording_id is not None:
            tenant = await auth.database.scalar(
                text("SELECT tenant_id FROM conversation_recordings WHERE id = :r"),
                {"r": recording_id},
            )
            if tenant is not None:
                # A staff read of a customer's call content, in that customer's own chain.
                await AuditRepository(auth.database).append(
                    tenant_id=tenant,
                    actor_person_id=actor.person_id,
                    action="one_pass.admin_view",
                    resource_type="conversation_recording",
                    resource_id=str(recording_id),
                    payload={"read": compare.SCHEMA},
                    session_id=actor.session_id,
                )
        result["environment"] = environment
        return result

    application.include_router(router)
