"""Private Coaching reads on the existing Sales Xray account session only."""

import asyncio
import re
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any, Literal, TypeVar
from uuid import UUID

from fastapi import APIRouter, FastAPI, HTTPException, Request, Response
from pydantic import BaseModel, ConfigDict, Field, ValidationError
from sqlalchemy import select
from starlette.requests import ClientDisconnect
from starlette.responses import StreamingResponse

from ac_platform.coaching import placeholder
from ac_platform.coaching.call import NO_CLIP, CallCoachingCache, CallCoachingView
from ac_platform.coaching.contracts import CoachingView
from ac_platform.coaching.dataset import DATASET_ROOT, read_topics, suggestions, verified_narration
from ac_platform.coaching.library import CoachingLibrary
from ac_platform.coaching.sandbox import ReportBind, SandboxCoaching
from ac_platform.coaching.sharing_store import (
    CurrentFocus,
    SharingView,
    latest_context,
    read_sharing,
    record_context,
    record_feedback,
    set_sharing,
)
from ac_platform.coaching.team import TeamCoachingView
from ac_platform.conversation_intelligence.acquisition_reports import AcquisitionReports
from ac_platform.conversation_intelligence.acquisition_sessions import AcquisitionSessions
from ac_platform.conversation_intelligence.application import ConversationError
from ac_platform.conversation_intelligence.async_io import join_thread
from ac_platform.conversation_intelligence.checkpoints import content_hash
from ac_platform.conversation_intelligence.guest_ownership import GuestOwnership
from ac_platform.conversation_intelligence.sales_xray_tenants import SALES_XRAY_MEMBER_ROLES
from ac_platform.conversation_intelligence.synthetic_imports import SyntheticImports
from ac_platform.http.auth import require_safe_origin
from ac_platform.http.conversation_playback import _PrivateAudioResponse, byte_range
from ac_platform.http.routes import RouteContext
from ac_platform.kernel.authz import ActorContext
from ac_platform.kernel.errors import DomainError
from ac_platform.tenancy.models import Membership, Organisation

CoachingRead = TypeVar("CoachingRead", CoachingView, CallCoachingView)

PRIVATE = {"Cache-Control": "private, no-store", "Vary": "Cookie"}


class ShareChoice(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    shared: bool
    expected_revision: int = Field(ge=0)


class ContextNote(BaseModel):
    """The learner's own words about their focus ("Add context")."""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    command_id: UUID
    focus_skill_id: str = Field(min_length=1, max_length=64)
    mission_origin_submission_id: UUID
    context: str = Field(min_length=1, max_length=1000)


class FeedbackChoice(BaseModel):
    model_config = ConfigDict(extra="forbid")
    command_id: UUID
    agreement: Literal["agree", "not_completely"]
    focus_skill_id: str = Field(min_length=1, max_length=64)
    mission_origin_submission_id: UUID


def install_coaching_http(application: FastAPI, ctx: RouteContext) -> None:
    router = APIRouter(prefix="/v1/me/coaching", tags=["coaching"])
    read_actor = getattr(ctx.require_actor, "read_only", ctx.require_actor)
    call_cache = CallCoachingCache()

    async def with_media(view: CoachingRead, *, their: bool = False) -> CoachingRead:
        if view.focus is None:
            return view
        topics = await asyncio.to_thread(read_topics)
        clips = suggestions(
            topics, skill_id=view.focus.skill_id, gap_type=view.root_cause.gap_type
        ) or await asyncio.to_thread(
            placeholder.clips_for,
            view.focus.skill_id,
            gap_type=view.root_cause.gap_type,
            their=their,
        )
        limitations = view.limitations
        if clips:
            limitations = tuple(item for item in limitations if item != NO_CLIP) + (
                "Dipak's lesson is read by a stand-in voice for now. The words are his script.",
            )
        return view.model_copy(update={"media_clips": clips, "limitations": limitations})

    @asynccontextmanager
    async def account_library(
        request: Request, response: Response, *, write: bool = False
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
        if write:
            try:
                require_safe_origin(request, settings)
            except DomainError:
                raise HTTPException(
                    403, "Use this Sales Xray page to continue.", headers=PRIVATE
                ) from None
        try:
            async with asynccontextmanager(ctx.require_actor if write else read_actor)(
                request
            ) as auth:
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

    async def sandbox_for(library: CoachingLibrary, actor: ActorContext) -> SandboxCoaching | None:
        """AC Sandbox reads for a current owner/admin of a flagged sandbox org.

        Everyone else, and every other organisation, keeps the normal reads.
        """
        sandbox = SandboxCoaching(library.database, library.ownership.tenant_id)
        if not await sandbox.flagged():
            return None
        try:
            await SyntheticImports(library.ownership).admit(actor)
        except ConversationError:
            # Not an owner/admin (or not admitted right now): the normal reads.
            return None
        return sandbox

    @router.get("", response_model=CoachingView, response_model_by_alias=True)
    async def coaching(request: Request, response: Response) -> CoachingView:
        async with account_library(request, response) as (library, actor):
            view = await library.read(actor)
            view = await with_media(view)
            view = await with_context(
                view, actor.person_id, library.ownership.tenant_id, library.database
            )
            sandbox = await sandbox_for(library, actor)
            # Your own (real) coaching; a pointer when fictional reps exist.
            reps = await sandbox.rep_count(actor.person_id) if sandbox else 0
            return CoachingView.model_validate(
                view.model_copy(update={"session_id": actor.session_id, "sandbox_reps": reps})
            )

    @router.get(
        "/calls/{submission_id}", response_model=CallCoachingView, response_model_by_alias=True
    )
    async def call_coaching(
        submission_id: UUID, request: Request, response: Response
    ) -> CallCoachingView:
        async with account_library(request, response) as (library, actor):
            sandbox = await sandbox_for(library, actor)

            async def loader_report(call_id: UUID) -> ReportBind | None:
                # A call opened by the dev loader's id is a real call of a
                # fictional rep: bind the authored view to that report. The read
                # is the existing owner/admin organisation read, freshly
                # authorized; only its identity hashes are used.
                try:
                    envelope = await AcquisitionReports(library.ownership).report(
                        call_id,
                        actor=actor,
                        shared_identity_locks=True,
                        allow_organisation_read=True,
                    )
                    return ReportBind(
                        recording_id=UUID(envelope["recording_id"]),
                        source_sha256=envelope["source_sha256"],
                        transcript_revision=envelope["transcript_revision"],
                        report_revision=content_hash(envelope["report"]),
                    )
                except (ConversationError, KeyError, TypeError, ValueError):
                    return None

            fictional = (
                await sandbox.read_call(actor.person_id, submission_id, loader_report)
                if sandbox
                else None
            )
            view = fictional or await library.read_call(actor, submission_id, call_cache)
            view = await with_media(view)
            return CallCoachingView.model_validate(
                view.model_copy(update={"session_id": actor.session_id})
            )

    @router.get("/team", response_model=TeamCoachingView, response_model_by_alias=True)
    async def team_coaching(request: Request, response: Response) -> TeamCoachingView:
        async with account_library(request, response) as (library, actor):
            sandbox = await sandbox_for(library, actor)
            fictional = await sandbox.read_team(actor.person_id) if sandbox else None
            view = (
                fictional
                if fictional is not None and fictional.analysed_calls
                else await library.read_team(actor)
            )
            return view.model_copy(update={"session_id": actor.session_id})

    @router.get("/people/{person_id}", response_model=CoachingView, response_model_by_alias=True)
    async def person_coaching(
        person_id: UUID, request: Request, response: Response
    ) -> CoachingView:
        # A fictional AC Sandbox rep for the person who imported it, or a real
        # rep who shares their coaching with this owner/admin. Private by
        # default: an unshared rep looks the same as no rep.
        async with account_library(request, response) as (library, actor):
            sandbox = await sandbox_for(library, actor)
            view = await sandbox.read_rep(actor.person_id, person_id) if sandbox else None
            if view is None:
                try:
                    view = await library.read_shared(actor, person_id)
                except ConversationError as error:
                    raise HTTPException(
                        404 if error.status in (403, 404) else error.status,
                        "This coaching is not shared with you.",
                        headers=PRIVATE,
                    ) from None
                view = await with_context(
                    view, person_id, library.ownership.tenant_id, library.database
                )
            view = await with_media(view, their=True)
            return CoachingView.model_validate(
                view.model_copy(update={"session_id": actor.session_id})
            )

    async def read_body(request: Request, *, limit: int = 1024) -> bytes | HTTPException:
        """Read a write's JSON body before any lock is taken.

        A wrong type or size is returned, not raised: the caller raises it
        only once the person is signed in (authenticate first).
        """
        content_types = request.headers.getlist("content-type")
        if (
            len(content_types) != 1
            or content_types[0].split(";", 1)[0].strip().lower() != "application/json"
        ):
            return HTTPException(415, "Send this choice as JSON.", headers=PRIVATE)
        raw = bytearray()
        try:
            async with asyncio.timeout(5):
                async for block in request.stream():
                    if len(raw) + len(block) > limit:
                        return HTTPException(413, "This choice is too large.", headers=PRIVATE)
                    raw.extend(block)
        except (TimeoutError, ClientDisconnect):
            raise HTTPException(
                408, "The request was interrupted. Try again.", headers=PRIVATE
            ) from None
        return bytes(raw)

    def parse_body[T: BaseModel](body: bytes | HTTPException, model: type[T]) -> T:
        if isinstance(body, HTTPException):
            raise body
        try:
            return model.model_validate_json(body)
        except ValidationError:
            raise HTTPException(422, "Choose a valid option.", headers=PRIVATE) from None

    def request_id(request: Request) -> str | None:
        value = getattr(request.state, "request_id", None)
        return value if isinstance(value, str) else None

    @router.get("/sharing", response_model=SharingView)
    async def sharing(request: Request, response: Response) -> SharingView:
        async with account_library(request, response) as (library, actor):
            try:
                return await read_sharing(
                    library.database,
                    tenant_id=library.ownership.tenant_id,
                    person_id=actor.person_id,
                )
            except ConversationError as error:
                raise HTTPException(error.status, str(error), headers=PRIVATE) from None

    @router.put("/sharing", response_model=SharingView)
    async def change_sharing(request: Request, response: Response) -> SharingView:
        # The body is read before any transaction or row lock is taken.
        body = await read_body(request)
        async with account_library(request, response, write=True) as (library, actor):
            choice = parse_body(body, ShareChoice)
            try:
                return await set_sharing(
                    library.database,
                    actor=actor,
                    tenant_id=library.ownership.tenant_id,
                    shared=choice.shared,
                    expected_revision=choice.expected_revision,
                    request_id=request_id(request),
                )
            except ConversationError as error:
                raise HTTPException(error.status, str(error), headers=PRIVATE) from None

    async def with_context(
        view: CoachingView, person_id: UUID, tenant_id: UUID, db: Any
    ) -> CoachingView:
        """Show the person's own newest note about this focus with the likely reason."""
        if view.focus is None or view.mission is None or view.sandbox:
            return view
        note = await latest_context(
            db,
            tenant_id=tenant_id,
            person_id=person_id,
            focus_skill_id=view.focus.skill_id,
            mission_origin_submission_id=view.mission.origin_submission_id,
        )
        if note is None:
            return view
        return view.model_copy(
            update={"root_cause": view.root_cause.model_copy(update={"learner_context": note})}
        )

    def current_focus(library: CoachingLibrary, actor: ActorContext) -> CurrentFocus:
        """The focus skill and mission origin My coaching shows this person now."""

        async def read() -> tuple[str, UUID] | None:
            view = await library.read(actor)
            if view.focus is None or view.mission is None:
                return None
            return view.focus.skill_id, view.mission.origin_submission_id

        return read

    @router.post("/context", status_code=204)
    async def add_context(request: Request, response: Response) -> Response:
        # 1,000 characters of Devanagari are up to 3 KB of UTF-8; read before locks.
        body = await read_body(request, limit=4096)
        async with account_library(request, response, write=True) as (library, actor):
            note = parse_body(body, ContextNote)
            try:
                await record_context(
                    library.database,
                    actor=actor,
                    tenant_id=library.ownership.tenant_id,
                    command_id=note.command_id,
                    focus_skill_id=note.focus_skill_id,
                    mission_origin_submission_id=note.mission_origin_submission_id,
                    context=note.context,
                    current_focus=current_focus(library, actor),
                    request_id=request_id(request),
                )
            except ConversationError as error:
                raise HTTPException(error.status, str(error), headers=PRIVATE) from None
        return Response(status_code=204, headers=PRIVATE)

    @router.post("/feedback", status_code=204)
    async def feedback(request: Request, response: Response) -> Response:
        body = await read_body(request)
        async with account_library(request, response, write=True) as (library, actor):
            choice = parse_body(body, FeedbackChoice)
            # Feedback attaches to the learner's current focus and mission,
            # derived here; it never changes a score or another person.
            try:
                await record_feedback(
                    library.database,
                    actor=actor,
                    tenant_id=library.ownership.tenant_id,
                    command_id=choice.command_id,
                    agreement=choice.agreement,
                    focus_skill_id=choice.focus_skill_id,
                    mission_origin_submission_id=choice.mission_origin_submission_id,
                    current_focus=current_focus(library, actor),
                    request_id=request_id(request),
                )
            except ConversationError as error:
                raise HTTPException(error.status, str(error), headers=PRIVATE) from None
        return Response(status_code=204, headers=PRIVATE)

    @router.get("/media/{topic_id}/{revision}/{review_id}/source")
    async def media_source(
        topic_id: str, revision: str, review_id: UUID, request: Request, response: Response
    ) -> StreamingResponse:
        # Reviewed exports and free placeholder topics stream in full; a locked
        # placeholder topic streams only its preview cut file (or is refused),
        # here, not just in the browser. A browser timeupdate is not a paywall.
        async with account_library(request, response) as (library, actor):
            now = await library.ownership.sessions._admit()
            await library.ownership.sessions._owner(None, actor, now, shared_identity_locks=True)
            if not re.fullmatch(r"[a-z0-9][a-z0-9_-]{0,99}", topic_id) or not re.fullmatch(
                r"[0-9a-f]{64}", revision
            ):
                raise HTTPException(404, "Coaching media is unavailable.", headers=PRIVATE)
            free = placeholder.playable(topic_id, revision, review_id)
            if free is not None:
                # A locked topic streams only its separate preview cut.
                iterator = placeholder.narration(free)
                size = placeholder.audio_file(free)[1]
            else:
                topics = await asyncio.to_thread(read_topics)
                topic = next((t for t in topics if t.topic_id == topic_id), None)
                if (
                    topic is None
                    or topic.transcript.sha256 != revision
                    or not any(clip.review.review_id == review_id for clip in topic.clips())
                ):
                    raise HTTPException(404, "Coaching media is unavailable.", headers=PRIVATE)
                iterator = verified_narration(DATASET_ROOT, topic)
                size = topic.narration.source_bytes
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
