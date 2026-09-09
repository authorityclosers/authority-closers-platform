"""Opt-in actual localhost HTTP/database/film-byte acceptance, never a live target."""

import os
from urllib.parse import urlsplit

import httpx
import pytest

from ac_platform.seed.technical_media_fixture_v2 import technical_media_identity

ORIGIN = "http://learner.localhost:3100"
API = "http://127.0.0.1:8000"


def check(condition: bool, message: str) -> None:
    # Failed assertions must not print cookies, passwords or signed manifests.
    if not condition:
        raise AssertionError(message)


def media_path(source: str) -> str:
    parsed = urlsplit(source)
    check(
        f"{parsed.scheme}://{parsed.netloc}" == ORIGIN
        and parsed.path.startswith("/v1/media/playback/")
        and not parsed.fragment,
        "Film delivery locator must remain on the exact local origin",
    )
    return parsed.path + "?" + parsed.query


def local_client(timeout: int = 20) -> httpx.Client:
    target = os.environ.get("AC_LOCAL_RUNTIME_ACCEPTANCE_TARGET", "api")
    check(target in {"api", "learner"}, "Only exact localhost acceptance targets are allowed")
    headers = {"Origin": ORIGIN}
    if target == "learner":
        # Explicit host preserves the same-origin Next request without relying
        # on the OS DNS resolver implementing browser .localhost semantics.
        headers["Host"] = "learner.localhost:3100"
    return httpx.Client(
        base_url=API if target == "api" else "http://127.0.0.1:3100",
        headers=headers,
        timeout=timeout,
        trust_env=False,
    )


@pytest.fixture
def browser():
    password = os.environ.get("AC_LOCAL_RUNTIME_TEST_PASSWORD")
    if not password or os.environ.get("AC_LOCAL_RUNTIME_ACCEPTANCE") != "1":
        pytest.skip("explicit disposable localhost acceptance is not enabled")
    with local_client() as client:
        response = client.post(
            "/v1/auth/password/login",
            json={"email": "learner@ac.localhost", "password": password},
        )
        check(response.status_code == 200, f"Local password login returned {response.status_code}")
        yield client
        logout = client.post("/v1/auth/logout")
        check(logout.status_code in {200, 204}, "Local logout failed")


def test_real_local_film_metadata_hls_progressive_range_and_session_denial(browser):
    identity = browser.get("/v1/me")
    check(identity.status_code == 200, "Local identity request failed")
    check(identity.json()["membership_role"] == "learner", "Local learner role changed")
    catalog = browser.get("/v1/programs")
    check(catalog.status_code == 200, "Local catalog request failed")
    films = next(
        item for item in catalog.json()["items"] if item["slug"] == "staging-technical-validation"
    )
    enrollment = browser.post(
        "/v1/enrollments/free",
        headers={"Idempotency-Key": "disposable-local-film-http-acceptance-v1"},
        json={"program_version_id": films["program_version_id"]},
    )
    # Technical fixtures are explicitly granted by the isolated seed, never
    # admitted through the foundation course's public self-attestation policy.
    check(enrollment.status_code == 403, "Technical self-enrollment must remain denied")
    _, _, _, activity_ids = technical_media_identity("a" * 40)
    for activity_id in activity_ids:
        response = browser.get(f"/v1/activities/{activity_id}")
        check(response.status_code == 200, f"Local activity returned {response.status_code}")
        media = response.json()["media"]
        check(
            media["state"] == "approved" and media["playback_available"],
            "Film playback unavailable",
        )
        check(media["delivery"] is not None, "Film delivery descriptor unavailable")
        checked = 0
        for name in ("progressive_url", "manifest_url"):
            source = media["delivery"].get(name)
            if not source:
                continue
            path = media_path(source)
            headers = {"Range": "bytes=0-4095"} if name == "progressive_url" else {}
            delivered = browser.get(path, headers=headers)
            check(
                delivered.status_code in {200, 206},
                f"Local {name} returned {delivered.status_code}",
            )
            if name == "progressive_url":
                check(
                    delivered.status_code == 206 and len(delivered.content) == 4096,
                    "MP4 range length failed",
                )
                check(
                    delivered.headers["content-range"].startswith("bytes 0-4095/"),
                    "MP4 content range failed",
                )
                check(
                    delivered.content[4:8] == b"ftyp", "MP4 range did not return actual film bytes"
                )
                head = browser.head(path)
                check(head.status_code == 200 and not head.content, "MP4 HEAD contract failed")
            else:
                check(delivered.text.startswith("#EXTM3U"), "HLS manifest signature failed")
                variant_url = next(
                    line
                    for line in delivered.text.splitlines()
                    if line and not line.startswith("#")
                )
                variant = browser.get(media_path(variant_url))
                check(
                    variant.status_code == 200 and variant.text.startswith("#EXTM3U"),
                    "HLS variant failed",
                )
                segment_url = next(
                    line for line in variant.text.splitlines() if line and not line.startswith("#")
                )
                segment = browser.get(media_path(segment_url))
                check(
                    segment.status_code == 200 and len(segment.content) >= 188,
                    "HLS segment unavailable",
                )
                check(segment.content[0] == 0x47, "HLS segment did not contain MPEG-TS film bytes")
            with local_client(timeout=10) as anonymous:
                denied = anonymous.get(path)
                check(denied.status_code in {401, 403}, "Unauthenticated film bytes must be denied")
            checked += 1
        check(checked == 2, "Both progressive and HLS film delivery must be available")
