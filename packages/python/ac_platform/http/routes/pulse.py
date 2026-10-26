"""Additive registration: Pulse (sign-in org link, directory, webhooks) and recordings
apps send for a person; their packages own implementation and contracts."""

from fastapi import FastAPI

from ac_platform.http.routes import RouteContext
from ac_platform.integrations.app_uploads import install_app_uploads_http
from ac_platform.pulse.http import install_pulse_http

ORDER = 1265


def install(app: FastAPI, ctx: RouteContext) -> None:
    install_pulse_http(app, ctx)
    install_app_uploads_http(app, ctx)
