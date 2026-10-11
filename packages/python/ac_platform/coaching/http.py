"""Private Coaching reads on the existing Sales Xray account session only."""

import asyncio
import re
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import TypeVar
from uuid import UUID

from fastapi import APIRouter, FastAPI, HTTPException, Request, Response
from sqlalchemy import select
from starlette.responses import StreamingResponse

from ac_platform.coaching.call import CallCoachingCache, CallCoachingView
from ac_platform.coaching.contracts import CoachingView
from ac_platform.coaching.dataset import DATASET_ROOT, read_topics, suggestions, verified_narration
from ac_platform.coaching.library import CoachingLibrary
from ac_platform.coaching.team import TeamCoachingView
from ac_platform.conversation_intelligence.acquisition_sessions import AcquisitionSessions
from ac_platform.conversation_intelligence.application import ConversationError
from ac_platform.conversation_intelligence.async_io import join_thread
from ac_platform.conversation_intelligence.guest_ownership import GuestOwnership
from ac_platform.conversation_intelligence.sales_xray_tenants import SALES_XRAY_MEMBER_ROLES
from ac_platform.http.conversation_playback import _PrivateAudioResponse, byte_range
from ac_platform.http.routes import RouteContext
from ac_platform.kernel.authz import ActorContext
from ac_platform.kernel.errors import DomainError
from ac_platform.tenancy.models import Membership, Organisation

CoachingRead = TypeVar("CoachingRead", CoachingView, CallCoachingView)

PRIVATE = {"Cache-Control": "private, no-store", "Vary": "Cookie"}


def install_coaching_http(application: FastAPI, ctx: RouteContext) -> None:
    router = APIRouter(prefix="/v1/me/coaching", tags=["coaching"])
    read_actor = getattr(ctx.require_actor, "read_only", ctx.require_actor)
    call_cache = CallCoachingCache()

    async def with_media(view: CoachingRead) -> CoachingRead:
        if view.focus is None:
            return view
        topics = await asyncio.to_thread(read_topics)
        clips = suggestions(topics, skill_id=view.focus.skill_id, gap_type=view.root_cause.gap_type)
        limitations = view.limitations
        if clips:
            limitations = tuple(
                item
                for item in limitations
                if item
                != (
                    "A relevant reviewed Dipak clip is not available yet; "
                    "use the structured text lesson."
                )
            ) + ("This clip uses labelled neutral placeholder narration of Dipak's script.",)
        return view.model_copy(update={"media_clips": clips, "limitations": limitations})

    @asynccontextmanager
    async def account_library(
        request: Request, response: Response
    ) -> AsyncIterator[tuple[CoachingLibrary, ActorContext]]:
        response.headers.update(PRIVATE)
        settings = ctx.settings
        if (
            settings.sales_xray_app_url is None
            or request.url.hostname != settings.sales_xray_app_url.host
        ):
            raise HTTPException(404, "Coaching is unavailable.", headers=PRIVATE)
        if request.query_params:
            raise HTTPException(
                422, "Coaching uses your signed-in account and workspace.", headers=PRIVATE
            )
        try:
            async with asynccontextmanager(read_actor)(request) as auth:
                actor = auth.resolved.actor
                tenant_id = actor.tenant_id
                if tenant_id is None or tenant_id == settings.operations_tenant_id:
                    raise HTTPException(403, "Choose a Sales Xray workspace.", headers=PRIVATE)
                member = await auth.database.scalar(
                    select(Membership)
                    .where(
                        Membership.tenant_id == tenant_id,
                        Membership.person_id == actor.person_id,
                        Membership.status == "active",
                        Membership.ended_at.is_(None),
                        Membership.role.in_(SALES_XRAY_MEMBER_ROLES),
                    )
                    .with_for_update(read=True)
                )
                organisation = await auth.database.scalar(
                    select(Organisation).where(
                        Organisation.tenant_id == tenant_id,
                    )
                )
                if member is None or (
                    tenant_id != settings.public_learner_tenant_id and organisation is None
                ):
                    raise HTTPException(
                        403, "Coaching is unavailable in this workspace.", headers=PRIVATE
                    )
                # AUT-1678: coaching is open to internal, free and unlimited
                # accounts. No payment/provider balance or analysis credit is read.
                sessions = AcquisitionSessions(
                    auth.database,
                    tenant_id=tenant_id,
                    policy_revision="AUT-1678-open-access",
                    operations_tenant_id=settings.operations_tenant_id,
                )
                yield CoachingLibrary(GuestOwnership(sessions)), actor
        except ConversationError as error:
            raise HTTPException(error.status, str(error), headers=PRIVATE) from None
        except DomainError:
            raise HTTPException(401, "Sign in to see your Coaching.", headers=PRIVATE) from None

    @router.get("", response_model=CoachingView, response_model_by_alias=True)
    async def coaching(request: Request, response: Response) -> CoachingView:
        async with account_library(request, response) as (library, actor):
            view = await library.read(actor)
            view = await with_media(view)
            return CoachingView.model_validate(
                view.model_copy(update={"session_id": actor.session_id})
            )

    @router.get(
        "/calls/{submission_id}", response_model=CallCoachingView, response_model_by_alias=True
    )
    async def call_coaching(
        submission_id: UUID, request: Request, response: Response
    ) -> CallCoachingView:
        async with account_library(request, response) as (library, actor):
            view = await library.read_call(actor, submission_id, call_cache)
            view = await with_media(view)
            return CallCoachingView.model_validate(
                view.model_copy(update={"session_id": actor.session_id})
            )

    @router.get("/team", response_model=TeamCoachingView, response_model_by_alias=True)
    async def team_coaching(request: Request, response: Response) -> TeamCoachingView:
        async with account_library(request, response) as (library, actor):
            view = await library.read_team(actor)
            return view.model_copy(update={"session_id": actor.session_id})

    @router.get("/media/{topic_id}/{revision}/{review_id}/source")
    async def media_source(
        topic_id: str, revision: str, review_id: UUID, request: Request, response: Response
    ) -> StreamingResponse:
        # Full access is the explicit current Coaching entitlement policy.
        # Do not expose a future limited stream until durable credits/usage
        # enforcement exists. A browser timeupdate is not a paywall.
        async with account_library(request, response) as (library, actor):
            now = await library.ownership.sessions._admit()
            await library.ownership.sessions._owner(None, actor, now, shared_identity_locks=True)
            if not re.fullmatch(r"[a-z0-9][a-z0-9_-]{0,99}", topic_id) or not re.fullmatch(
                r"[0-9a-f]{64}", revision
            ):
                raise HTTPException(404, "Coaching media is unavailable.", headers=PRIVATE)
            topics = await asyncio.to_thread(read_topics)
            topic = next((t for t in topics if t.topic_id == topic_id), None)
            if (
                topic is None
                or topic.transcript.sha256 != revision
                or not any(clip.review.review_id == review_id for clip in topic.clips())
            ):
                raise HTTPException(404, "Coaching media is unavailable.", headers=PRIVATE)
            iterator = verified_narration(DATASET_ROOT, topic)
            try:
                # Complete hash verification occurs before the first byte.
                first = await join_thread(lambda: next(iterator, None))
                if first is None:
                    raise ValueError("Empty narration.")
            except BaseException as error:
                await join_thread(iterator.close)
                if isinstance(error, (OSError, ValueError)):
                    raise HTTPException(
                        404, "Coaching media is unavailable.", headers=PRIVATE
                    ) from None
                raise
            ranges = request.headers.getlist("range")
            try:
                size = topic.narration.source_bytes
                if len(ranges) > 1:
                    raise ValueError("Duplicate range.")
                start, end = byte_range(ranges[0] if ranges else None, size)
            except (OSError, ValueError):
                iterator.close()
                raise HTTPException(
                    416, "Use one valid audio byte range.", headers=PRIVATE
                ) from None
            headers = {
                **PRIVATE,
                "Accept-Ranges": "bytes",
                "Content-Length": str(end - start + 1),
                "X-Content-Type-Options": "nosniff",
            }
            if ranges:
                headers["Content-Range"] = f"bytes {start}-{end}/{size}"
            return _PrivateAudioResponse(
                iterator,
                first,
                start,
                end,
                status_code=206 if ranges else 200,
                media_type="audio/mpeg",
                headers=headers,
            )

    application.include_router(router)
