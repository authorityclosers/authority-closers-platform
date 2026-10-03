from __future__ import annotations

from fastapi import FastAPI

from ac_platform.http.practice import install_practice_http
from ac_platform.http.routes import RouteContext

ORDER = 400


def install(app: FastAPI, ctx: RouteContext) -> None:
    install_practice_http(app, settings=ctx.settings, require_actor=ctx.require_actor)
