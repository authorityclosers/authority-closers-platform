"""Additive registration; the one_pass package owns implementation."""

from fastapi import FastAPI

from ac_platform.http.routes import RouteContext
from ac_platform.one_pass.admin_http import install_one_pass_admin_http

ORDER = 1282


def install(app: FastAPI, ctx: RouteContext) -> None:
    install_one_pass_admin_http(app, ctx)
