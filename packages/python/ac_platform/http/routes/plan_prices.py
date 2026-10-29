"""Additive registration; the plans package owns implementation."""

from fastapi import FastAPI

from ac_platform.http.routes import RouteContext
from ac_platform.plans.admin_http import install_plan_prices_admin_http

ORDER = 1286


def install(app: FastAPI, ctx: RouteContext) -> None:
    install_plan_prices_admin_http(app, ctx)
