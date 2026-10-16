"""Connector endpoints for the Sales Xray CRM (/v1/lead-desk).

Google Ads lead forms post to ``/capture/{source_id}/google-ads``. The source is
the CRM's own website-form source (kind ``webhook``) labelled "Google Ads lead
form"; Google's ``google_key`` is that source's key, so no session is needed and
the source key stays the only authority, exactly as for website forms.
"""

from __future__ import annotations

import asyncio
import json
from typing import Any
from uuid import UUID

from fastapi import APIRouter, FastAPI, HTTPException, Request, Response
from starlette.requests import ClientDisconnect

from ac_platform.http.routes import RouteContext
from ac_platform.lead_desk.connectors import google_ads
from ac_platform.lead_desk.intake import Intake
from ac_platform.lead_desk.store import DeskError

NO_STORE = {"Cache-Control": "no-store"}
_MAX_BODY = 64 * 1024


def install_connectors_http(application: FastAPI, ctx: RouteContext) -> None:
    router = APIRouter(prefix="/v1/lead-desk", tags=["lead-desk"])
    settings = ctx.settings

    def app_url() -> str:
        return str(settings.sales_xray_app_url or "").rstrip("/")

    def same_host(request: Request) -> None:
        if (
            settings.sales_xray_app_url is None
            or request.url.hostname != settings.sales_xray_app_url.host
        ):
            raise HTTPException(404, "Leads are unavailable here.", headers=NO_STORE)

    @router.post("/capture/{source_id}/google-ads")
    async def google_ads_lead(source_id: UUID, request: Request, response: Response) -> dict[str, Any]:
        """Google Ads sends one lead form submission. No cookie, no session."""
        response.headers.update(NO_STORE)
        same_host(request)
        payload = _json_object(await _body(request))
        try:
            token = google_ads.google_key(payload)
            record = google_ads.to_record(payload)
        except google_ads.GoogleAdsError as error:
            raise HTTPException(422, str(error), headers=NO_STORE) from None
        try:
            async with ctx.sessions() as database, database.begin():
                lead_id, outcome = await Intake.capture(
                    database, source_id, token, record, app_url=app_url()
                )
        except DeskError as error:
            raise HTTPException(error.status, str(error), headers=NO_STORE) from None
        return {"received": outcome != "skipped", "outcome": outcome, "lead_id": lead_id}

    application.include_router(router)


async def _body(request: Request) -> bytes:
    raw = bytearray()
    try:
        async with asyncio.timeout(15):
            async for chunk in request.stream():
                if len(raw) + len(chunk) > _MAX_BODY:
                    raise HTTPException(413, "That's too large to send.", headers=NO_STORE)
                raw.extend(chunk)
    except (TimeoutError, ClientDisconnect):
        raise HTTPException(408, "The upload stopped. Try again.", headers=NO_STORE) from None
    return bytes(raw)


def _json_object(raw: bytes) -> dict[str, Any]:
    try:
        value = json.loads(raw)
    except (UnicodeDecodeError, ValueError, RecursionError):
        raise HTTPException(422, "Send the lead as JSON.", headers=NO_STORE) from None
    if not isinstance(value, dict):
        raise HTTPException(422, "Send one lead as a JSON object.", headers=NO_STORE)
    return value
