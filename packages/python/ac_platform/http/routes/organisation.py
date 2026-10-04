from __future__ import annotations

from fastapi import FastAPI

from ac_platform.http.organisation import install_organisation_http
from ac_platform.http.routes import RouteContext

ORDER = 100


def install(app: FastAPI, ctx: RouteContext) -> None:
    install_organisation_http(app, settings=ctx.settings, require_actor=ctx.require_actor)
