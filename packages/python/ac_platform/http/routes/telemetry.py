from __future__ import annotations

from fastapi import FastAPI

from ac_platform.http.routes import RouteContext
from ac_platform.http.telemetry import install_telemetry_http
from ac_platform.http.telemetry_preferences import install_telemetry_preferences_http
from ac_platform.telemetry.sales_xray import (
    RETENTION_DAYS,
    RETENTION_POLICY_ID,
    SALES_XRAY_SURFACE,
    SalesXrayAdmission,
)
from ac_platform.telemetry.sales_xray_consent import sales_xray_consent

ORDER = 1600


def install(app: FastAPI, ctx: RouteContext) -> None:
    # Sales X-Ray product telemetry (owner, 24 Oct 2026, option B): recorded unless a person
    # or their workspace turns it off (Settings, Privacy); never in a sandbox.
    install_telemetry_http(
        app,
        settings=ctx.settings,
        require_actor=ctx.require_actor,
        consent_resolver=sales_xray_consent,
        retention_days=RETENTION_DAYS,
        retention_policy_id=RETENTION_POLICY_ID,
        admission=SalesXrayAdmission(),
        surface=SALES_XRAY_SURFACE,
    )
    install_telemetry_preferences_http(app, settings=ctx.settings, require_actor=ctx.require_actor)
