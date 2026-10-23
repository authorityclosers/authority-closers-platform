"""Additive registration: Admin → Product telemetry (http/admin_telemetry.py)."""

from fastapi import FastAPI

from ac_platform.http.admin_telemetry import install_admin_telemetry_http
from ac_platform.http.routes import RouteContext

ORDER = 1610


def install(app: FastAPI, ctx: RouteContext) -> None:
    install_admin_telemetry_http(app, ctx)
