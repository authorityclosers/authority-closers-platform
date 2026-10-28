"""/v1/app-web: the phone apps' signed web bundles, served read-only from AC_APP_WEB_ROOT."""

from __future__ import annotations

import hashlib
from pathlib import Path

from fastapi import FastAPI
from fastapi.testclient import TestClient

from ac_platform.application.settings import Settings
from ac_platform.http.app_web import install_app_web_http
from ac_platform.http.problem import register_problem_handlers

ZIP = b"PK\x03\x04 a web bundle"
DIGEST = hashlib.sha256(ZIP).hexdigest()
MANIFEST = b'{"format":"sx-web-bundle/1","key":"00","payload":"{}","signature":"00"}\n'


def settings(root: Path | None) -> Settings:
    return Settings(
        environment="test",
        database_url="postgresql+psycopg://unused:unused@localhost/unused",
        database_migrator_url="postgresql+psycopg://unused:unused@localhost/unused",
        session_token_pepper="test-session-token-pepper-that-is-long-enough",  # noqa: S106
        oauth_transaction_secret="test-oauth-secret-that-is-long-enough",  # noqa: S106
        public_app_url="https://app.authorityclosers.test",
        admin_app_url="https://admin.authorityclosers.test",
        api_url="https://api.authorityclosers.test",
        app_web_root=None if root is None else str(root),
    )


def client(root: Path | None) -> TestClient:
    app = FastAPI()
    register_problem_handlers(app)
    install_app_web_http(app, settings=settings(root))
    return TestClient(app)


def published(tmp_path: Path) -> Path:
    root = tmp_path / "app-web"
    (root / "bundles").mkdir(parents=True)
    (root / "manifest.json").write_bytes(MANIFEST)
    (root / "bundles" / f"{DIGEST}.zip").write_bytes(ZIP)
    return root


def test_the_manifest_is_served_as_published_and_always_asked_afresh(tmp_path: Path) -> None:
    response = client(published(tmp_path)).get("/v1/app-web/manifest.json")
    assert response.status_code == 200
    assert response.content == MANIFEST
    assert response.headers["content-type"] == "application/json"
    assert response.headers["cache-control"] == "no-cache"


def test_a_bundle_is_served_by_its_sha256_name_and_never_changes(tmp_path: Path) -> None:
    response = client(published(tmp_path)).get(f"/v1/app-web/bundles/{DIGEST}.zip")
    assert response.status_code == 200
    assert response.content == ZIP
    assert response.headers["content-type"] == "application/zip"
    assert response.headers["cache-control"] == "public, max-age=31536000, immutable"


def test_only_sha256_named_zips_under_bundles_are_served(tmp_path: Path) -> None:
    root = published(tmp_path)
    (tmp_path / "secret.txt").write_text("not for the web")
    (root / "bundles" / "latest.zip").write_bytes(ZIP)
    test_client = client(root)
    for path in (
        "/v1/app-web/bundles/latest.zip",
        f"/v1/app-web/bundles/{DIGEST.upper()}.zip",
        f"/v1/app-web/bundles/{DIGEST}.ZIP",
        "/v1/app-web/bundles/..%2F..%2Fsecret.txt",
        "/v1/app-web/../secret.txt",
        "/v1/app-web/secret.txt",
    ):
        response = test_client.get(path)
        assert response.status_code in {404, 422}, path
        assert b"not for the web" not in response.content


def test_nothing_is_served_until_something_is_published(tmp_path: Path) -> None:
    for root in (None, tmp_path / "app-web"):
        test_client = client(root)
        for path in ("/v1/app-web/manifest.json", f"/v1/app-web/bundles/{DIGEST}.zip"):
            response = test_client.get(path)
            assert response.status_code == 404
            assert response.json()["code"] == "app_web_unavailable"


def test_a_symbolic_link_is_never_followed(tmp_path: Path) -> None:
    root = published(tmp_path)
    outside = tmp_path / "outside.json"
    outside.write_text('{"not": "published"}')
    (root / "manifest.json").unlink()
    (root / "manifest.json").symlink_to(outside)
    assert client(root).get("/v1/app-web/manifest.json").status_code == 404


def test_writes_are_not_routes(tmp_path: Path) -> None:
    test_client = client(published(tmp_path))
    assert test_client.put("/v1/app-web/manifest.json", content=b"{}").status_code == 405
    assert test_client.delete(f"/v1/app-web/bundles/{DIGEST}.zip").status_code == 405
