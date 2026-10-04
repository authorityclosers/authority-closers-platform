from __future__ import annotations

from fastapi import FastAPI

from ac_platform.http.certificates import install_certificate_http
from ac_platform.http.routes import RouteContext

ORDER = 1800


def install(app: FastAPI, ctx: RouteContext) -> None:
    install_certificate_http(app, require_actor=ctx.require_actor)
