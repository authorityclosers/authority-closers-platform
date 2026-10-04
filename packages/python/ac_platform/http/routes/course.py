from __future__ import annotations

from fastapi import FastAPI

from ac_platform.http.course import install_course_http
from ac_platform.http.routes import RouteContext

ORDER = 300


def install(app: FastAPI, ctx: RouteContext) -> None:
    install_course_http(
        app, settings=ctx.settings, sessions=ctx.sessions, require_actor=ctx.require_actor
    )
