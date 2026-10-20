"""The Sales X-Ray API's lead-journey route, for apps an organisation connected.

- ``PUT /v1/api/lead-journey/catalogue``: an app (Pulse first) sends its workflows'
  steps. Sales X-Ray keeps them as stages to choose from on Leads → Lead stages;
  nothing changes on the stage list until a manager adds one. Needs ``leads:write``
  and a connection that acts for the whole team (an organisation key, or a platform
  app connected by an owner or admin).

Body::

    {"source": "pulse", "revision": "<etag>",
     "workflows": [{"id": "wf_1", "name": "Sales",
                    "steps": [{"id": "st_3", "name": "Site visit",
                               "block": "site_visit", "position": 3}]}]}

Answers ``{"kept": <steps kept>, "offered": <new stages offered>}``. Same errors and
limits as the rest of the API.
"""

from __future__ import annotations

import time
from datetime import UTC, datetime
from typing import Any

from fastapi import APIRouter, FastAPI, Request
from fastapi.responses import JSONResponse

from ac_platform.http.routes import RouteContext
from ac_platform.integrations.api_http import PRIVATE, ApiError, make_opener
from ac_platform.lead_desk.journey import catalogue
from ac_platform.lead_desk.journey import model as journeys
from ac_platform.lead_desk.models import LeadDeskSettings


def install_journey_partner_http(application: FastAPI, ctx: RouteContext) -> None:
    router = APIRouter(prefix="/v1/api", tags=["sales-xray-api"])
    open_reader = make_opener(ctx)

    @router.put("/lead-journey/catalogue")
    async def put_catalogue(request: Request) -> JSONResponse:
        try:
            body: Any = await request.json()
        except ValueError:
            raise ApiError(400, "body_invalid", "Send the catalogue as JSON.") from None
        if not isinstance(body, dict):
            raise ApiError(400, "body_invalid", "Send the catalogue as a JSON object.")
        async with open_reader(request) as reader:
            reader.require("leads:write")
            if reader.caller.personal_workspace:
                raise ApiError(
                    403, "organisation_only", "Lead stages are kept in organisations, not Personal."
                )
            if not reader.caller.sees_team:
                raise ApiError(
                    403,
                    "owner_only",
                    "Only an owner's or admin's connection can send workflow steps.",
                )
            try:
                kept = catalogue.clean(str(body.get("source") or ""), body, now=int(time.time()))
            except catalogue.CatalogueError as error:
                raise ApiError(422, "catalogue_invalid", str(error)) from None
            tenant_id = reader.key.tenant_id
            session = reader.session
            row = await session.get(LeadDeskSettings, tenant_id, with_for_update=True)
            if row is None:
                row = LeadDeskSettings(
                    tenant_id=tenant_id,
                    revision=1,
                    config={},
                    updated_by_person_id=None,
                    updated_at=datetime.now(UTC),
                )
                session.add(row)
            config = dict(row.config or {})
            config[catalogue.KEY] = kept
            row.config = config
            await session.flush()
            journey = await journeys.read(session, tenant_id)
            offered = catalogue.suggestions(config, journey)
            steps = sum(len(flow["steps"]) for flow in kept["workflows"])
            return JSONResponse({"kept": steps, "offered": len(offered)}, headers=PRIVATE)

    application.include_router(router)
