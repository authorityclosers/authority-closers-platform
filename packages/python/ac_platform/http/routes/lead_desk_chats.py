"""Additive registration; the Chats package owns implementation."""

from fastapi import FastAPI

from ac_platform.http.routes import RouteContext
from ac_platform.lead_desk.chats.http import install_chats_http

ORDER = 1272


def install(app: FastAPI, ctx: RouteContext) -> None:
    install_chats_http(app, ctx)
