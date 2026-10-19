"""Additive registration; the lead desk WhatsApp package owns implementation."""

from fastapi import FastAPI

from ac_platform.http.routes import RouteContext
from ac_platform.lead_desk.whatsapp.http import install_whatsapp_http

ORDER = 1266


def install(app: FastAPI, ctx: RouteContext) -> None:
    install_whatsapp_http(app, ctx)
