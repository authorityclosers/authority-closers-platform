"""Additive registration; the lead desk package owns the Connected apps implementation."""

from fastapi import FastAPI

from ac_platform.http.routes import RouteContext
from ac_platform.lead_desk.connected_apps_http import install_connected_apps_http

ORDER = 1270


def install(app: FastAPI, ctx: RouteContext) -> None:
    install_connected_apps_http(app, ctx)
