"""Additive registration; the lead desk AI replies package owns implementation."""

from fastapi import FastAPI

from ac_platform.http.routes import RouteContext
from ac_platform.lead_desk.ai_replies.admin_http import install_ai_replies_admin_http
from ac_platform.lead_desk.ai_replies.http import install_ai_replies_http

ORDER = 1269


def install(app: FastAPI, ctx: RouteContext) -> None:
    install_ai_replies_http(app, ctx)
    install_ai_replies_admin_http(app, ctx)
