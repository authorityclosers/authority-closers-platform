from __future__ import annotations

from fastapi import FastAPI

from ac_platform.http.app_web import install_app_web_http
from ac_platform.http.routes import RouteContext

ORDER = 1210


def install(app: FastAPI, ctx: RouteContext) -> None:
    install_app_web_http(app, settings=ctx.settings)
