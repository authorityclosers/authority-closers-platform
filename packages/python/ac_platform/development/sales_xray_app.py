"""Read-only synthetic API for the standalone local frontend's network checks.

No user data, upload, secret, identity impersonation, or background execution.
Production composes conversation routes through the AC API, never this runner.
"""

import os
from pathlib import Path

from fastapi import FastAPI, Request
from starlette.middleware.base import RequestResponseEndpoint
from starlette.middleware.trustedhost import TrustedHostMiddleware
from starlette.responses import Response
from starlette.staticfiles import StaticFiles

from ac_platform.http.conversation import install_conversation_http

app = FastAPI(title="Sales Xray synthetic development API", docs_url=None, redoc_url=None)
app.add_middleware(TrustedHostMiddleware, allowed_hosts=["127.0.0.1", "localhost", "testserver"])
install_conversation_http(app)


@app.middleware("http")
async def preview_headers(request: Request, call_next: RequestResponseEndpoint) -> Response:
    response: Response = await call_next(request)
    response.headers["Cache-Control"] = "no-store"
    response.headers["Referrer-Policy"] = "no-referrer"
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["Permissions-Policy"] = "camera=(), microphone=(), geolocation=()"
    return response


if os.environ.get("AC_SALES_XRAY_STATIC_PREVIEW") == "1":
    # Fixed build artifact only. Never mount a user directory or the source recording.
    exported = Path(__file__).resolve().parents[4] / "apps" / "sales-xray-web" / "out"
    if not (exported / "index.html").is_file() or exported.is_symlink():
        raise RuntimeError("Build the Sales Xray static preview artifact first.")
    app.mount("/", StaticFiles(directory=exported, html=True), name="sales-xray-local-preview")
