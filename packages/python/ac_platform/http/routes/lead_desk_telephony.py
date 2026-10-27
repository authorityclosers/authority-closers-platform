"""Additive registration; the lead desk telephony package owns implementation."""

from fastapi import FastAPI

from ac_platform.http.routes import RouteContext
from ac_platform.lead_desk.telephony.http import install_telephony_http

ORDER = 1267


def install(app: FastAPI, ctx: RouteContext) -> None:
    install_telephony_http(app, ctx)
