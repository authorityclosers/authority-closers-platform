"""Additive registration; the integrations package owns implementation and contracts."""

from fastapi import FastAPI

from ac_platform.http.routes import RouteContext
from ac_platform.integrations.admin_http import install_integrations_admin_http
from ac_platform.integrations.api_http import install_integrations_api
from ac_platform.integrations.http import install_integrations_http

ORDER = 1264


def install(app: FastAPI, ctx: RouteContext) -> None:
    install_integrations_http(app, ctx)
    install_integrations_api(app, ctx)
    install_integrations_admin_http(app, ctx)
