"""Additive registration: Ask Dipak's saved lessons and Next-call missions (ask_dipak/http.py)
its lessons and coaching loop (ask_dipak/coaching_http.py), and the same for API keys and
connected apps (ask_dipak/integration.py, /v1/api/ask-dipak)."""

from fastapi import FastAPI

from ac_platform.ask_dipak.coaching_http import install_ask_dipak_coaching_http
from ac_platform.ask_dipak.http import install_ask_dipak_http
from ac_platform.ask_dipak.integration import install_ask_dipak_api
from ac_platform.http.routes import RouteContext

ORDER = 1620


def install(app: FastAPI, ctx: RouteContext) -> None:
    install_ask_dipak_http(app, ctx)
    install_ask_dipak_coaching_http(app, ctx)
    install_ask_dipak_api(app, ctx)
