"""Additive registration: call reports for API keys and connected apps
(integrations/reports_api.py: /v1/api/reports and /v1/api/calls/{id}/report, .docx and
transcript). Its MCP tools are in the integrations MCP server."""

from fastapi import FastAPI

from ac_platform.http.routes import RouteContext
from ac_platform.integrations.reports_api import install_reports_api

ORDER = 1625


def install(app: FastAPI, ctx: RouteContext) -> None:
    install_reports_api(app, ctx)
