"""Additive registration; the call_ai package owns implementation."""

from fastapi import FastAPI

from ac_platform.call_ai.http import install_call_ai_http
from ac_platform.http.routes import RouteContext

ORDER = 1263


def install(app: FastAPI, ctx: RouteContext) -> None:
    install_call_ai_http(app, ctx)
