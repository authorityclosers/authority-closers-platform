"""Additive registration; the lead desk social package owns implementation."""

from fastapi import FastAPI

from ac_platform.http.routes import RouteContext
from ac_platform.lead_desk.social.http import install_social_http

ORDER = 1268


def install(app: FastAPI, ctx: RouteContext) -> None:
    install_social_http(app, ctx)
