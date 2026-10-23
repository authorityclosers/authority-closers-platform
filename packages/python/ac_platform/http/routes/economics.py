"""Additive registration; the economics package owns implementation."""

from fastapi import FastAPI

from ac_platform.economics.admin_http import install_economics_admin_http
from ac_platform.http.routes import RouteContext

ORDER = 1285


def install(app: FastAPI, ctx: RouteContext) -> None:
    install_economics_admin_http(app, ctx)
