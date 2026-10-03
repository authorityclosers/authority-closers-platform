from __future__ import annotations

from fastapi import FastAPI

from ac_platform.http.platform_sensitive_segments import install_platform_sensitive_segments_http
from ac_platform.http.routes import RouteContext

ORDER = 1400


def install(app: FastAPI, ctx: RouteContext) -> None:
    install_platform_sensitive_segments_http(
        app, settings=ctx.settings, require_actor=ctx.require_actor
    )
