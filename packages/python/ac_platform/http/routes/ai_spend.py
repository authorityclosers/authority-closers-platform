"""Additive registration; the ai_spend package owns implementation."""

from fastapi import FastAPI

from ac_platform.ai_spend.admin_http import install_ai_spend_admin_http
from ac_platform.http.routes import RouteContext

ORDER = 1281


def install(app: FastAPI, ctx: RouteContext) -> None:
    install_ai_spend_admin_http(app, ctx)
