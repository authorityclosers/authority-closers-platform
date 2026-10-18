"""Additive registration; the call data package owns implementation and contracts."""

from fastapi import FastAPI

from ac_platform.call_data.admin_http import install_call_data_admin_http
from ac_platform.call_data.http import install_call_data_http
from ac_platform.http.routes import RouteContext

ORDER = 1262


def install(app: FastAPI, ctx: RouteContext) -> None:
    install_call_data_http(app, ctx)
    install_call_data_admin_http(app, ctx)
