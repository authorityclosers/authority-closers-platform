"""Authenticated academy public identity and opt-in leaderboard HTTP boundary."""

from __future__ import annotations

from typing import Annotated, Any, Literal

from fastapi import APIRouter, Depends, FastAPI, HTTPException, Query, Request, Response
from pydantic import BaseModel, ConfigDict, Field, StrictBool, StrictInt

from ac_platform.application.settings import Settings
from ac_platform.community.application import CommunityApplication
from ac_platform.http.auth import AuthenticatedTransaction, RequireActor, require_safe_origin


class UsernameClaimRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    username: str = Field(max_length=128)


class LeaderboardOptInRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    opted_in: StrictBool
    expected_revision: StrictInt = Field(ge=1)


class CommunityPolicyResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    version: Literal["all_time_practice_xp_v1"]
    period: Literal["all_time"]
    measure: Literal["confirmed_practice_xp"]
    ranking: Literal["competition"]
    privacy: Literal["academy_opt_in"]


class CommunityProfileResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    username: str | None
    leaderboard_opted_in: bool
    revision: int
    leaderboard_policy: CommunityPolicyResponse


class LeaderboardPolicyResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    version: Literal["all_time_practice_xp_v1"]
    label: Literal["All-time practice XP"]
    period: Literal["all_time"]
    ranking: Literal["competition"]
    scope: Literal["academy"]


class LeaderboardItemResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    rank: int = Field(ge=1)
    username: str = Field(min_length=3, max_length=30)
    xp_total: int = Field(gt=0)
    is_current_learner: bool


class LeaderboardResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    policy: LeaderboardPolicyResponse
    items: list[LeaderboardItemResponse]
    next_cursor: str | None


def install_community_http(
    application: FastAPI,
    *,
    settings: Settings,
    require_actor: RequireActor,
) -> None:
    router = APIRouter(prefix="/v1/community", tags=["learner-community"])
    actor_dependency = Depends(require_actor, scope="function")

    def admitted(
        auth: AuthenticatedTransaction,
        request: Request,
        response: Response,
    ) -> None:
        if auth.resolved.actor.tenant_id is None or auth.resolved.membership_role != "learner":
            raise HTTPException(403, "Select your learner academy to open community identity.")
        if request.query_params:
            raise HTTPException(422, "Community profile does not accept account selectors.")
        response.headers["cache-control"] = "private, no-store"

    @router.get("/profile", response_model=CommunityProfileResponse)
    async def profile(
        request: Request,
        response: Response,
        auth: AuthenticatedTransaction = actor_dependency,
    ) -> dict[str, Any]:
        admitted(auth, request, response)
        return await CommunityApplication(auth.database).profile(auth.resolved.actor)

    @router.put("/username", response_model=CommunityProfileResponse)
    async def claim_username(
        payload: UsernameClaimRequest,
        request: Request,
        response: Response,
        auth: AuthenticatedTransaction = actor_dependency,
    ) -> dict[str, Any]:
        admitted(auth, request, response)
        require_safe_origin(request, settings)
        return await CommunityApplication(auth.database).claim_username(
            auth.resolved.actor,
            payload.username,
        )

    @router.put("/leaderboard-opt-in", response_model=CommunityProfileResponse)
    async def set_leaderboard_opt_in(
        payload: LeaderboardOptInRequest,
        request: Request,
        response: Response,
        auth: AuthenticatedTransaction = actor_dependency,
    ) -> dict[str, Any]:
        admitted(auth, request, response)
        require_safe_origin(request, settings)
        return await CommunityApplication(auth.database).set_leaderboard_opt_in(
            auth.resolved.actor,
            opted_in=payload.opted_in,
            expected_revision=payload.expected_revision,
        )

    @router.get("/leaderboard", response_model=LeaderboardResponse)
    async def leaderboard(
        request: Request,
        response: Response,
        limit: Annotated[int, Query(ge=1, le=100)] = 25,
        cursor: Annotated[str | None, Query(min_length=1, max_length=512)] = None,
        auth: AuthenticatedTransaction = actor_dependency,
    ) -> dict[str, Any]:
        if auth.resolved.actor.tenant_id is None or auth.resolved.membership_role != "learner":
            raise HTTPException(403, "Select your learner academy to view the leaderboard.")
        if (
            not set(request.query_params).issubset({"limit", "cursor"})
            or len(request.query_params.multi_items()) != len(request.query_params)
        ):
            raise HTTPException(422, "Leaderboard accepts only pagination parameters.")
        response.headers["cache-control"] = "private, no-store"
        return await CommunityApplication(auth.database).leaderboard(
            auth.resolved.actor,
            limit=limit,
            cursor=cursor,
        )

    application.include_router(router)


__all__ = ["install_community_http"]
