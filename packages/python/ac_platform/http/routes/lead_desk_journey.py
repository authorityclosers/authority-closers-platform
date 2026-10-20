"""Additive registration; the lead journey package owns implementation."""

from fastapi import FastAPI

from ac_platform.http.routes import RouteContext
from ac_platform.lead_desk.journey import engine
from ac_platform.lead_desk.journey.http import install_journey_http

ORDER = 1271


def install(app: FastAPI, ctx: RouteContext) -> None:
    install_journey_http(app, ctx)
    # The lead-stage engine sends every platform's events, Meta's included; it replaced
    # the Meta-only sender (connectors/meta_capi.py), which no longer starts.
    engine.attach(app, ctx.sessions, ctx.settings.environment)
