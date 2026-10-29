from __future__ import annotations

from fastapi import FastAPI

from ac_platform.http.app_config import install_app_config_http
from ac_platform.http.routes import RouteContext

ORDER = 1211


def install(app: FastAPI, ctx: RouteContext) -> None:
    install_app_config_http(app, settings=ctx.settings)
