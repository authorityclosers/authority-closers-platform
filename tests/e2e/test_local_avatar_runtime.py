"""Opt-in real local photo upload/processing/private delivery, with sanitized failures."""

import hashlib
import io
import os
import random
from urllib.parse import urlsplit
from uuid import uuid4

import httpx
import pytest
from PIL import Image

ORIGIN = "http://learner.localhost:3100"


def check(value: bool, message: str) -> None:
    if not value:
        raise AssertionError(message)


def local_client():
    target = os.environ.get("AC_LOCAL_RUNTIME_ACCEPTANCE_TARGET", "api")
    check(target in {"api", "learner"}, "Only local acceptance targets are allowed")
    return httpx.Client(
        base_url="http://127.0.0.1:8000" if target == "api" else "http://127.0.0.1:3100",
        headers={
            "origin": ORIGIN,
            **({"host": "learner.localhost:3100"} if target == "learner" else {}),
        },
        timeout=30,
        trust_env=False,
        limits=httpx.Limits(max_keepalive_connections=0),
    )


def target_path(value: str, prefix: str) -> str:
    parsed = urlsplit(value)
    check(
        f"{parsed.scheme}://{parsed.netloc}" == ORIGIN
        and parsed.path.startswith(prefix)
        and not parsed.fragment
        and not parsed.username,
        "Avatar URL escaped the exact local boundary",
    )
    return parsed.path + "?" + parsed.query


def read_existing_photo() -> tuple[str, str]:
    """Read an existing photo; safe output is only its version and byte digest."""
    password = os.environ.get("AC_LOCAL_RUNTIME_TEST_PASSWORD")
    check(
        bool(password) and os.environ.get("AC_LOCAL_RUNTIME_ACCEPTANCE") == "1",
        "Explicit disposable localhost acceptance is required",
    )
    with local_client() as client:
        login = client.post(
            "/v1/auth/password/login", json={"email": "learner@ac.localhost", "password": password}
        )
        check(login.status_code == 200, "Local retained-photo login failed")
        try:
            response = client.get("/v1/profile/avatar")
            check(response.status_code == 200, "Local retained-photo query failed")
            avatar = response.json()["avatar"]
            check(
                avatar is not None and avatar["state"] == "ready" and avatar["size_px"] == 512,
                "Existing ready photo was not retained",
            )
            delivered = client.get(target_path(avatar["delivery_url"], "/v1/media/read/"))
            check(
                delivered.status_code == 200
                and delivered.headers.get("content-type") == "image/webp",
                "Existing private photo bytes were not retained",
            )
            with Image.open(io.BytesIO(delivered.content)) as decoded:
                decoded.load()
                check(decoded.size == (512, 512), "Retained photo did not decode at 512 pixels")
            return avatar["version_id"], hashlib.sha256(delivered.content).hexdigest()
        finally:
            logout = client.post("/v1/auth/logout")
            check(logout.status_code in {200, 204}, "Local retained-photo logout failed")


def test_existing_local_photo_survives_managed_api_restart():
    expected_version = os.environ.get("AC_LOCAL_RUNTIME_EXPECTED_AVATAR_VERSION")
    expected_digest = os.environ.get("AC_LOCAL_RUNTIME_EXPECTED_AVATAR_DIGEST")
    if not expected_version or not expected_digest:
        pytest.skip("Capture the existing photo before the explicit managed API restart")
    version, digest = read_existing_photo()
    check(version == expected_version, "API restart changed the canonical avatar version")
    check(digest == expected_digest, "API restart changed the saved avatar bytes")


def test_real_local_avatar_upload_processing_delivery_and_session_denial():
    password = os.environ.get("AC_LOCAL_RUNTIME_TEST_PASSWORD")
    if not password or os.environ.get("AC_LOCAL_RUNTIME_ACCEPTANCE") != "1":
        pytest.skip("Explicit disposable localhost acceptance is not enabled")
    # Deterministic synthetic pixels, large enough to exercise >1MiB raw PUT.
    with Image.frombytes(
        "RGB",
        (1024, 512),
        random.Random(712).randbytes(1024 * 512 * 3),  # noqa: S311 - deterministic synthetic pixels
    ) as pixels:
        encoded = io.BytesIO()
        pixels.save(encoded, format="PNG")
        body = encoded.getvalue()
    check(
        1024 * 1024 < len(body) < 5 * 1024 * 1024,
        "Synthetic photo must exercise the bounded large-body path",
    )
    checksum = hashlib.sha256(body).hexdigest()
    command = str(uuid4())
    with local_client() as client:
        login = client.post(
            "/v1/auth/password/login", json={"email": "learner@ac.localhost", "password": password}
        )
        check(login.status_code == 200, f"Local photo login returned {login.status_code}")
        try:
            intent = client.post(
                "/v1/profile/avatar",
                headers={"idempotency-key": command},
                json={
                    "purpose": "avatar",
                    "filename": "synthetic-local-profile.png",
                    "content_type": "image/png",
                    "content_length": len(body),
                    "checksum_sha256": checksum,
                    "crop": {"x": 0.5, "y": 0, "width": 0.5, "height": 1, "rotation_degrees": 0},
                },
            )
            check(intent.status_code == 201, f"Local photo intent returned {intent.status_code}")
            descriptor = intent.json()
            path = target_path(descriptor["upload_url"], "/v1/media/local-avatar-upload/")
            with local_client() as anonymous:
                rejected = anonymous.put(path, content=body, headers=descriptor["upload_headers"])
                check(rejected.status_code in {401, 403}, "Anonymous photo upload was not refused")
            uploaded = client.put(path, content=body, headers=descriptor["upload_headers"])
            check(uploaded.status_code == 204, f"Local photo PUT returned {uploaded.status_code}")
            complete = client.post(
                f"/v1/profile/avatar/{descriptor['upload_id']}/complete",
                headers={"idempotency-key": command + "-complete"},
                json={"actual_bytes": len(body), "checksum_sha256": checksum},
            )
            check(
                complete.status_code == 200,
                f"Local photo completion returned {complete.status_code}",
            )
            profile = client.get("/v1/profile/avatar")
            check(profile.status_code == 200, "Local photo query failed")
            avatar = profile.json()["avatar"]
            check(
                avatar is not None
                and avatar["version_id"] == descriptor["media_version_id"]
                and avatar["state"] == "ready"
                and avatar["size_px"] == 512,
                "Local photo was not persisted ready",
            )
            read = target_path(avatar["delivery_url"], "/v1/media/read/")
            delivered = client.get(read)
            check(
                delivered.status_code == 200
                and delivered.headers.get("content-type") == "image/webp",
                f"Local photo delivery returned {delivered.status_code}",
            )
            with Image.open(io.BytesIO(delivered.content)) as decoded:
                decoded.load()
                check(
                    decoded.size == (512, 512) and not decoded.getexif(),
                    "Local photo decoded dimensions or metadata failed",
                )
            with local_client() as anonymous:
                denied = anonymous.get(read)
                check(denied.status_code in {401, 403}, "Anonymous avatar read was not refused")
            head = client.head(read)
            check(
                head.status_code == 200 and not head.content,
                f"Local photo HEAD returned {head.status_code}, body bytes {len(head.content)}",
            )
        finally:
            logout = client.post("/v1/auth/logout")
            check(logout.status_code in {200, 204}, "Local photo logout failed")
