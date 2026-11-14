"""Additive registration: Sales X-Ray Play testers, /testers and Admin -> Testers
(testers/http.py)."""

from fastapi import FastAPI

from ac_platform.http.routes import RouteContext
from ac_platform.testers.http import install_testers_http

ORDER = 1616


def install(app: FastAPI, ctx: RouteContext) -> None:
    install_testers_http(app, ctx)
