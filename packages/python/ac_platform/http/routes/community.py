from __future__ import annotations

from fastapi import FastAPI

from ac_platform.http.community import install_community_http
from ac_platform.http.routes import RouteContext

ORDER = 1100


def install(app: FastAPI, ctx: RouteContext) -> None:
    install_community_http(app, settings=ctx.settings, require_actor=ctx.require_actor)
