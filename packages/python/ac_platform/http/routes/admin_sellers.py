"""Additive registration: Admin → Sellers → What happened (http/admin_sellers.py)."""

from fastapi import FastAPI

from ac_platform.http.admin_sellers import install_admin_sellers_http
from ac_platform.http.routes import RouteContext

ORDER = 1615


def install(app: FastAPI, ctx: RouteContext) -> None:
    install_admin_sellers_http(app, ctx)
