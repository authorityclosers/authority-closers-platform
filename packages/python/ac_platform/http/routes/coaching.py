"""Additive registration; Coaching owns implementation and contracts."""

from fastapi import FastAPI

from ac_platform.coaching.http import install_coaching_http
from ac_platform.http.routes import RouteContext

ORDER = 1250


def install(app: FastAPI, ctx: RouteContext) -> None:
    install_coaching_http(app, ctx)
