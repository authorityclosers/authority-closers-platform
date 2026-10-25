"""Additive registration; the Lead Desk package owns implementation and contracts."""

from fastapi import FastAPI

from ac_platform.http.routes import RouteContext
from ac_platform.lead_desk.duplicates_admin_http import install_duplicates_admin_http
from ac_platform.lead_desk.http import install_lead_desk_http

ORDER = 1260


def install(app: FastAPI, ctx: RouteContext) -> None:
    install_lead_desk_http(app, ctx)
    install_duplicates_admin_http(app, ctx)
