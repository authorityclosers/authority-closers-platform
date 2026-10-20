"""Additive registration; the provider hub package owns implementation and contracts."""

from fastapi import FastAPI

from ac_platform.http.routes import RouteContext
from ac_platform.provider_hub.http import install_provider_hub_http

ORDER = 1267


def install(app: FastAPI, ctx: RouteContext) -> None:
    install_provider_hub_http(app, ctx)
