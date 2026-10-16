"""Additive registration; the lead connectors package owns implementation."""

from fastapi import FastAPI

from ac_platform.http.routes import RouteContext
from ac_platform.lead_desk.connectors.http import install_connectors_http

ORDER = 1261


def install(app: FastAPI, ctx: RouteContext) -> None:
    install_connectors_http(app, ctx)
