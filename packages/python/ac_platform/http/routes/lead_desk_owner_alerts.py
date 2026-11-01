"""Additive registration; the lead desk package owns owner alerts and the day's summary."""

from fastapi import FastAPI

from ac_platform.http.routes import RouteContext
from ac_platform.lead_desk.owner_alerts_http import install_owner_alerts_http

ORDER = 1275


def install(app: FastAPI, ctx: RouteContext) -> None:
    install_owner_alerts_http(app, ctx)
