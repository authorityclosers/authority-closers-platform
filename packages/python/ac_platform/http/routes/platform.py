from __future__ import annotations

from fastapi import FastAPI

from ac_platform.http.platform import install_platform_http
from ac_platform.http.routes import RouteContext

ORDER = 1300


def install(app: FastAPI, ctx: RouteContext) -> None:
    install_platform_http(app, settings=ctx.settings, require_actor=ctx.require_actor)
