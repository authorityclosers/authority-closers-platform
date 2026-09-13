"""Read-only saved audio measurements through the existing AC session boundary."""

from typing import Any
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Request, Response

from ac_platform.conversation_intelligence.application import (
    ConversationApplication,
    ConversationError,
)
from ac_platform.conversation_intelligence.measurement_view import ConversationMeasurements
from ac_platform.http.auth import AuthenticatedTransaction, RequireActor

_PRIVATE_HEADERS = {"Cache-Control": "private, no-store"}


def install_measurement_routes(
    router: APIRouter,
    require_actor: RequireActor,
) -> None:
    dependency = Depends(require_actor, scope="function")

    @router.get("/recordings/{recording_id}/measurements")
    async def measurements(
        recording_id: UUID,
        request: Request,
        response: Response,
        auth: AuthenticatedTransaction = dependency,
    ) -> dict[str, Any]:
        response.headers.update(_PRIVATE_HEADERS)
        if request.query_params:
            raise HTTPException(
                422,
                "Recording access comes from your current AC session.",
                headers=_PRIVATE_HEADERS,
            )
        application = ConversationApplication(auth.database)
        try:
            return await ConversationMeasurements(application).get(
                auth.resolved.actor, recording_id
            )
        except ConversationError as error:
            raise HTTPException(error.status, str(error), headers=_PRIVATE_HEADERS) from None
