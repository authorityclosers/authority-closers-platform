from __future__ import annotations

from fastapi import FastAPI

from ac_platform.http.admin_learning import install_admin_learning_http
from ac_platform.http.routes import RouteContext

ORDER = 1900


def install(app: FastAPI, ctx: RouteContext) -> None:
    install_admin_learning_http(app, settings=ctx.settings, require_actor=ctx.require_actor)
