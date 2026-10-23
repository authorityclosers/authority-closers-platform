"""Additive registration; the bug_reports package owns implementation and contracts."""

from fastapi import FastAPI

from ac_platform.bug_reports.http import install_bug_reports_http
from ac_platform.http.routes import RouteContext

ORDER = 1284


def install(app: FastAPI, ctx: RouteContext) -> None:
    install_bug_reports_http(app, ctx)
