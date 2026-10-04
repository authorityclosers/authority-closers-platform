from __future__ import annotations

from fastapi import FastAPI

from ac_platform.http.routes import RouteContext
from ac_platform.http.telemetry import install_telemetry_http

ORDER = 1600


def install(app: FastAPI, ctx: RouteContext) -> None:
    install_telemetry_http(app, settings=ctx.settings, require_actor=ctx.require_actor)
