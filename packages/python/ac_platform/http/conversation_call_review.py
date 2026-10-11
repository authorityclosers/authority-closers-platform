"""Admin call review console routes (AUT-1798), on the admin conversation router.

Read-only. Every route requires the Admin host and the same operations
control account as the Admin report; the audio route streams the private
source with the reviewer route's byte-range and bounded-memory rules.
"""

from __future__ import annotations

import re
from datetime import UTC, date, datetime
from typing import Annotated, Any
from uuid import UUID

from fastapi import APIRouter, Depends, Header, HTTPException, Path, Query, Request, Response
from starlette.responses import StreamingResponse

from ac_platform.application.settings import Settings
from ac_platform.conversation_intelligence.admin_analysis_health import AdminAnalysisHealth
from ac_platform.conversation_intelligence.admin_call_review import (
    LANGUAGES,
    STATUSES,
    AdminCallReview,
)
from ac_platform.conversation_intelligence.admin_usage import AdminUsage
from ac_platform.conversation_intelligence.application import (
    ConversationApplication,
    ConversationError,
)
from ac_platform.conversation_intelligence.async_io import join_thread
from ac_platform.conversation_intelligence.models import ConversationRecording
from ac_platform.conversation_intelligence.review_labels import (
    REVIEW_STATES,
    LabelIntent,
    ReviewLabels,
)
from ac_platform.conversation_intelligence.source_objects import resolve_source_key
from ac_platform.conversation_intelligence.storage import (
    PrivateLocalRecordingStorage,
    StorageError,
)
from ac_platform.conversation_intelligence.synthetic_dataset import SyntheticDataset
from ac_platform.http.auth import (
    AuthenticatedTransaction,
    RequireActor,
    require_admin_surface,
    require_safe_origin,
)
from ac_platform.http.conversation_insights import (
    insight_filters,
    insight_organisations,
    tenant_insights,
)
from ac_platform.http.conversation_playback import _PrivateAudioResponse, byte_range
from ac_platform.product_updates.admin_reading import latest_notes

_DIGEST = re.compile(r"^[0-9a-f]{64}$")
_QUEUE_PARAMS = {
    "review",
    "organisation",
    "rep",
    "language",
    "provider",
    "prompt",
    "status",
    "since",
    "until",
    "cursor",
    "limit",
}


def install_call_review_routes(
    router: APIRouter,
    *,
    settings: Settings,
    require_actor: RequireActor,
    recording_tenant_ids: tuple[UUID, ...],
    storage: PrivateLocalRecordingStorage | None,
) -> None:
    dependency = Depends(require_actor, scope="function")
    # Keep the fresh recording and permission locks until streaming ends.
    streaming_dependency = Depends(require_actor, scope="request")

    def service(auth: AuthenticatedTransaction) -> AdminCallReview:
        if settings.operations_tenant_id is None:
            raise HTTPException(503, "Call review is not configured.")
        return AdminCallReview(
            ConversationApplication(auth.database),
            settings.operations_tenant_id,
            recording_tenant_ids=recording_tenant_ids,
        )

    def scope(request: Request, response: Response, allowed: set[str] | None = None) -> None:
        require_admin_surface(request, settings)
        response.headers["Cache-Control"] = "private, no-store"
        names = set(request.query_params)
        if (allowed is None and names) or (allowed is not None and names - allowed):
            raise HTTPException(422, "This view takes no other filters.")
        if any(len(request.query_params.getlist(name)) != 1 for name in names):
            raise HTTPException(422, "Give each filter once.")

    @router.get("/calls")
    async def calls(
        request: Request,
        response: Response,
        organisation: UUID | None = None,
        rep: UUID | None = None,
        language: Annotated[str | None, Query(max_length=16)] = None,
        provider: Annotated[str | None, Query(max_length=256)] = None,
        prompt: Annotated[str | None, Query(min_length=1, max_length=128)] = None,
        status: Annotated[str | None, Query(max_length=16)] = None,
        review: Annotated[str | None, Query(max_length=16)] = None,
        since: date | None = None,
        until: date | None = None,
        cursor: Annotated[str | None, Query(min_length=1, max_length=64)] = None,
        limit: Annotated[int, Query(ge=1, le=100)] = 50,
        auth: AuthenticatedTransaction = dependency,
    ) -> dict[str, Any]:
        """The review queue: the newest calls, filtered, with filter choices and counts."""

        scope(request, response, _QUEUE_PARAMS)
        if status is not None and status not in STATUSES:
            raise HTTPException(422, "Use a known call status.")
        if language is not None and language not in LANGUAGES:
            raise HTTPException(422, "Use a known report language.")
        if review is not None and review not in REVIEW_STATES:
            raise HTTPException(422, "Use a known review state.")
        try:
            return await service(auth).queue(
                auth.resolved.actor,
                organisation=organisation,
                rep=rep,
                language=language,
                provider=provider,
                prompt=prompt,
                status=status,
                review=review,
                since=since,
                until=until,
                cursor=cursor,
                limit=limit,
            )
        except ConversationError as error:
            raise HTTPException(error.status, str(error)) from None

    @router.get("/health")
    async def health(
        request: Request,
        response: Response,
        days: Annotated[int, Query(ge=1, le=30)] = 7,
        auth: AuthenticatedTransaction = dependency,
    ) -> dict[str, Any]:
        """Analysis health for a window of days: jobs, failures, stuck work, time, cost."""

        scope(request, response, {"days"})
        if settings.operations_tenant_id is None:
            raise HTTPException(503, "Analysis health is not configured.")
        try:
            return await AdminAnalysisHealth(
                ConversationApplication(auth.database),
                settings.operations_tenant_id,
                recording_tenant_ids=recording_tenant_ids,
            ).summary(auth.resolved.actor, days=days)
        except ConversationError as error:
            raise HTTPException(error.status, str(error)) from None

    @router.get("/usage")
    async def usage(
        request: Request,
        response: Response,
        days: Annotated[int, Query(ge=1, le=90)] = 7,
        auth: AuthenticatedTransaction = dependency,
    ) -> dict[str, Any]:
        """Product event counts for the served organisations; never payloads."""

        scope(request, response, {"days"})
        if settings.operations_tenant_id is None:
            raise HTTPException(503, "Usage is not configured.")
        try:
            return await AdminUsage(
                ConversationApplication(auth.database),
                settings.operations_tenant_id,
                recording_tenant_ids=recording_tenant_ids,
            ).summary(auth.resolved.actor, days=days)
        except ConversationError as error:
            raise HTTPException(error.status, str(error)) from None

    @router.get("/product-updates")
    async def product_updates(
        request: Request,
        response: Response,
        auth: AuthenticatedTransaction = dependency,
    ) -> dict[str, Any]:
        """The newest version of each product note users see as "What's new"."""

        scope(request, response)
        try:
            await service(auth)._admit(auth.resolved.actor)
        except ConversationError as error:
            raise HTTPException(error.status, str(error)) from None
        return await latest_notes(auth.database)

    synthetic = SyntheticDataset(settings.sales_xray_synthetic_dataset_root)

    @router.get("/synthetic")
    async def synthetic_index(
        request: Request,
        response: Response,
        business: Annotated[str | None, Query(max_length=64)] = None,
        language: Annotated[str | None, Query(max_length=16)] = None,
        outcome: Annotated[str | None, Query(max_length=64)] = None,
        q: Annotated[str | None, Query(max_length=80)] = None,
        offset: Annotated[int, Query(ge=0, le=100_000)] = 0,
        limit: Annotated[int, Query(ge=1, le=100)] = 50,
        auth: AuthenticatedTransaction = dependency,
    ) -> dict[str, Any]:
        """The fictional synthetic-v1 calls, read-only and clearly labelled."""

        scope(request, response, {"business", "language", "outcome", "q", "offset", "limit"})
        try:
            await service(auth)._admit(auth.resolved.actor)
            return await join_thread(
                lambda: synthetic.index(
                    business=business,
                    language=language,
                    outcome=outcome,
                    query=q,
                    offset=offset,
                    limit=limit,
                )
            )
        except ConversationError as error:
            raise HTTPException(error.status, str(error)) from None

    @router.get("/synthetic/{call_id}")
    async def synthetic_call(
        call_id: Annotated[str, Path(min_length=5, max_length=128)],
        request: Request,
        response: Response,
        auth: AuthenticatedTransaction = dependency,
    ) -> dict[str, Any]:
        """One synthetic call: transcript and answer key, never its fixture truth."""

        scope(request, response)
        try:
            await service(auth)._admit(auth.resolved.actor)
            return await join_thread(lambda: synthetic.call(call_id))
        except ConversationError as error:
            raise HTTPException(error.status, str(error)) from None

    # ---------- Company view (AUT-1798): the owner's view of one organisation ----------

    insight_params = frozenset({"organisation"})

    async def insight_target(
        auth: AuthenticatedTransaction, organisation: UUID | None
    ) -> tuple[list[dict[str, Any]], dict[str, Any] | None]:
        await service(auth)._admit(auth.resolved.actor)
        organisations = await insight_organisations(auth.database, recording_tenant_ids)
        if organisation is None:
            return organisations, organisations[0] if organisations else None
        chosen = next((item for item in organisations if item["id"] == str(organisation)), None)
        if chosen is None:
            raise HTTPException(404, "That organisation isn't served by Sales Xray.")
        return organisations, chosen

    @router.get("/insights")
    async def company_view(
        request: Request,
        response: Response,
        organisation: UUID | None = None,
        span: Annotated[str | None, Query(alias="range", max_length=8)] = None,
        start: Annotated[date | None, Query(alias="from")] = None,
        end: Annotated[date | None, Query(alias="to")] = None,
        person: Annotated[str | None, Query(min_length=1, max_length=160)] = None,
        team: Annotated[str | None, Query(min_length=1, max_length=160)] = None,
        outcome: Annotated[str | None, Query(max_length=16)] = None,
        language: Annotated[str | None, Query(min_length=1, max_length=32)] = None,
        auth: AuthenticatedTransaction = dependency,
    ) -> dict[str, Any]:
        """One organisation's company view, as its owner sees it (read-only)."""

        require_admin_surface(request, settings)
        response.headers["Cache-Control"] = "private, no-store"
        now = datetime.now(UTC)
        filters = insight_filters(
            request,
            now=now,
            span=span,
            start=start,
            end=end,
            person=person,
            team=team,
            outcome=outcome,
            language=language,
            extra=insight_params,
        )
        try:
            organisations, chosen = await insight_target(auth, organisation)
            overview = (
                None
                if chosen is None
                else await tenant_insights(
                    auth.database, auth.resolved.actor, UUID(chosen["id"])
                ).overview(filters, now=now)
            )
        except ConversationError as error:
            raise HTTPException(error.status, str(error)) from None
        return {"organisations": organisations, "organisation": chosen, "overview": overview}

    @router.get("/insights/calls")
    async def company_view_calls(
        request: Request,
        response: Response,
        organisation: UUID,
        span: Annotated[str | None, Query(alias="range", max_length=8)] = None,
        start: Annotated[date | None, Query(alias="from")] = None,
        end: Annotated[date | None, Query(alias="to")] = None,
        person: Annotated[str | None, Query(min_length=1, max_length=160)] = None,
        team: Annotated[str | None, Query(min_length=1, max_length=160)] = None,
        outcome: Annotated[str | None, Query(max_length=16)] = None,
        language: Annotated[str | None, Query(min_length=1, max_length=32)] = None,
        offset: Annotated[int, Query(ge=0, le=1_000_000)] = 0,
        auth: AuthenticatedTransaction = dependency,
    ) -> dict[str, Any]:
        """The calls behind one organisation's company view, newest first."""

        require_admin_surface(request, settings)
        response.headers["Cache-Control"] = "private, no-store"
        filters = insight_filters(
            request,
            now=datetime.now(UTC),
            span=span,
            start=start,
            end=end,
            person=person,
            team=team,
            outcome=outcome,
            language=language,
            extra=insight_params,
        )
        try:
            await insight_target(auth, organisation)
            return await tenant_insights(auth.database, auth.resolved.actor, organisation).calls(
                filters, offset=offset
            )
        except ConversationError as error:
            raise HTTPException(error.status, str(error)) from None

    @router.post("/insights/refresh")
    async def company_view_refresh(
        request: Request,
        response: Response,
        organisation: UUID,
        auth: AuthenticatedTransaction = dependency,
    ) -> dict[str, Any]:
        """Bring one organisation's per-call projection up to date (one batch)."""

        scope(request, response, {"organisation"})
        require_safe_origin(request, settings)
        try:
            await insight_target(auth, organisation)
            return await tenant_insights(auth.database, auth.resolved.actor, organisation).refresh(
                now=datetime.now(UTC)
            )
        except ConversationError as error:
            raise HTTPException(error.status, str(error)) from None

    def labels(auth: AuthenticatedTransaction) -> ReviewLabels:
        if settings.operations_tenant_id is None:
            raise HTTPException(503, "Call review is not configured.")
        return ReviewLabels(
            ConversationApplication(auth.database),
            settings.operations_tenant_id,
            recording_tenant_ids=recording_tenant_ids,
        )

    @router.get("/calls/{recording_id}/labels")
    async def call_labels(
        recording_id: UUID,
        request: Request,
        response: Response,
        auth: AuthenticatedTransaction = dependency,
    ) -> dict[str, Any]:
        """The call's reviewer labels: what stands now, and the full history."""

        scope(request, response)
        try:
            return await labels(auth).read(auth.resolved.actor, recording_id)
        except ConversationError as error:
            raise HTTPException(error.status, str(error)) from None

    @router.post("/calls/{recording_id}/labels", status_code=201)
    async def add_label(
        recording_id: UUID,
        intent: LabelIntent,
        request: Request,
        response: Response,
        key: Annotated[str, Header(alias="Idempotency-Key", min_length=1, max_length=128)],
        auth: AuthenticatedTransaction = dependency,
    ) -> dict[str, Any]:
        """Add one verdict, note, gold label, data mark or review state (append-only)."""

        scope(request, response)
        require_safe_origin(request, settings)
        try:
            return await labels(auth).add(auth.resolved.actor, recording_id, intent, key=key)
        except ConversationError as error:
            raise HTTPException(error.status, str(error)) from None

    @router.get("/gold")
    async def gold(
        request: Request,
        response: Response,
        auth: AuthenticatedTransaction = dependency,
    ) -> dict[str, Any]:
        """Dipak's gold set and the AI's agreement with it (internal, not a score)."""

        scope(request, response)
        try:
            return await labels(auth).gold(auth.resolved.actor)
        except ConversationError as error:
            raise HTTPException(error.status, str(error)) from None

    @router.get("/calls/{recording_id}")
    async def call(
        recording_id: UUID,
        request: Request,
        response: Response,
        auth: AuthenticatedTransaction = dependency,
    ) -> dict[str, Any]:
        """One call and every analysis run of it, newest first."""

        scope(request, response)
        try:
            return await service(auth).call(auth.resolved.actor, recording_id)
        except ConversationError as error:
            raise HTTPException(error.status, str(error)) from None

    @router.get("/runs/{run_id}/review")
    async def review(
        run_id: UUID,
        request: Request,
        response: Response,
        auth: AuthenticatedTransaction = dependency,
    ) -> dict[str, Any]:
        """One run's report and transcript, withheld per the recording's marks."""

        scope(request, response)
        try:
            return await service(auth).bundle(auth.resolved.actor, run_id)
        except ConversationError as error:
            raise HTTPException(error.status, str(error)) from None

    @router.get("/runs/{run_id}/source")
    async def source(
        run_id: UUID,
        request: Request,
        response: Response,
        auth: AuthenticatedTransaction = streaming_dependency,
    ) -> StreamingResponse:
        """The call audio for review, one byte range at a time."""

        scope(request, response)
        if storage is None:
            raise HTTPException(503, "Private conversation storage is not configured.")
        try:
            recording = await service(auth).playback(auth.resolved.actor, run_id)
        except ConversationError as error:
            raise HTTPException(error.status, str(error)) from None
        try:
            source_bytes = recording["source_bytes"]
            source_sha256 = recording["source_sha256"]
            recording_id = UUID(str(recording["id"]))
            content_type = str(recording["content_type"])
            if (
                type(source_bytes) is not int
                or source_bytes <= 0
                or not isinstance(source_sha256, str)
                or _DIGEST.fullmatch(source_sha256) is None
                or not content_type
            ):
                raise StorageError("invalid private source descriptor")
            ranges = request.headers.getlist("range")
            if len(ranges) > 1:
                raise ValueError("duplicate range")
            start, end = byte_range(ranges[0] if ranges else None, source_bytes)
        except (KeyError, TypeError, ValueError, StorageError):
            raise HTTPException(
                416,
                "Use a single valid audio byte range.",
                headers={"Content-Range": f"bytes */{recording.get('source_bytes', 0)}"},
            ) from None
        iterator = None
        try:
            row = await auth.database.get(ConversationRecording, recording_id)
            if row is None:
                raise StorageError("storage_object_missing")
            key = await resolve_source_key(auth.database, row)
            iterator = storage.iter_bytes(key, expected_sha256=source_sha256)
            first = await join_thread(lambda: next(iterator, None))
            if first is None:
                raise StorageError("empty private source")
        except BaseException as error:
            close = getattr(iterator, "close", None)
            if close is not None:
                await join_thread(close)
            if isinstance(error, (StorageError, OSError)):
                raise HTTPException(409, "The retained recording is unavailable.") from None
            raise
        headers = {
            "Cache-Control": "private, no-store",
            "Accept-Ranges": "bytes",
            "Content-Length": str(end - start + 1),
            "X-Content-Type-Options": "nosniff",
            "Content-Disposition": 'inline; filename="sales-call"',
        }
        if ranges:
            headers["Content-Range"] = f"bytes {start}-{end}/{source_bytes}"
        return _PrivateAudioResponse(
            iterator,
            first,
            start,
            end,
            status_code=206 if ranges else 200,
            media_type=content_type,
            headers=headers,
        )
