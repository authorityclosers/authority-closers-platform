"""Admin → Product telemetry (owner, 24 Oct 2026: "Build full performance and usage telemetry
with the Admin dashboard").

GET /v1/admin/telemetry/overview?window=24h|7d|30d[&release=&device=&app=&tier=]
    This environment's speed per action (slow-device share), Web Vitals, app start,
    screens and flows, funnels, feature adoption, errors, slow APIs, rage and dead taps,
    per release and device class (telemetry/admin_view.py).
GET /v1/admin/telemetry/daily[?day=YYYY-MM-DD]
    One India day's export for the cost optimiser: each analysed call's cost joined to how
    its report was used, and per-workspace tallies (telemetry/daily_export.py).

The improvement loop (owner, 24 Oct 2026: "use in our recursive improvement pipeline each
new update"; telemetry/improvement.py):

GET /v1/admin/telemetry/devices?window=[&release=&app=]
    Every phone model and device class, its make-up, speed on key actions and issues, and
    the slowest 10% of devices.
GET /v1/admin/telemetry/compare[?head=&base=&app=]
    A release against the one before it (last 30 days).
GET /v1/admin/telemetry/gate?release=[&baseline=]
    The release train's input: pass, block (a key action regressed) or not_enough_data.
GET /v1/admin/telemetry/fix-next?window=
    What to fix next, ranked by people affected times severity, and what improved since the
    window before.

All are content-free (counts, timings, pseudonyms), for AC control accounts in the
operations workspace, and readable with a staff key that has admin:read.
"""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from typing import Any, Literal

from fastapi import APIRouter, Depends, FastAPI, HTTPException, Request, Response

from ac_platform.conversation_intelligence.application import (
    ConversationApplication,
    ConversationError,
)
from ac_platform.conversation_intelligence.cost_metrics import india_day, read_store
from ac_platform.conversation_intelligence.provider_admin import ConversationProviderAdmin
from ac_platform.http.auth import AuthenticatedTransaction, require_admin_surface
from ac_platform.http.routes import RouteContext
from ac_platform.telemetry import admin_view, daily_export, improvement
from ac_platform.usage_people.pseudonyms import ensure_key

PRIVATE = {"Cache-Control": "private, no-store"}


def install_admin_telemetry_http(application: FastAPI, ctx: RouteContext) -> None:
    settings = ctx.settings
    dependency = Depends(ctx.require_actor, scope="function")
    router = APIRouter(prefix="/v1/admin/telemetry", tags=["admin-telemetry"])

    async def admit(request: Request, response: Response, auth: AuthenticatedTransaction) -> None:
        require_admin_surface(request, settings)
        response.headers.update(PRIVATE)
        actor = auth.resolved.actor
        if (
            settings.operations_tenant_id is None
            or actor.tenant_id != settings.operations_tenant_id
        ):
            raise HTTPException(403, "Use the AC operations workspace.")
        try:
            await ConversationProviderAdmin(ConversationApplication(auth.database)).admit(actor)
        except ConversationError as error:
            raise HTTPException(error.status, str(error)) from None

    @router.get("/overview")
    async def overview(
        request: Request,
        response: Response,
        window: Literal["24h", "7d", "30d"] = "7d",
        release: str | None = None,
        device: Literal["phone", "tablet", "desktop"] | None = None,
        app: Literal["web", "android"] | None = None,
        tier: Literal["low", "mid", "high", "unknown"] | None = None,
        auth: AuthenticatedTransaction = dependency,
    ) -> dict[str, Any]:
        await admit(request, response, auth)
        if release is not None and not (0 < len(release) <= 64):
            raise HTTPException(422, "Choose a release from the list.")
        now = datetime.now(UTC)
        since = now - admin_view.WINDOWS[window]

        def read(connection: Any) -> tuple[admin_view.Read, dict[str, int]]:
            rows = admin_view.read_rows(connection, since=since, until=now, now=now)
            return rows, admin_view.read_consent(connection)

        rows, consent = await auth.database.run_sync(read)
        return admin_view.overview(
            rows,
            now=now,
            window=window,
            filters=admin_view.Filters(release=release, device=device, app=app, tier=tier),
            consent=consent,
            environment=settings.environment,
        )

    async def read_window(
        auth: AuthenticatedTransaction, since: datetime, now: datetime
    ) -> admin_view.Read:
        return await auth.database.run_sync(
            lambda connection: admin_view.read_rows(connection, since=since, until=now, now=now)
        )

    def release_name(value: str | None, field: str) -> str | None:
        if value is not None and not (0 < len(value) <= 64):
            raise HTTPException(422, f"Choose a {field} from the list.")
        return value

    @router.get("/devices")
    async def devices(
        request: Request,
        response: Response,
        window: Literal["24h", "7d", "30d"] = "7d",
        release: str | None = None,
        app: Literal["web", "android"] | None = None,
        auth: AuthenticatedTransaction = dependency,
    ) -> dict[str, Any]:
        await admit(request, response, auth)
        now = datetime.now(UTC)
        rows = await read_window(auth, now - admin_view.WINDOWS[window], now)
        return {
            **improvement.devices(
                rows,
                now=now,
                window=window,
                filters=admin_view.Filters(release=release_name(release, "release"), app=app),
            ),
            "environment": settings.environment,
            "truncated": rows.truncated,
        }

    @router.get("/compare")
    async def compare(
        request: Request,
        response: Response,
        head: str | None = None,
        base: str | None = None,
        app: Literal["web", "android"] | None = None,
        auth: AuthenticatedTransaction = dependency,
    ) -> dict[str, Any]:
        await admit(request, response, auth)
        now = datetime.now(UTC)
        rows = await read_window(auth, now - admin_view.WINDOWS["30d"], now)
        return {
            **improvement.compare(
                rows,
                now=now,
                head=release_name(head, "release"),
                base=release_name(base, "release"),
                filters=admin_view.Filters(app=app),
            ),
            "environment": settings.environment,
        }

    @router.get("/gate")
    async def gate(
        request: Request,
        response: Response,
        release: str,
        baseline: str | None = None,
        auth: AuthenticatedTransaction = dependency,
    ) -> dict[str, Any]:
        await admit(request, response, auth)
        now = datetime.now(UTC)
        rows = await read_window(auth, now - admin_view.WINDOWS["30d"], now)
        return improvement.gate(
            rows,
            now=now,
            environment=settings.environment,
            release=release_name(release, "release") or "",
            baseline=release_name(baseline, "baseline"),
        )

    @router.get("/fix-next")
    async def fix_next(
        request: Request,
        response: Response,
        window: Literal["24h", "7d", "30d"] = "7d",
        auth: AuthenticatedTransaction = dependency,
    ) -> dict[str, Any]:
        await admit(request, response, auth)
        now = datetime.now(UTC)
        span = admin_view.WINDOWS[window]
        # This window and the one before it (what improved since).
        rows = await read_window(auth, now - 2 * span, now)
        since = now - span
        return {
            **improvement.fix_next(
                [row for row in rows.rows if row.at >= since],
                [row for row in rows.rows if row.at < since],
                now=now,
                window=window,
                environment=settings.environment,
            ),
            "truncated": rows.truncated,
        }

    @router.get("/daily")
    async def daily(
        request: Request,
        response: Response,
        day: date | None = None,
        auth: AuthenticatedTransaction = dependency,
    ) -> dict[str, Any]:
        await admit(request, response, auth)
        now = datetime.now(UTC)
        today = india_day(now)
        wanted = day or today - timedelta(days=1)
        if wanted > today or wanted < today - timedelta(days=60):
            raise HTTPException(422, "Choose a day in the last 60 days.")
        start, end = daily_export.day_window(wanted)
        until = min(now, end + daily_export.FOLLOW)

        def read(connection: Any) -> tuple[admin_view.Read, tuple[bytes, bytes]]:
            rows = admin_view.read_rows(connection, since=start, until=until, now=now)
            return rows, ensure_key(connection, now)

        rows, pads = await auth.database.run_sync(read)
        exports, _problems = read_store(settings.metrics_store_root)
        export = next((item for item in exports if item.environment == settings.environment), None)
        return {
            **daily_export.daily_export(
                day=wanted,
                rows=rows.rows,
                export=export,
                pads=pads,
                environment=settings.environment,
                now=now,
            ),
            "truncated": rows.truncated,
        }

    application.include_router(router)


__all__ = ["install_admin_telemetry_http"]
