"""Additive registration; the CRM's websites module owns implementation."""

from fastapi import FastAPI

from ac_platform.http.routes import RouteContext
from ac_platform.lead_desk.websites_http import install_websites_http

ORDER = 1273


def install(app: FastAPI, ctx: RouteContext) -> None:
    install_websites_http(app, ctx)
