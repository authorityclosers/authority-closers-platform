"""Read-only Sales Xray surface, installable in the existing AC API."""

from collections.abc import Awaitable
from contextlib import asynccontextmanager
from typing import Annotated, Any
from uuid import UUID

from fastapi import APIRouter, Depends, FastAPI, Header, HTTPException, Request, Response

from ac_platform.application.settings import Settings
from ac_platform.conversation_intelligence.application import (
    ConversationApplication,
    ConversationError,
)
from ac_platform.conversation_intelligence.contracts import Capabilities, RecordingIntent, RunIntent
from ac_platform.conversation_intelligence.example import example_report
from ac_platform.conversation_intelligence.intake import ConversationIntake
from ac_platform.conversation_intelligence.report_store import ConversationReports
from ac_platform.http.auth import (
    AuthenticatedTransaction,
    AuthenticationRequired,
    RequireActor,
    require_safe_origin,
)
from ac_platform.http.conversation_intake import ConversationIntakeRuntime, install_intake_routes
from ac_platform.identity.services import IdentityResolutionError, SessionNotFoundError


def install_conversation_http(
    app: FastAPI,
    *,
    settings: Settings | None = None,
    require_actor: RequireActor | None = None,
    intake_runtime: ConversationIntakeRuntime | None = None,
) -> None:
    router = APIRouter(prefix="/v1/conversation", tags=["conversation-intelligence"])

    @router.get("/workspace")
    async def workspace(request: Request, response: Response) -> dict[str, Any]:
        response.headers["Cache-Control"] = "private, no-store"
        if request.query_params:
            raise HTTPException(422, "Scope comes from your current AC session.")
        answer: dict[str, Any] = {
            "authenticated": False,
            "intake_enabled": False,
            "sign_in_url": str(settings.public_app_url).rstrip("/") + "/login?next=/sales-xray"
            if settings
            else None,
            "message": "Sign in with your AC account to upload and manage your calls."
            if settings
            else "Select and play a call here while server upload is being connected.",
        }
        if require_actor is not None:
            try:
                async with asynccontextmanager(require_actor)(request) as auth:
                    application = ConversationApplication(auth.database)
                    await application.admit(auth.resolved.actor)
                    answer.update(authenticated=True, sign_in_url=None)
                    if intake_runtime is not None:
                        await ConversationIntake(application, intake_runtime.policy).admit(
                            auth.resolved.actor
                        )
                        answer.update(
                            intake_enabled=True,
                            message=(
                                "Your private workspace is ready for local audio analysis. "
                                "A sales report needs its approved provider run."
                            ),
                        )
                    else:
                        answer["message"] = (
                            "AC account connected. Upload is not enabled for this workspace."
                        )
            except (AuthenticationRequired, SessionNotFoundError, IdentityResolutionError):
                pass
            except ConversationError as error:
                answer["message"] = str(error)
        return answer

    @router.get("/capabilities", response_model=Capabilities)
    def capabilities(response: Response) -> Capabilities:
        response.headers["Cache-Control"] = "no-store"
        return Capabilities()

    @router.get("/example")
    def example(response: Response) -> dict[str, Any]:
        response.headers["Cache-Control"] = "no-store"
        return example_report()

    if settings is not None and require_actor is not None:
        if intake_runtime is not None:
            install_intake_routes(router, settings, require_actor, intake_runtime)
        dependency = Depends(require_actor, scope="function")

        def admitted(request: Request, response: Response) -> None:
            if request.query_params:
                raise HTTPException(422, "Account and tenant selectors are not accepted.")
            response.headers["Cache-Control"] = "private, no-store"

        async def result(call: Awaitable[Any]) -> Any:
            try:
                return await call
            except ConversationError as error:
                raise HTTPException(error.status, str(error)) from None

        @router.post("/recordings", status_code=201)
        async def register(
            payload: RecordingIntent,
            request: Request,
            response: Response,
            key: Annotated[str, Header(alias="Idempotency-Key", min_length=1, max_length=128)],
            auth: AuthenticatedTransaction = dependency,
        ) -> Any:
            admitted(request, response)
            require_safe_origin(request, settings)
            return await result(
                ConversationApplication(auth.database).register(
                    auth.resolved.actor,
                    payload,
                    key=key,
                )
            )

        @router.get("/recordings")
        async def recordings(
            request: Request,
            response: Response,
            auth: AuthenticatedTransaction = dependency,
        ) -> Any:
            admitted(request, response)
            return await result(
                ConversationReports(ConversationApplication(auth.database)).history(
                    auth.resolved.actor
                )
            )

        @router.get("/recordings/{recording_id}")
        async def get_recording(
            recording_id: UUID,
            request: Request,
            response: Response,
            auth: AuthenticatedTransaction = dependency,
        ) -> Any:
            admitted(request, response)
            return await result(
                ConversationApplication(auth.database).get(
                    auth.resolved.actor,
                    recording_id,
                )
            )

        @router.post("/runs", status_code=202)
        async def request_run(
            payload: RunIntent,
            request: Request,
            response: Response,
            key: Annotated[str, Header(alias="Idempotency-Key", min_length=1, max_length=128)],
            auth: AuthenticatedTransaction = dependency,
        ) -> Any:
            admitted(request, response)
            require_safe_origin(request, settings)
            return await result(
                ConversationApplication(auth.database).request_run(
                    auth.resolved.actor,
                    payload,
                    key=key,
                )
            )

        @router.get("/runs/{run_id}")
        async def get_run(
            run_id: UUID,
            request: Request,
            response: Response,
            auth: AuthenticatedTransaction = dependency,
        ) -> Any:
            admitted(request, response)
            return await result(
                ConversationApplication(auth.database).get_run(
                    auth.resolved.actor,
                    run_id,
                )
            )

        @router.get("/runs/{run_id}/report")
        async def get_report(
            run_id: UUID,
            request: Request,
            response: Response,
            auth: AuthenticatedTransaction = dependency,
        ) -> Any:
            admitted(request, response)
            return await result(
                ConversationReports(ConversationApplication(auth.database)).get(
                    auth.resolved.actor, run_id
                )
            )

        @router.get("/recordings/{recording_id}/transcript")
        async def get_transcript(
            recording_id: UUID,
            request: Request,
            response: Response,
            auth: AuthenticatedTransaction = dependency,
        ) -> Any:
            admitted(request, response)
            return await result(
                ConversationReports(ConversationApplication(auth.database)).transcript(
                    auth.resolved.actor, recording_id
                )
            )

        @router.get("/recordings/{recording_id}/checkpoints")
        async def get_checkpoints(
            recording_id: UUID,
            request: Request,
            response: Response,
            auth: AuthenticatedTransaction = dependency,
        ) -> Any:
            admitted(request, response)
            return await result(
                ConversationApplication(auth.database).checkpoints(
                    auth.resolved.actor,
                    recording_id,
                )
            )

        @router.delete("/recordings/{recording_id}", status_code=202)
        async def delete_recording(
            recording_id: UUID,
            request: Request,
            response: Response,
            key: Annotated[str, Header(alias="Idempotency-Key", min_length=1, max_length=128)],
            auth: AuthenticatedTransaction = dependency,
        ) -> Any:
            admitted(request, response)
            require_safe_origin(request, settings)
            return await result(
                ConversationApplication(auth.database).request_deletion(
                    auth.resolved.actor,
                    recording_id,
                    key=key,
                )
            )

    app.include_router(router)
