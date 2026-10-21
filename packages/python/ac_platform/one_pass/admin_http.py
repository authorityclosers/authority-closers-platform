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
- GET /v1/admin/analysis-pipeline/transcription      the C2 route in use, and the Gemini 3.1
                                                      Flash-Lite configuration: saved? sealed?
- POST /v1/admin/analysis-pipeline/transcription/prepare
                                                      save that configuration as a provider
                                                      revision (its digest is what Root seals)

The switch itself is ``POST /v1/admin/conversation/providers/activate`` with the owner's
typed confirm and reason (``ConversationProviderAdmin._owner_gate``); back to Scribe is the
same call for the classic revision, one click.

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
from typing import Any, Literal
from uuid import UUID

from fastapi import APIRouter, Depends, FastAPI, HTTPException, Request, Response
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select, text

from ac_platform.ai_spend.policy import environment_name
from ac_platform.audit.service import AuditRepository
from ac_platform.conversation_intelligence import provider_admin
from ac_platform.conversation_intelligence.application import (
    ConversationApplication,
    ConversationError,
)
from ac_platform.conversation_intelligence.hosted_runtime import load_pinned_approval
from ac_platform.conversation_intelligence.models import ConversationProviderConfiguration
from ac_platform.conversation_intelligence.provider_admin import (
    OWNER_CONFIRM_WORD,
    ConversationProviderAdmin,
)
from ac_platform.conversation_intelligence.provider_registry import (
    ProviderRegistryError,
    parse_registry_config,
)
from ac_platform.http.auth import (
    AuthenticatedTransaction,
    require_admin_surface,
    require_safe_origin,
)
from ac_platform.http.routes import RouteContext
from ac_platform.identity.sign_in_methods import session_is_fresh
from ac_platform.kernel.errors import DomainError
from ac_platform.one_pass import c2_route, compare, markers
from ac_platform.one_pass import settings as choices

PRIVATE = {"Cache-Control": "private, no-store"}
_BENCH_CALL = re.compile(r"^[a-z]{2}-[0-9]{2}$")


class PrepareCommand(BaseModel):
    model_config = ConfigDict(extra="forbid")
    tier: Literal["standard", "flex", "one_pass", "one_pass_flex", "luna", "luna_flex"] = "standard"


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


def _transcription(row: Any) -> dict[str, Any] | None:
    try:
        config = parse_registry_config(row.configuration)
    except (ProviderRegistryError, TypeError, ValueError):
        return None
    route = next((item for item in config.routes if item.task == "asr"), None)
    return None if route is None else {"provider": route.provider_id, "model": route.model_id}


def _uses_flex(row: Any) -> bool:
    try:
        config = parse_registry_config(row.configuration)
    except (ProviderRegistryError, TypeError, ValueError):
        return False
    return any(route.model_id.endswith(":flex") for route in config.routes)


def _uses_one_pass(row: Any) -> bool:
    try:
        config = parse_registry_config(row.configuration)
    except (ProviderRegistryError, TypeError, ValueError):
        return False
    return any(
        route.task == "facts" and route.recipe_revision == markers.RECIPE for route in config.routes
    )


def _uses_openai(row: Any) -> bool:
    try:
        config = parse_registry_config(row.configuration)
    except (ProviderRegistryError, TypeError, ValueError):
        return False
    return any(route.provider_id == "openai" for route in config.routes)


# The prepared configurations: (name, Prepare's tier, flex, one pass, Luna, Root's profile).
_TIERS = (
    ("gemini", "standard", False, False, False, c2_route.PROFILE_ID),
    ("gemini_flex", "flex", True, False, False, c2_route.FLEX_PROFILE_ID),
    ("one_pass", "one_pass", False, True, False, c2_route.ONE_PASS_PROFILE_ID),
    ("one_pass_flex", "one_pass_flex", True, True, False, c2_route.ONE_PASS_FLEX_PROFILE_ID),
    ("luna", "luna", False, True, True, c2_route.LUNA_PROFILE_ID),
    ("luna_flex", "luna_flex", True, True, True, c2_route.LUNA_FLEX_PROFILE_ID),
)


async def _transcription_view(auth: Any, actor: Any, settings: Any) -> dict[str, Any]:
    """The C2 route in use and the Gemini configurations' state (Flash-Lite C2, standard
    and Flex, each with today's C4 or the one-pass C4 request): derived from today's Scribe
    configuration, saved? sealed? Ids and digests only."""
    service = provider_admin.ConversationProviderAdmin(ConversationApplication(auth.database))
    bundle = None
    if settings.sales_xray_enabled and settings.sales_xray_approval_path:
        try:
            bundle = load_pinned_approval(settings)
        except ValueError:
            bundle = None
    current = await service.current(actor, bundle=bundle) or {}
    activation = current.get("activation") or {}
    rows = {
        row.revision: row
        for row in (
            await auth.database.scalars(
                select(ConversationProviderConfiguration)
                .where(ConversationProviderConfiguration.tenant_id == actor.tenant_id)
                .order_by(ConversationProviderConfiguration.revision.desc())
                .limit(64)
            )
        ).all()
    }
    options = {item["revision"]: item for item in current.get("activation_options") or []}
    active = rows.get(activation.get("revision"))
    in_use = None if active is None else _transcription(active)
    # The classic configuration both Gemini ones derive from: the active one while it is
    # on Scribe, else the newest saved configuration that is.
    classic = (
        active
        if active is not None and in_use is not None and in_use["provider"] != "gemini"
        else next(
            (
                row
                for _, row in sorted(rows.items(), reverse=True)
                if (_transcription(row) or {}).get("provider") not in (None, "gemini")
            ),
            None,
        )
    )
    tiers: dict[str, Any] = {}
    for tier, _, flex, one_pass, luna, profile_id in _TIERS:
        derived = None
        unavailable = None if classic is not None else "no_classic_configuration"
        if classic is not None:
            try:
                derived = c2_route.derive_configuration(
                    parse_registry_config(classic.configuration),
                    flex=flex,
                    one_pass=one_pass,
                    luna=luna,
                )
            except c2_route.SealError as error:
                # e.g. Luna needs an OpenAI GPT-6 Luna entry, added in Providers first.
                derived, unavailable = None, str(error)
            except (ProviderRegistryError, TypeError, ValueError):
                derived, unavailable = None, "configuration_unreadable"
        saved = next(
            (
                revision
                for revision, row in sorted(rows.items(), reverse=True)
                if derived is not None and row.configuration_sha256 == derived.digest
            ),
            None,
        )
        tiers[tier] = {
            "model": c2_route.MODEL + (":flex" if flex else ""),
            "profile_id": profile_id,
            "unavailable": unavailable,
            "configuration_sha256": None if derived is None else derived.digest,
            "saved_revision": saved,
            "approved": saved is not None and saved in options,
        }
    return {
        "latest_revision": max(rows) if rows else 0,
        "sealed_bundle": None if bundle is None else bundle.digest,
        "active": None
        if active is None
        else {
            "revision": active.revision,
            "configuration_sha256": active.configuration_sha256,
            "transcription": in_use,
            "flex": _uses_flex(active),
            "one_pass": _uses_one_pass(active),
            "openai": _uses_openai(active),
        },
        **tiers,
        "classic_revision": None
        if classic is None or classic.revision not in options
        else classic.revision,
        "confirm": OWNER_CONFIRM_WORD,
        "openai_confirm": provider_admin.OPENAI_CONFIRM_WORD,
    }


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

    @router.get("/v1/admin/analysis-pipeline/transcription")
    async def transcription(
        request: Request, response: Response, auth: AuthenticatedTransaction = dependency
    ) -> dict[str, Any]:
        actor = await admit(request, response, auth)
        try:
            return await _transcription_view(auth, actor, settings)
        except ConversationError as error:
            raise HTTPException(error.status, str(error)) from None

    @router.post("/v1/admin/analysis-pipeline/transcription/prepare")
    async def prepare_transcription(
        request: Request,
        response: Response,
        auth: AuthenticatedTransaction = dependency,
        command: PrepareCommand | None = None,
    ) -> dict[str, Any]:
        """Save today's Scribe configuration with C2 on Gemini 3.1 Flash-Lite (``flex``:
        C2, C4 and C5 on Gemini Flex; ``one_pass``: C4 as the one-pass request) as a new
        provider revision. Nothing changes until Root seals it and the owner switches."""
        try:
            require_safe_origin(request, settings)
        except DomainError:
            raise HTTPException(403, "Use this Admin page to continue.") from None
        actor = await admit(request, response, auth)
        tier_name = "standard" if command is None else command.tier
        name, _, flex, one_pass, luna, _ = next(item for item in _TIERS if item[1] == tier_name)
        view = await _transcription_view(auth, actor, settings)
        tier = view[name]
        if tier["saved_revision"] is not None:
            return view
        if tier["configuration_sha256"] is None:
            raise HTTPException(409, "There is no Scribe configuration to start from.")
        classic = next(
            (
                row
                for row in (
                    await auth.database.scalars(
                        select(ConversationProviderConfiguration)
                        .where(ConversationProviderConfiguration.tenant_id == actor.tenant_id)
                        .order_by(ConversationProviderConfiguration.revision.desc())
                        .limit(64)
                    )
                ).all()
                if (_transcription(row) or {}).get("provider") not in (None, "gemini")
            ),
            None,
        )
        if classic is None:
            raise HTTPException(409, "There is no Scribe configuration to start from.")
        derived = c2_route.derive_configuration(
            parse_registry_config(classic.configuration), flex=flex, one_pass=one_pass, luna=luna
        )
        service = provider_admin.ConversationProviderAdmin(ConversationApplication(auth.database))
        try:
            await service.save(
                actor,
                derived.as_dict(),
                expected_revision=view["latest_revision"],
                key=f"one-pass-c2:{derived.digest}",
            )
        except ConversationError as error:
            raise HTTPException(error.status, str(error)) from None
        await AuditRepository(auth.database).append_for_actor(
            actor,
            action="analysis_pipeline.gemini_transcription_prepared",
            resource_type="conversation_provider_configuration",
            resource_id=derived.digest,
            payload={
                "from_revision": classic.revision,
                "configuration_sha256": derived.digest,
                "tier": tier_name,
            },
        )
        return await _transcription_view(auth, actor, settings)

    application.include_router(router)
