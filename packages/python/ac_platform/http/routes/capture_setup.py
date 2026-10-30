"""Additive registration; the call_ai package owns implementation."""

from fastapi import FastAPI

from ac_platform.call_ai.capture_setup_http import install_capture_setup_http
from ac_platform.http.routes import RouteContext

ORDER = 1264


def install(app: FastAPI, ctx: RouteContext) -> None:
    install_capture_setup_http(app, ctx)
