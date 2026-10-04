from __future__ import annotations

from fastapi import FastAPI

from ac_platform.http.app_updates import install_app_updates_http
from ac_platform.http.routes import RouteContext

ORDER = 1200


def install(app: FastAPI, ctx: RouteContext) -> None:
    install_app_updates_http(app, settings=ctx.settings, require_actor=ctx.require_actor)
