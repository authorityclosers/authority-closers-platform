"""Additive registration; the admin_settings package owns the registry and its route."""

from fastapi import FastAPI

from ac_platform.admin_settings.http import install_admin_settings_http
from ac_platform.http.routes import RouteContext

ORDER = 2100


def install(app: FastAPI, ctx: RouteContext) -> None:
    install_admin_settings_http(app, settings=ctx.settings, require_actor=ctx.require_actor)
