from __future__ import annotations

from fastapi import FastAPI

from ac_platform.http.routes import RouteContext
from ac_platform.http.telemetry import install_telemetry_http
from ac_platform.telemetry.sales_xray import (
    RETENTION_DAYS,
    RETENTION_POLICY_ID,
    SALES_XRAY_SURFACE,
    SalesXrayAdmission,
)

ORDER = 1600


def install(app: FastAPI, ctx: RouteContext) -> None:
    # Sales X-Ray product telemetry (owner, 22 Oct 2026). Writes stay refused
    # until the consent resolver for the approved basis is composed here.
    install_telemetry_http(
        app,
        settings=ctx.settings,
        require_actor=ctx.require_actor,
        retention_days=RETENTION_DAYS,
        retention_policy_id=RETENTION_POLICY_ID,
        admission=SalesXrayAdmission(),
        surface=SALES_XRAY_SURFACE,
    )
