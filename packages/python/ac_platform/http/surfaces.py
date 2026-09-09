"""Fail-closed route inventory for the independent Academy Studio web host."""

from __future__ import annotations

import re

from starlette.requests import Request
from starlette.types import ASGIApp, Receive, Scope, Send

from ac_platform.application.settings import Settings
from ac_platform.http.problem import problem_response

_UUID = r"[0-9a-fA-F]{8}-(?:[0-9a-fA-F]{4}-){3}[0-9a-fA-F]{12}"
_COACH_ROUTES = tuple(
    (method, re.compile(path))
    for method, path in (
        ("GET", r"/health/(?:live|ready)"),
        ("GET", r"/v1/me(?:/studio-access|/workspaces)?"),
        ("GET", r"/v1/context"),
        ("POST", r"/v1/context"),
        ("GET", r"/v1/auth/google/(?:start|callback)"),
        ("POST", r"/v1/auth/password/(?:login|recovery|reset)"),
        ("POST", r"/v1/auth/logout"),
        ("POST", rf"/v1/sessions/{_UUID}/revoke"),
        ("GET", r"/v1/admin/studio/(?:readiness|programs)"),
        ("GET", rf"/v1/admin/studio/programs/{_UUID}"),
        ("POST", rf"/v1/admin/studio/program-versions/{_UUID}/revision"),
        ("POST", rf"/v1/admin/studio/program-versions/{_UUID}/modules"),
        ("PATCH", rf"/v1/admin/studio/program-versions/{_UUID}/modules/{_UUID}"),
        ("POST", rf"/v1/admin/studio/program-versions/{_UUID}/modules/{_UUID}/activities"),
        ("PATCH", rf"/v1/admin/studio/program-versions/{_UUID}/activities/{_UUID}"),
        ("POST", rf"/v1/admin/program-versions/{_UUID}/publish"),
    )
)


class CoachSurfaceMiddleware:
    """Admission only: every admitted route still runs canonical authentication.

    Trust the actual Host consumed by routing, never browser Forwarded headers.
    New learner, platform or media routes are not implicitly exposed on Coach.
    """

    def __init__(self, app: ASGIApp, *, settings: Settings) -> None:
        self.app = app
        self.coach_host = settings.coach_app_url.host

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        request = Request(scope)
        if request.url.hostname != self.coach_host or any(
            method == request.method and pattern.fullmatch(scope.get("path", ""))
            for method, pattern in _COACH_ROUTES
        ):
            await self.app(scope, receive, send)
            return
        response = problem_response(
            request=request,
            status_code=403,
            code="coach_surface_route_denied",
            title="The route is unavailable on the Studio surface",
            detail="Use the application responsible for this operation.",
        )
        response.headers["cache-control"] = "no-store"
        await response(scope, receive, send)
