"""The phone apps' live web updates: this environment's signed web bundles, read-only.

ac-web-bundle-after-release publishes each production release's bundle (a zip of the web app's
static export, named by its SHA-256) and its Ed25519-signed manifest under AC_APP_WEB_ROOT. The
apps check the signature against keys they pin, so this route only serves bytes: it never signs,
chooses or changes anything. Unset root, or nothing published yet: 404.
docs/ops/LIVE-WEB-BUNDLES.md.
"""

from __future__ import annotations

from pathlib import Path as FilePath

from fastapi import APIRouter, FastAPI, Path
from fastapi.responses import FileResponse, Response

from ac_platform.application.settings import Settings
from ac_platform.kernel.errors import DomainError

BUNDLE_NAME_PATTERN = r"^[0-9a-f]{64}\.zip$"
MAX_MANIFEST_BYTES = 64 * 1024


class AppWebUnavailable(DomainError):
    status = 404
    code = "app_web_unavailable"
    title = "No web bundle is published here"


def install_app_web_http(application: FastAPI, *, settings: Settings) -> None:
    router = APIRouter(prefix="/v1/app-web", tags=["app-web"])

    def published(*parts: str) -> FilePath:
        root = settings.app_web_root
        if not root or not FilePath(root).is_absolute():
            raise AppWebUnavailable("Live web updates are not published on this environment.")
        path = FilePath(root, *parts)
        if not path.is_file() or path.is_symlink():
            raise AppWebUnavailable("That web bundle is not published.")
        return path

    @router.get("/manifest.json")
    def manifest() -> Response:
        path = published("manifest.json")
        data = path.read_bytes()
        if len(data) > MAX_MANIFEST_BYTES:
            raise AppWebUnavailable("That web bundle is not published.")
        # Always asked afresh: the apps read it on start and on coming back.
        return Response(data, media_type="application/json", headers={"Cache-Control": "no-cache"})

    @router.get("/bundles/{name}")
    def bundle(
        name: str = Path(min_length=68, max_length=68, pattern=BUNDLE_NAME_PATTERN),
    ) -> FileResponse:
        # Named by its own SHA-256, so a name always means the same bytes.
        return FileResponse(
            published("bundles", name),
            media_type="application/zip",
            headers={"Cache-Control": "public, max-age=31536000, immutable"},
        )

    application.include_router(router)


__all__ = ["AppWebUnavailable", "install_app_web_http"]
