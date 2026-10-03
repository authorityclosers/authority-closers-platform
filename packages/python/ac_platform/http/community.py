"""Authenticated global public identity and academy leaderboard HTTP boundary."""

from __future__ import annotations

from typing import Annotated, Any, Literal
from uuid import UUID

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
    expected_revision: StrictInt = Field(ge=0)


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


class DiscoveryPreferenceRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    discoverable: StrictBool
    public_display_name: str | None = Field(default=None, max_length=120)
    avatar_asset_id: UUID | None = None
    expected_revision: StrictInt = Field(ge=0)


class DiscoveryPreferenceResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    username: str | None
    discoverable: bool
    public_display_name: str | None
    avatar_asset_id: UUID | None
    revision: int


class PublicCommunityProfileResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    username: str = Field(min_length=3, max_length=30)
    display_name: str | None
    avatar_asset_id: UUID | None
    practice_xp_total: int | None = Field(default=None, ge=0)
    connection_state: Literal["pending", "accepted", "declined", "removed"] | None = None
    connection_incoming: bool | None = None


class PublicCommunitySearchResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    items: list[PublicCommunityProfileResponse]


class CommunityConnectionResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    username: str = Field(min_length=3, max_length=30)
    state: Literal["pending", "accepted", "declined", "removed"]
    incoming: bool


class CommunityConnectionsResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    items: list[CommunityConnectionResponse]


class CommunityReportRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    reason: Literal["spam", "harassment", "impersonation", "other"]


def install_community_http(
    application: FastAPI,
    *,
    settings: Settings,
    require_actor: RequireActor,
) -> None:
    router = APIRouter(prefix="/v1/community", tags=["learner-community"])
    actor_dependency = Depends(require_actor, scope="function")

    def account_admitted(
        auth: AuthenticatedTransaction,
        request: Request,
        response: Response,
    ) -> None:
        del auth
        if request.query_params:
            raise HTTPException(422, "Community identity does not accept account selectors.")
        response.headers["cache-control"] = "private, no-store"

    def academy_admitted(
        auth: AuthenticatedTransaction,
        request: Request,
        response: Response,
        *,
        allowed_query_params: set[str] | None = None,
    ) -> None:
        if auth.resolved.actor.tenant_id is None or auth.resolved.membership_role != "learner":
            raise HTTPException(403, "Select your learner academy to manage its leaderboard.")
        if allowed_query_params is None and request.query_params:
            raise HTTPException(422, "Community profile does not accept account selectors.")
        response.headers["cache-control"] = "private, no-store"

    @router.get("/profile", response_model=CommunityProfileResponse)
    async def profile(
        request: Request,
        response: Response,
        auth: AuthenticatedTransaction = actor_dependency,
    ) -> dict[str, Any]:
        account_admitted(auth, request, response)
        return await CommunityApplication(auth.database).profile(auth.resolved.actor)

    @router.put("/username", response_model=CommunityProfileResponse)
    async def claim_username(
        payload: UsernameClaimRequest,
        request: Request,
        response: Response,
        auth: AuthenticatedTransaction = actor_dependency,
    ) -> dict[str, Any]:
        account_admitted(auth, request, response)
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
        academy_admitted(auth, request, response)
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
        if not set(request.query_params).issubset({"limit", "cursor"}) or len(
            request.query_params.multi_items()
        ) != len(request.query_params):
            raise HTTPException(422, "Leaderboard accepts only pagination parameters.")
        response.headers["cache-control"] = "private, no-store"
        return await CommunityApplication(auth.database).leaderboard(
            auth.resolved.actor,
            limit=limit,
            cursor=cursor,
        )

    @router.get("/discovery", response_model=DiscoveryPreferenceResponse)
    async def discovery(
        request: Request,
        response: Response,
        auth: AuthenticatedTransaction = actor_dependency,
    ) -> dict[str, Any]:
        academy_admitted(auth, request, response)
        return await CommunityApplication(auth.database).discovery_profile(auth.resolved.actor)

    @router.put("/discovery", response_model=DiscoveryPreferenceResponse)
    async def set_discovery(
        payload: DiscoveryPreferenceRequest,
        request: Request,
        response: Response,
        auth: AuthenticatedTransaction = actor_dependency,
    ) -> dict[str, Any]:
        academy_admitted(auth, request, response)
        require_safe_origin(request, settings)
        return await CommunityApplication(auth.database).set_discovery(
            auth.resolved.actor,
            discoverable=payload.discoverable,
            public_display_name=payload.public_display_name,
            avatar_asset_id=payload.avatar_asset_id,
            expected_revision=payload.expected_revision,
        )

    @router.get("/search", response_model=PublicCommunitySearchResponse)
    async def search(
        query: Annotated[str, Query(min_length=3, max_length=30)],
        request: Request,
        response: Response,
        limit: Annotated[int, Query(ge=1, le=25)] = 10,
        auth: AuthenticatedTransaction = actor_dependency,
    ) -> dict[str, Any]:
        academy_admitted(auth, request, response, allowed_query_params={"query", "limit"})
        if set(request.query_params) - {"query", "limit"}:
            raise HTTPException(422, "Community search accepts only query and limit.")
        return await CommunityApplication(auth.database).search_public_profiles(
            auth.resolved.actor, query=query, limit=limit
        )

    @router.get("/public/{username}", response_model=PublicCommunityProfileResponse)
    async def public_profile(
        username: str,
        request: Request,
        response: Response,
        auth: AuthenticatedTransaction = actor_dependency,
    ) -> dict[str, Any]:
        academy_admitted(auth, request, response)
        result = await CommunityApplication(auth.database)._public_candidate(
            auth.resolved.actor, username
        )
        result.pop("person_id", None)
        return result

    @router.get("/connections", response_model=CommunityConnectionsResponse)
    async def connections(
        request: Request,
        response: Response,
        auth: AuthenticatedTransaction = actor_dependency,
    ) -> dict[str, Any]:
        academy_admitted(auth, request, response)
        return await CommunityApplication(auth.database).connections(auth.resolved.actor)

    @router.post("/connections/{username}", response_model=CommunityConnectionResponse)
    async def request_connection(
        username: str,
        request: Request,
        response: Response,
        auth: AuthenticatedTransaction = actor_dependency,
    ) -> dict[str, Any]:
        academy_admitted(auth, request, response)
        require_safe_origin(request, settings)
        return await CommunityApplication(auth.database).request_connection(
            auth.resolved.actor, username
        )

    @router.post("/connections/{username}/accept", response_model=CommunityConnectionResponse)
    async def accept_connection(
        username: str,
        request: Request,
        response: Response,
        auth: AuthenticatedTransaction = actor_dependency,
    ) -> dict[str, Any]:
        academy_admitted(auth, request, response)
        require_safe_origin(request, settings)
        return await CommunityApplication(auth.database).respond_connection(
            auth.resolved.actor, username, accept=True
        )

    @router.post("/connections/{username}/decline", response_model=CommunityConnectionResponse)
    async def decline_connection(
        username: str,
        request: Request,
        response: Response,
        auth: AuthenticatedTransaction = actor_dependency,
    ) -> dict[str, Any]:
        academy_admitted(auth, request, response)
        require_safe_origin(request, settings)
        return await CommunityApplication(auth.database).respond_connection(
            auth.resolved.actor, username, accept=False
        )

    @router.delete("/connections/{username}", response_model=CommunityConnectionResponse)
    async def remove_connection(
        username: str,
        request: Request,
        response: Response,
        auth: AuthenticatedTransaction = actor_dependency,
    ) -> dict[str, Any]:
        academy_admitted(auth, request, response)
        require_safe_origin(request, settings)
        return await CommunityApplication(auth.database).remove_connection(
            auth.resolved.actor, username
        )

    @router.post("/blocks/{username}")
    async def block(
        username: str,
        request: Request,
        response: Response,
        auth: AuthenticatedTransaction = actor_dependency,
    ) -> dict[str, Any]:
        academy_admitted(auth, request, response)
        require_safe_origin(request, settings)
        return await CommunityApplication(auth.database).block(auth.resolved.actor, username)

    @router.post("/reports/{username}")
    async def report(
        username: str,
        payload: CommunityReportRequest,
        request: Request,
        response: Response,
        auth: AuthenticatedTransaction = actor_dependency,
    ) -> dict[str, Any]:
        academy_admitted(auth, request, response)
        require_safe_origin(request, settings)
        return await CommunityApplication(auth.database).report(
            auth.resolved.actor, username, reason=payload.reason
        )

    application.include_router(router)


__all__ = ["install_community_http"]
