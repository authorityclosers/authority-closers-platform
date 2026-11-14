"""Additive registration: Ask Dipak's saved lessons and Next-call missions (ask_dipak/http.py)."""

from fastapi import FastAPI

from ac_platform.ask_dipak.http import install_ask_dipak_http
from ac_platform.http.routes import RouteContext

ORDER = 1620


def install(app: FastAPI, ctx: RouteContext) -> None:
    install_ask_dipak_http(app, ctx)
