"""Admin routes for the analysis pipeline switch and the one-pass comparison
(Admin host, operations control accounts only).

- GET /v1/admin/analysis-pipeline                    the switch, its history, recent runs
- PUT /v1/admin/analysis-pipeline/settings           classic | both (development) |
                                                      one_pass (the owner's action: typed
                                                      confirm, reason, fresh sign-in)
- GET /v1/admin/analysis-pipeline/compare            every compared call and the summary
                                                      (numbers only)
- GET /v1/admin/analysis-pipeline/compare/{subject}  one call side by side (a recording id
                                                      or a benchmark call id); audited as
                                                      one_pass.admin_view for a real call

Settings are append-only revisions, every save audited with old, new and the reason.
Switching to ``one_pass`` (people see one-pass results) is the owner's action (owner, 21
Oct 2026: "So at least get this on prod now!!!"): a control account signed in within the
last ten minutes types ``one_pass`` and gives the reason in the owner's words, and the
environment's one-pass spend cap must be above ₹0; it is audited as
``analysis_pipeline.one_pass_switched_on``. Back to ``classic`` is one click, at once.
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

from ac_platform.ai_spend.policy import environment_name
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
from ac_platform.identity.sign_in_methods import session_is_fresh
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
    confirm: str | None = Field(default=None, max_length=32)


MIN_OWNER_REASON = 10


def _spend_ready(connection: Any, environment: str) -> str | None:
    """Why the AI spend guard would stop every one-pass read here, or None."""
    from ac_platform.ai_spend import guard as spend_guard

    config, _ = spend_guard.read_settings(connection, environment)
    if not config["background_enabled"]:
        return "Background AI is off here: switch it on in AI spend first."
    if int(config["feature_caps_inr"].get("one_pass", 0)) <= 0:
        return "The one-pass cap is Rs 0 here: raise it in AI spend first."
    return None


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
        mode = str(command.config.get("mode") or "")
        reason = (command.reason or "").strip()
        owner_action = False
        if choices.needs_owner(mode):
            owner_action = True
            if command.confirm != choices.CONFIRM:
                raise HTTPException(422, f"Type {choices.CONFIRM} to confirm.")
            if len(reason) < MIN_OWNER_REASON:
                raise HTTPException(422, "Give the reason, in the owner's words.")
            if not await session_is_fresh(auth.database, actor.session_id, datetime.now(UTC)):
                raise HTTPException(403, "Sign in again (within ten minutes) to switch this.")

        def write(session: Any) -> tuple[dict[str, Any], dict[str, Any], int]:
            connection = session.connection()
            before, current = choices.read(connection, environment)
            if current != command.expected_revision:
                raise HTTPException(409, "Someone changed these settings. Refresh and try again.")
            if owner_action and before["mode"] != mode:
                blocked = _spend_ready(connection, environment)
                if blocked is not None:
                    raise HTTPException(422, blocked)
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
                else "Staging and production run the standard tier for now (Flex after a"
                " latency check)."
                if error.code.endswith("_standard_only")
                else None
            )
            raise HTTPException(422, message or f"Check the settings ({error.code}).") from None
        switched_on = after["mode"] == "one_pass" and before["mode"] != "one_pass"
        payload: dict[str, Any] = {
            "revision": revision,
            "old": before,
            "new": after,
            "reason": command.reason,
        }
        if switched_on:
            payload["confirm"] = command.confirm
            payload["environment"] = environment_name(environment)
        await AuditRepository(auth.database).append_for_actor(
            actor,
            action=(
                "analysis_pipeline.one_pass_switched_on"
                if switched_on
                else "analysis_pipeline.settings_saved"
            ),
            resource_type="analysis_pipeline_settings",
            resource_id=str(revision),
            payload=payload,
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
