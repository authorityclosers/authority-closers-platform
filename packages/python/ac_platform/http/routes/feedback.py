"""Additive registration; the feedback package owns implementation and contracts."""

from fastapi import FastAPI

from ac_platform.feedback.http import install_feedback_http
from ac_platform.http.routes import RouteContext

ORDER = 1285


def install(app: FastAPI, ctx: RouteContext) -> None:
    install_feedback_http(app, ctx)
