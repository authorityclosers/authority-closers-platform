"""Prove one real local Studio video upload through learner delivery.

This is a deliberately narrow disposable-sandbox proof.  It authenticates
through the local web surfaces, uses the seeded synthetic Studio course, sends
the real licensed fixture through the HTTP upload route, waits for the local
worker, binds it to a dedicated synthetic video activity, grants the seeded
learner access through the supported admin command, and checks the resulting
learner delivery bytes.  It never writes credentials, cookies, signed URLs,
raw API bodies, or media copies to the proof directory.

The script is intentionally not a deployment check.  It only accepts the
fixed loopback hosts and the exact sandbox identifiers from sandbox.json.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import time
from contextlib import suppress
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from urllib.parse import urljoin, urlsplit
from uuid import UUID, uuid4

from playwright.sync_api import Browser, BrowserContext, Page, Response, sync_playwright
from playwright.sync_api import TimeoutError as PlaywrightTimeoutError

ROOT = Path(__file__).resolve().parents[1]
SANDBOX = ROOT / ".tmp" / "local-platform" / "sandbox.json"
FIXTURE = (
    ROOT
    / "tools"
    / "media-player-stress"
    / ".artifacts"
    / "staging-alpha-public-films-12s-v1"
    / "bbb-12s"
    / "progressive.mp4"
)
OUTPUT_ROOT = ROOT / ".tmp" / "local-platform" / "new" / "studio-video-upload"

COACH_ORIGIN = "http://coach.localhost:3102"
ADMIN_ORIGIN = "http://admin.localhost:3101"
LEARNER_ORIGIN = "http://learner.localhost:3100"
LOCAL_ORIGINS = {COACH_ORIGIN, ADMIN_ORIGIN, LEARNER_ORIGIN}

UUID_PATTERN = re.compile(r"^[0-9a-fA-F]{8}-(?:[0-9a-fA-F]{4}-){3}[0-9a-fA-F]{12}$")
SIGNED_DELIVERY_PATH = re.compile(r"^/v1/media/(?:playback|delivery)/")
DEDICATED_VIDEO_TITLE = "Local video approval UI check"
ALLOWED_AUTH_WRITES = {
    ("POST", "/v1/auth/password/login"),
    ("POST", "/v1/auth/logout"),
    ("POST", "/v1/context"),
}


class ProofFailure(RuntimeError):
    """A safe, stage-labelled failure that contains no response body or URL."""

    def __init__(self, stage: str, reason: str, *, status: int | None = None):
        super().__init__(reason)
        self.stage = stage
        self.reason = reason
        self.status = status


class BrowserActivity:
    """Own one context and a fail-closed page request guard."""

    def __init__(self, browser: Browser, origin: str, *, viewport: dict[str, int]):
        self.origin = origin
        self.blocked: list[dict[str, str]] = []
        self.external: list[dict[str, str]] = []
        self.console_counts: dict[str, int] = {}
        self.allowed_writes: set[tuple[str, str]] = set(ALLOWED_AUTH_WRITES)
        self.context: BrowserContext = browser.new_context(viewport=viewport)
        self.context.route("**/*", self._guard)
        self.page = self.context.new_page()
        self.page.on(
            "console",
            lambda message: self.console_counts.__setitem__(
                message.type, self.console_counts.get(message.type, 0) + 1
            ),
        )
        self.page.on(
            "pageerror",
            lambda _error: self.console_counts.__setitem__(
                "pageerror", self.console_counts.get("pageerror", 0) + 1
            ),
        )

    def _guard(self, route: Any) -> None:
        request = route.request
        parsed = urlsplit(request.url)
        request_origin = f"{parsed.scheme}://{parsed.netloc}"
        key = (request.method.upper(), parsed.path)
        if request_origin == self.origin and (
            request.method.upper() in {"GET", "HEAD"} or key in self.allowed_writes
        ):
            route.continue_()
            return
        if request_origin in LOCAL_ORIGINS:
            self.blocked.append({"method": request.method.upper(), "path": parsed.path})
        else:
            self.external.append(
                {"method": request.method.upper(), "origin": request_origin, "path": parsed.path}
            )
        route.abort()

    def allow(self, method: str, path: str) -> None:
        self.allowed_writes.add((method.upper(), path))

    def close(self) -> None:
        self.page.close()
        self.context.close()


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Bounded real local Coach upload/worker/learner playback proof. "
            "Uses only the disposable synthetic sandbox and fixed loopback hosts."
        )
    )
    parser.add_argument("--mode", choices=("live",), default="live")
    parser.add_argument(
        "--timeout-seconds",
        type=int,
        default=600,
        help="Maximum worker polling time (120-900 seconds; default: 600).",
    )
    parser.add_argument(
        "--poll-seconds",
        type=int,
        default=5,
        help="Worker status polling interval (2-30 seconds; default: 5).",
    )
    return parser.parse_args()


def _validate_args(args: argparse.Namespace) -> None:
    if not 120 <= args.timeout_seconds <= 900:
        raise SystemExit("--timeout-seconds must be between 120 and 900")
    if not 2 <= args.poll_seconds <= 30:
        raise SystemExit("--poll-seconds must be between 2 and 30")


def _uuid(value: Any, label: str) -> str:
    if not isinstance(value, str) or UUID_PATTERN.fullmatch(value) is None:
        raise ProofFailure("sandbox", f"{label}_is_not_a_uuid")
    return str(UUID(value))


def _load_sandbox() -> dict[str, str]:
    if not SANDBOX.is_file():
        raise ProofFailure("sandbox", "sandbox_manifest_missing")
    try:
        raw = json.loads(SANDBOX.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        raise ProofFailure("sandbox", "sandbox_manifest_unreadable") from None
    if not isinstance(raw, dict):
        raise ProofFailure("sandbox", "sandbox_manifest_shape_invalid")
    required = (
        "academy_tenant_id",
        "studio_program_id",
        "account_emails",
    )
    if any(key not in raw for key in required):
        raise ProofFailure("sandbox", "sandbox_manifest_missing_required_fields")
    tenant_id = _uuid(raw["academy_tenant_id"], "academy_tenant_id")
    program_id = _uuid(raw["studio_program_id"], "studio_program_id")
    emails = raw["account_emails"]
    if not isinstance(emails, list) or set(emails) != {
        "learner@ac.localhost",
        "coach@ac.localhost",
        "admin@ac.localhost",
    }:
        raise ProofFailure("sandbox", "sandbox_accounts_are_not_the_exact_fixture_set")
    return {"academy_tenant_id": tenant_id, "studio_program_id": program_id}


def _new_output() -> Path:
    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    output = OUTPUT_ROOT / f"actual-{stamp}-{uuid4().hex[:8]}"
    output.mkdir(parents=True, exist_ok=False)
    return output


def _same_origin_path(value: Any, *, origin: str, stage: str) -> str:
    if not isinstance(value, str) or not value:
        raise ProofFailure(stage, "url_missing")
    parsed = urlsplit(value)
    if (parsed.scheme or parsed.netloc) and f"{parsed.scheme}://{parsed.netloc}" != origin:
        raise ProofFailure(stage, "url_origin_mismatch")
    if parsed.query or parsed.fragment or not parsed.path.startswith("/v1/"):
        raise ProofFailure(stage, "url_scope_invalid")
    return parsed.path


def _delivery_url(value: Any, *, stage: str) -> str:
    if not isinstance(value, str) or not value:
        raise ProofFailure(stage, "delivery_url_missing")
    parsed = urlsplit(urljoin(LEARNER_ORIGIN, value))
    if f"{parsed.scheme}://{parsed.netloc}" != LEARNER_ORIGIN:
        raise ProofFailure(stage, "delivery_url_origin_mismatch")
    if not SIGNED_DELIVERY_PATH.match(parsed.path):
        raise ProofFailure(stage, "delivery_url_path_not_private_media")
    if not parsed.query:
        raise ProofFailure(stage, "delivery_url_has_no_server_grant")
    return urljoin(LEARNER_ORIGIN, value)


def _safe_path(value: str) -> str:
    parsed = urlsplit(value)
    if parsed.scheme or parsed.netloc:
        return parsed.path or "/"
    return parsed.path or value.split("?", 1)[0]


def _safe_response_headers(response: Any) -> dict[str, str]:
    try:
        return {str(key).lower(): str(value) for key, value in response.headers.items()}
    except Exception:
        return {}


def _json_response(response: dict[str, Any], *, stage: str, expected: set[int]) -> dict[str, Any]:
    status = response.get("status")
    if not isinstance(status, int) or status not in expected:
        safe_status = status if isinstance(status, int) else "unknown"
        raise ProofFailure(stage, f"http_{safe_status}", status=status)
    text = response.get("text")
    if not isinstance(text, str):
        raise ProofFailure(stage, "response_body_unavailable", status=status)
    try:
        value = json.loads(text)
    except json.JSONDecodeError:
        raise ProofFailure(stage, "response_json_invalid", status=status) from None
    if not isinstance(value, dict):
        raise ProofFailure(stage, "response_json_not_object", status=status)
    return value


def _page_json(
    browser_activity: BrowserActivity,
    method: str,
    path: str,
    *,
    stage: str,
    body: dict[str, Any] | None = None,
    headers: dict[str, str] | None = None,
    expected: set[int] | None = None,
) -> dict[str, Any]:
    if not path.startswith("/v1/") or "?" in path:
        raise ProofFailure(stage, "api_path_not_exact")
    method = method.upper()
    if method not in {"GET", "POST", "PATCH", "PUT"}:
        raise ProofFailure(stage, "api_method_not_allowed")
    if method not in {"GET", "HEAD"}:
        browser_activity.allow(method, path)
    request_headers = {"accept": "application/json"}
    if headers:
        request_headers.update({str(key).lower(): str(value) for key, value in headers.items()})
    result = browser_activity.page.evaluate(
        """
        async ({path, method, headers, body}) => {
          const init = {
            method,
            headers,
            credentials: "same-origin",
            cache: "no-store",
            redirect: "error",
          };
          if (body !== null) init.body = JSON.stringify(body);
          const response = await fetch(path, init);
          return {
            status: response.status,
            headers: Object.fromEntries(response.headers.entries()),
            text: await response.text(),
          };
        }
        """,
        {"path": path, "method": method, "headers": request_headers, "body": body},
    )
    return _json_response(result, stage=stage, expected=expected or {200})


def _login_operations(
    browser_activity: BrowserActivity,
    *,
    email: str,
    password: str,
    tenant_id: str,
    destination: str,
    stage: str,
) -> None:
    page = browser_activity.page
    try:
        page.goto(browser_activity.origin + "/login", wait_until="domcontentloaded", timeout=30_000)
        page.wait_for_load_state("networkidle", timeout=30_000)
        page.get_by_label("Email address", exact=True).fill(email)
        page.get_by_label("Password", exact=True).fill(password)
        page.get_by_label("Local tenant ID", exact=True).fill(tenant_id)
        page.get_by_role("button", name="Sign in", exact=True).click()
        page.wait_for_timeout(300)
        page.wait_for_url(
            lambda url: (
                urlsplit(url).netloc == urlsplit(browser_activity.origin).netloc
                and urlsplit(url).path == destination
            ),
        )
        page.wait_for_load_state("networkidle", timeout=30_000)
    except (PlaywrightTimeoutError, AssertionError):
        raise ProofFailure(stage, "normal_form_login_did_not_complete") from None


def _login_learner(
    browser_activity: BrowserActivity,
    *,
    password: str,
    stage: str,
) -> dict[str, Any]:
    page = browser_activity.page
    try:
        page.goto(browser_activity.origin + "/login", wait_until="domcontentloaded", timeout=30_000)
        page.wait_for_load_state("networkidle", timeout=30_000)
        page.get_by_label("Email address", exact=True).fill("learner@ac.localhost")
        page.get_by_label("Password", exact=True).fill(password)
        page.get_by_role("button", name="Sign in", exact=True).click()
        page.wait_for_timeout(500)
        page.wait_for_load_state("networkidle", timeout=30_000)
        if urlsplit(page.url).path == "/login":
            raise ProofFailure(stage, "normal_form_login_returned_to_login")
    except ProofFailure:
        raise
    except (PlaywrightTimeoutError, AssertionError):
        raise ProofFailure(stage, "normal_form_login_did_not_complete") from None
    return _page_json(browser_activity, "GET", "/v1/me", stage=stage, expected={200})


def _version(detail: dict[str, Any], version_id: str, *, stage: str) -> dict[str, Any]:
    versions = detail.get("versions")
    if not isinstance(versions, list):
        raise ProofFailure(stage, "program_versions_missing")
    matches = [item for item in versions if isinstance(item, dict) and item.get("id") == version_id]
    if len(matches) != 1:
        raise ProofFailure(stage, "program_version_not_unique")
    return matches[0]


def _find_dedicated_activity(
    detail: dict[str, Any], *, stage: str
) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
    versions = detail.get("versions")
    if not isinstance(versions, list):
        raise ProofFailure(stage, "program_versions_missing")
    exact: list[tuple[dict[str, Any], dict[str, Any], dict[str, Any]]] = []
    for version in versions:
        if not isinstance(version, dict):
            continue
        modules = version.get("modules")
        if not isinstance(modules, list):
            continue
        for module in modules:
            if not isinstance(module, dict):
                continue
            activities = module.get("activities")
            if not isinstance(activities, list):
                continue
            for activity in activities:
                if not isinstance(activity, dict) or activity.get("kind") != "VIDEO":
                    continue
                title = activity.get("title")
                if (
                    isinstance(title, str)
                    and title.strip().casefold() == DEDICATED_VIDEO_TITLE.casefold()
                ):
                    exact.append((version, module, activity))
    if not exact:
        raise ProofFailure(stage, "dedicated_synthetic_video_activity_missing")
    published = [item for item in exact if item[0].get("status") == "published"]
    draft_ready = [
        item
        for item in exact
        if item[0].get("status") == "draft" and item[0].get("readiness") == "ready"
    ]
    selected = published or draft_ready
    if not selected:
        raise ProofFailure(stage, "dedicated_video_is_not_published_or_publishable")
    selected.sort(
        key=lambda item: (
            int(item[0].get("version_number", 0)),
            int(item[1].get("position", 0)),
            int(item[2].get("position", 0)),
        )
    )
    return selected[-1]


def _assert_program(detail: dict[str, Any], *, tenant_id: str, program_id: str) -> None:
    if detail.get("id") != program_id or detail.get("tenant_id") != tenant_id:
        raise ProofFailure("course", "program_identity_mismatch")
    if detail.get("scope") != "tenant" or detail.get("access") != "selected_tenant":
        raise ProofFailure("course", "program_is_not_selected_tenant_scope")
    title = detail.get("title")
    if not isinstance(title, str) or "synthetic" not in title.casefold():
        raise ProofFailure("course", "program_is_not_marked_synthetic")


def _ffprobe(content: bytes) -> dict[str, Any]:
    executable = shutil.which("ffprobe")
    if executable is None:
        return {"available": False, "ok": False, "reason": "ffprobe_not_found"}
    try:
        result = subprocess.run(  # noqa: S603 - executable is resolved from the local PATH
            [executable, "-v", "error", "-show_streams", "-show_format", "-of", "json", "pipe:0"],
            input=content,
            capture_output=True,
            timeout=90,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired):
        return {"available": True, "ok": False, "reason": "ffprobe_failed"}
    if result.returncode != 0:
        return {"available": True, "ok": False, "reason": "ffprobe_rejected_stream"}
    try:
        payload = json.loads(result.stdout.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        return {"available": True, "ok": False, "reason": "ffprobe_json_invalid"}
    streams = payload.get("streams") if isinstance(payload, dict) else None
    if not isinstance(streams, list):
        return {"available": True, "ok": False, "reason": "ffprobe_streams_missing"}
    video = next(
        (
            stream
            for stream in streams
            if isinstance(stream, dict) and stream.get("codec_type") == "video"
        ),
        None,
    )
    if not isinstance(video, dict):
        return {"available": True, "ok": False, "reason": "ffprobe_video_stream_missing"}
    duration = (
        payload.get("format", {}).get("duration")
        if isinstance(payload.get("format"), dict)
        else None
    )
    return {
        "available": True,
        "ok": True,
        "codec": video.get("codec_name"),
        "width": video.get("width"),
        "height": video.get("height"),
        "duration_seconds": float(duration) if isinstance(duration, str) else duration,
    }


def _response_body(
    response: Response, *, stage: str, expected: set[int]
) -> tuple[int, dict[str, str], bytes]:
    status = response.status
    if status not in expected:
        raise ProofFailure(stage, f"http_{status}", status=status)
    try:
        body = response.body()
    except Exception:
        raise ProofFailure(stage, "response_body_unavailable", status=status) from None
    return status, _safe_response_headers(response), body


def _private_media_request(
    page: Page,
    url: str,
    *,
    method: str = "GET",
    headers: dict[str, str] | None = None,
    stage: str,
    expected: set[int],
) -> tuple[int, dict[str, str], bytes]:
    parsed = urlsplit(url)
    if f"{parsed.scheme}://{parsed.netloc}" != LEARNER_ORIGIN:
        raise ProofFailure(stage, "delivery_origin_mismatch")
    if not SIGNED_DELIVERY_PATH.match(parsed.path) or not parsed.query:
        raise ProofFailure(stage, "delivery_scope_invalid")
    request_headers = {"accept": "*/*"}
    if headers:
        request_headers.update(headers)
    try:
        response = page.request.fetch(
            url,
            method=method,
            headers=request_headers,
            timeout=180_000,
            max_redirects=0,
        )
    except Exception:
        raise ProofFailure(stage, "delivery_request_failed") from None
    return _response_body(response, stage=stage, expected=expected)


def _playlist_child(playlist: str, *, base_url: str, stage: str) -> str:
    map_uri: str | None = None
    for line in playlist.splitlines():
        value = line.strip()
        if not value:
            continue
        if value.startswith("#EXT-X-MAP:"):
            match = re.search(r'URI="([^"]+)"', value)
            if match:
                map_uri = match.group(1)
            continue
        if value.startswith("#"):
            continue
        candidate = urljoin(base_url, value)
        parsed = urlsplit(candidate)
        if f"{parsed.scheme}://{parsed.netloc}" != LEARNER_ORIGIN or not parsed.query:
            raise ProofFailure(stage, "playlist_child_scope_invalid")
        return candidate
    if map_uri:
        candidate = urljoin(base_url, map_uri)
        parsed = urlsplit(candidate)
        if f"{parsed.scheme}://{parsed.netloc}" == LEARNER_ORIGIN and parsed.query:
            return candidate
    raise ProofFailure(stage, "playlist_has_no_child")


def _renderer_probe(page: Page, progressive_url: str, *, stage: str) -> dict[str, Any]:
    try:
        result = page.evaluate(
            """
            async (url) => {
              const response = await fetch(url, {credentials: "same-origin", cache: "no-store"});
              if (!response.ok) return {ok: false, reason: "fetch_status_" + response.status};
              const blob = await response.blob();
              const source = URL.createObjectURL(blob);
              const video = document.createElement("video");
              video.preload = "metadata";
              video.muted = true;
              video.src = source;
              document.body.append(video);
              const waitFor = (eventName) => new Promise((resolve, reject) => {
                const timeout = setTimeout(() => reject(new Error("timeout")), 20000);
                video.addEventListener(
                  eventName,
                  () => { clearTimeout(timeout); resolve(); },
                  {once: true},
                );
                video.addEventListener(
                  "error",
                  () => { clearTimeout(timeout); reject(new Error("media")); },
                  {once: true},
                );
              });
              try {
                await waitFor("loadedmetadata");
                const metadata = {
                  duration: video.duration,
                  width: video.videoWidth,
                  height: video.videoHeight,
                };
                const target = Math.min(1, Math.max(0, video.duration / 2));
                video.currentTime = target;
                await waitFor("seeked");
                const sought = video.currentTime;
                video.remove();
                URL.revokeObjectURL(source);
                return {ok: true, metadata, sought};
              } catch {
                video.remove();
                URL.revokeObjectURL(source);
                return {ok: false, reason: "browser_decode_or_seek_failed"};
              }
            }
            """,
            progressive_url,
        )
    except Exception:
        return {"ok": False, "reason": "browser_renderer_probe_failed"}
    return (
        result if isinstance(result, dict) else {"ok": False, "reason": "renderer_result_invalid"}
    )


def _write_proof(output: Path, proof: dict[str, Any]) -> None:
    (output / "proof.json").write_text(
        json.dumps(proof, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )


def main() -> int:
    args = _parse_args()
    _validate_args(args)
    output = _new_output()
    started = time.monotonic()
    proof: dict[str, Any] = {
        "status": "incomplete",
        "mode": args.mode,
        "environment": "disposable local sandbox only",
        "actual_vs_fixture": (
            "actual HTTP upload, local scanner/worker, and learner delivery; "
            "fixture used only as the source bytes"
        ),
        "origins": {"coach": COACH_ORIGIN, "admin": ADMIN_ORIGIN, "learner": LEARNER_ORIGIN},
        "screenshots": [],
        "stages": {},
    }
    activities: list[BrowserActivity] = []
    browser = None
    coach: BrowserActivity | None = None
    admin: BrowserActivity | None = None
    learner: BrowserActivity | None = None
    try:
        password = os.environ.get("AC_LOCAL_BROWSER_TEST_PASSWORD")
        if not password:
            raise ProofFailure("auth", "AC_LOCAL_BROWSER_TEST_PASSWORD_is_required")
        sandbox = _load_sandbox()
        if not FIXTURE.is_file():
            raise ProofFailure("source", "licensed_4k_fixture_missing")
        source = FIXTURE.read_bytes()
        if len(source) <= 1_000_000:
            raise ProofFailure("source", "fixture_is_not_the_expected_large_source")
        source_hash = hashlib.sha256(source).hexdigest()
        proof["source"] = {
            "label": "bbb-12s/progressive.mp4",
            "bytes": len(source),
            "sha256": source_hash,
        }

        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(channel="chrome", headless=True)
            coach = BrowserActivity(browser, COACH_ORIGIN, viewport={"width": 1440, "height": 1000})
            admin = BrowserActivity(browser, ADMIN_ORIGIN, viewport={"width": 1440, "height": 1000})
            learner = BrowserActivity(
                browser, LEARNER_ORIGIN, viewport={"width": 1440, "height": 1000}
            )
            activities = [coach, admin, learner]

            _login_operations(
                coach,
                email="coach@ac.localhost",
                password=password,
                tenant_id=sandbox["academy_tenant_id"],
                destination="/studio",
                stage="coach_auth",
            )
            proof["stages"]["coach_auth"] = "normal_form_login"
            program_path = f"/v1/admin/studio/programs/{sandbox['studio_program_id']}"
            detail = _page_json(coach, "GET", program_path, stage="course", expected={200})
            _assert_program(
                detail,
                tenant_id=sandbox["academy_tenant_id"],
                program_id=sandbox["studio_program_id"],
            )
            try:
                version, module, activity = _find_dedicated_activity(detail, stage="course")
            except ProofFailure:
                # Keep an auditable, sanitized inventory when the disposable
                # fixture is not yet prepared; never persist full API JSON.
                inventory: list[dict[str, Any]] = []
                for candidate_version in detail.get("versions", []):
                    if not isinstance(candidate_version, dict):
                        continue
                    for candidate_module in candidate_version.get("modules", []):
                        if not isinstance(candidate_module, dict):
                            continue
                        for candidate_activity in candidate_module.get("activities", []):
                            if isinstance(candidate_activity, dict):
                                inventory.append(
                                    {
                                        "version_number": candidate_version.get("version_number"),
                                        "version_status": candidate_version.get("status"),
                                        "readiness": candidate_version.get("readiness"),
                                        "blockers": candidate_version.get("blockers", []),
                                        "activity_kind": candidate_activity.get("kind"),
                                        "activity_title": candidate_activity.get("title"),
                                    }
                                )
                proof["course_inventory"] = inventory
                raise
            program_version_id = _uuid(version.get("id"), "program_version_id")
            activity_id = _uuid(activity.get("id"), "activity_id")
            module_id = _uuid(module.get("id"), "module_id")
            proof["course"] = {
                "program_id": sandbox["studio_program_id"],
                "program_title": detail.get("title"),
                "program_scope": detail.get("scope"),
                "version_id": program_version_id,
                "version_number": version.get("version_number"),
                "version_status_before": version.get("status"),
                "activity_id": activity_id,
                "activity_title": activity.get("title"),
                "module_id": module_id,
            }
            proof["stages"]["course"] = "synthetic_program_and_dedicated_video_activity_verified"

            capability_path = f"{program_path}/video-upload-capability"
            capability = _page_json(
                coach, "GET", capability_path, stage="capability", expected={200}
            )
            if capability.get("available") is not True:
                raise ProofFailure("capability", "local_video_capability_not_available")
            if capability.get("max_source_bytes", 0) < len(source):
                raise ProofFailure("capability", "fixture_exceeds_local_capability")
            if "video/mp4" not in capability.get("accepted_content_types", []):
                raise ProofFailure("capability", "video_mp4_not_accepted")
            proof["capability"] = {
                "available": True,
                "max_source_bytes": capability.get("max_source_bytes"),
                "accepted_content_types": capability.get("accepted_content_types"),
            }
            proof["stages"]["capability"] = "enabled_and_bounded"

            upload_key = "local-proof-upload-" + uuid4().hex
            upload_request = {
                "filename": "progressive.mp4",
                "content_type": "video/mp4",
                "content_length": len(source),
                "checksum_sha256": source_hash,
            }
            intent_path = f"{program_path}/video-uploads"
            intent = _page_json(
                coach,
                "POST",
                intent_path,
                stage="upload_admission",
                body=upload_request,
                headers={"idempotency-key": upload_key},
                expected={200, 201},
            )
            upload_id = _uuid(intent.get("upload_id"), "upload_id")
            asset_id = _uuid(intent.get("media_id"), "media_id")
            media_version_id = _uuid(intent.get("media_version_id"), "media_version_id")
            if intent.get("version_number") != 1:
                raise ProofFailure("upload_admission", "upload_version_is_not_one")
            bytes_path = _same_origin_path(
                intent.get("upload_url"), origin=COACH_ORIGIN, stage="upload_admission"
            )
            expected_bytes_path = f"{program_path}/video-uploads/{upload_id}/bytes"
            if bytes_path != expected_bytes_path:
                raise ProofFailure("upload_admission", "upload_url_is_not_exact_course_route")
            upload_headers = intent.get("upload_headers")
            if not isinstance(upload_headers, dict) or set(upload_headers) != {
                "content-type",
                "content-length",
                "x-content-sha256",
            }:
                raise ProofFailure("upload_admission", "upload_envelope_headers_invalid")
            if upload_headers != {
                "content-type": "video/mp4",
                "content-length": str(len(source)),
                "x-content-sha256": source_hash,
            }:
                raise ProofFailure("upload_admission", "upload_envelope_mismatch")
            if not isinstance(intent.get("max_bytes"), int) or intent["max_bytes"] < len(source):
                raise ProofFailure("upload_admission", "upload_max_bytes_mismatch")
            proof["upload"] = {
                "intent_status": intent.get("state"),
                "upload_id": upload_id,
                "asset_id": asset_id,
                "version_id": media_version_id,
                "exact_route": True,
                "declared_bytes": len(source),
            }

            put_headers = {str(key): str(value) for key, value in upload_headers.items()}
            put_headers["origin"] = COACH_ORIGIN
            try:
                put_response = coach.page.request.put(
                    COACH_ORIGIN + bytes_path,
                    data=source,
                    headers=put_headers,
                    timeout=max(180_000, args.timeout_seconds * 1000),
                    max_redirects=0,
                )
            except Exception:
                raise ProofFailure("upload_bytes", "byte_request_failed") from None
            put_status, put_receipt_headers, put_body = _response_body(
                put_response, stage="upload_bytes", expected={204}
            )
            del put_body
            if put_receipt_headers.get("x-ac-upload-bytes") != str(len(source)):
                raise ProofFailure(
                    "upload_bytes", "byte_receipt_length_mismatch", status=put_status
                )
            if put_receipt_headers.get("x-ac-upload-sha256") != source_hash:
                raise ProofFailure("upload_bytes", "byte_receipt_hash_mismatch", status=put_status)
            proof["upload"]["byte_receipt"] = {
                "status": put_status,
                "length_matches": True,
                "sha256_matches": True,
            }
            proof["stages"]["upload_bytes"] = "actual_fixture_uploaded_and_receipted"

            complete_path = f"{program_path}/video-uploads/{upload_id}/complete"
            complete_key = "local-proof-complete-" + uuid4().hex
            completion = _page_json(
                coach,
                "POST",
                complete_path,
                stage="upload_complete",
                headers={"idempotency-key": complete_key},
                expected={200, 202},
            )
            if _uuid(completion.get("upload_id"), "completion_upload_id") != upload_id:
                raise ProofFailure("upload_complete", "completion_upload_identity_mismatch")
            if _uuid(completion.get("asset_id"), "completion_asset_id") != asset_id:
                raise ProofFailure("upload_complete", "completion_asset_identity_mismatch")
            if _uuid(completion.get("version_id"), "completion_version_id") != media_version_id:
                raise ProofFailure("upload_complete", "completion_version_identity_mismatch")
            if completion.get("state") not in {"processing", "ready"}:
                raise ProofFailure("upload_complete", "completion_did_not_start_processing")
            proof["upload"]["completion"] = {
                "state": completion.get("state"),
                "processing_job_present": isinstance(completion.get("processing_job_id"), str),
                "http_status": completion.get("state"),
            }

            poll_states: list[str] = []
            poll_started = time.monotonic()
            final_status: dict[str, Any] | None = None
            while time.monotonic() - poll_started <= args.timeout_seconds:
                status_body = _page_json(
                    coach,
                    "GET",
                    f"{program_path}/video-uploads/{upload_id}",
                    stage="processing_poll",
                    expected={200},
                )
                if _uuid(status_body.get("upload_id"), "status_upload_id") != upload_id:
                    raise ProofFailure("processing_poll", "status_upload_identity_mismatch")
                if _uuid(status_body.get("asset_id"), "status_asset_id") != asset_id:
                    raise ProofFailure("processing_poll", "status_asset_identity_mismatch")
                if _uuid(status_body.get("version_id"), "status_version_id") != media_version_id:
                    raise ProofFailure("processing_poll", "status_version_identity_mismatch")
                state = status_body.get("state")
                if not isinstance(state, str):
                    raise ProofFailure("processing_poll", "status_state_missing")
                if not poll_states or poll_states[-1] != state:
                    poll_states.append(state)
                if state in {"processing", "ready"} and status_body.get(
                    "uploaded_bytes"
                ) != status_body.get("declared_bytes"):
                    raise ProofFailure("processing_poll", "status_byte_count_not_exact")
                if state in {"failed", "retired"}:
                    raise ProofFailure("processing_poll", f"worker_terminal_{state}")
                if state == "ready":
                    final_status = status_body
                    break
                coach.page.wait_for_timeout(args.poll_seconds * 1000)
            if final_status is None:
                raise ProofFailure("processing_poll", "worker_deadline_expired")
            if final_status.get("declared_bytes") != len(source) or final_status.get(
                "uploaded_bytes"
            ) != len(source):
                raise ProofFailure("processing_poll", "ready_byte_count_mismatch")
            if (
                not isinstance(final_status.get("duration_seconds"), (int, float))
                or final_status["duration_seconds"] <= 0
            ):
                raise ProofFailure("processing_poll", "ready_duration_missing")
            if not isinstance(final_status.get("width"), int) or not isinstance(
                final_status.get("height"), int
            ):
                raise ProofFailure("processing_poll", "ready_dimensions_missing")
            proof["upload"]["processing"] = {
                "states": poll_states,
                "elapsed_seconds": round(time.monotonic() - poll_started, 2),
                "state": final_status.get("state"),
                "declared_bytes": final_status.get("declared_bytes"),
                "uploaded_bytes": final_status.get("uploaded_bytes"),
                "duration_seconds": final_status.get("duration_seconds"),
                "width": final_status.get("width"),
                "height": final_status.get("height"),
            }
            proof["stages"]["processing_poll"] = "scanner_and_ffmpeg_worker_reached_ready"

            if version.get("status") == "draft":
                etag = version.get("etag")
                if not isinstance(etag, str) or not etag:
                    raise ProofFailure("publication", "draft_publication_etag_missing")
                publication_path = f"/v1/admin/program-versions/{program_version_id}/publish"
                publication = _page_json(
                    coach,
                    "POST",
                    publication_path,
                    stage="publication",
                    body={"reason": "Actual local synthetic Studio video playback proof."},
                    headers={
                        "if-match": etag,
                        "idempotency-key": "local-proof-publish-" + uuid4().hex,
                    },
                    expected={200},
                )
                if _uuid(publication.get("id"), "publication_version_id") != program_version_id:
                    raise ProofFailure("publication", "published_version_identity_mismatch")
                if publication.get("status") != "published":
                    raise ProofFailure("publication", "publication_not_published")
                proof["course"]["version_status_after"] = publication.get("status")
                proof["stages"]["publication"] = "synthetic_version_published_with_normal_command"
            else:
                proof["course"]["version_status_after"] = version.get("status")
                proof["stages"]["publication"] = "existing_synthetic_published_version_used"

            current_path = f"{program_path}/activities/{activity_id}/video"
            current = _page_json(
                coach, "GET", current_path, stage="selection_current", expected={200}
            )
            existing_binding = current.get("binding")
            expected_binding_id: str | None = None
            if existing_binding is not None:
                if not isinstance(existing_binding, dict):
                    raise ProofFailure("selection_current", "existing_binding_shape_invalid")
                expected_binding_id = _uuid(
                    existing_binding.get("binding_id"), "existing_binding_id"
                )
            selection = _page_json(
                coach,
                "POST",
                current_path,
                stage="selection",
                body={
                    "asset_id": asset_id,
                    "version_id": media_version_id,
                    "expected_binding_id": expected_binding_id,
                    "approval_reference": "Actual local synthetic Studio video playback proof.",
                },
                headers={"idempotency-key": "local-proof-selection-" + uuid4().hex},
                expected={200},
            )
            if _uuid(selection.get("asset_id"), "selection_asset_id") != asset_id:
                raise ProofFailure("selection", "selection_asset_identity_mismatch")
            if _uuid(selection.get("version_id"), "selection_version_id") != media_version_id:
                raise ProofFailure("selection", "selection_version_identity_mismatch")
            if selection.get("state") != "approved":
                raise ProofFailure("selection", "selection_not_approved")
            proof["selection"] = {
                "state": selection.get("state"),
                "binding_id": _uuid(selection.get("binding_id"), "selection_binding_id"),
                "expected_binding_was_present": expected_binding_id is not None,
                "replayed": selection.get("replayed"),
            }
            proof["stages"]["selection"] = "approved_to_dedicated_synthetic_video_activity"

            page = coach.page
            try:
                page.goto(
                    COACH_ORIGIN + f"/studio/programs/{sandbox['studio_program_id']}",
                    wait_until="domcontentloaded",
                    timeout=30_000,
                )
                page.wait_for_load_state("networkidle", timeout=30_000)
                page.screenshot(path=str(output / "coach-selected.png"), full_page=False)
                proof["screenshots"].append("coach-selected.png")
            except Exception:
                proof["stages"]["coach_screenshot"] = "unavailable"

            _login_operations(
                admin,
                email="admin@ac.localhost",
                password=password,
                tenant_id=sandbox["academy_tenant_id"],
                destination="/",
                stage="admin_auth",
            )
            proof["stages"]["admin_auth"] = "normal_form_login"
            learner_me = _login_learner(learner, password=password, stage="learner_auth")
            learner_person_id = _uuid(learner_me.get("person_id"), "learner_person_id")
            selected_tenant = learner_me.get("selected_tenant_id")
            if selected_tenant != sandbox["academy_tenant_id"]:
                context = _page_json(
                    learner,
                    "POST",
                    "/v1/context",
                    stage="learner_context",
                    body={"tenant_id": sandbox["academy_tenant_id"]},
                    expected={200},
                )
                if context.get("tenant_id") != sandbox["academy_tenant_id"]:
                    raise ProofFailure("learner_context", "academy_context_not_selected")
            proof["stages"]["learner_auth"] = "normal_form_login_and_identity_verified"

            grant_path = "/v1/admin/enrollment-grants"
            grant = _page_json(
                admin,
                "POST",
                grant_path,
                stage="enrollment",
                body={
                    "person_id": learner_person_id,
                    "program_version_id": program_version_id,
                    "reason": "Actual local synthetic Studio video playback proof.",
                },
                headers={"idempotency-key": "local-proof-enrollment-" + uuid4().hex},
                expected={200, 201},
            )
            enrollment_id = _uuid(grant.get("enrollment_id"), "enrollment_id")
            if grant.get("created") is not True and grant.get("replayed") is not True:
                raise ProofFailure("enrollment", "enrollment_receipt_not_created_or_replayed")
            proof["enrollment"] = {
                "enrollment_id": enrollment_id,
                "created": grant.get("created"),
                "replayed": grant.get("replayed"),
                "learner_person_id": learner_person_id,
                "program_version_id": program_version_id,
            }
            proof["stages"]["enrollment"] = "normal_admin_grant_to_seeded_synthetic_learner"

            learning_path = f"/v1/learning/{sandbox['studio_program_id']}"
            learning = _page_json(
                learner, "GET", learning_path, stage="learner_learning", expected={200}
            )
            if (
                learning.get("program_id") != sandbox["studio_program_id"]
                or learning.get("program_version_id") != program_version_id
            ):
                raise ProofFailure("learner_learning", "learning_scope_mismatch")
            learning_activities = [
                item
                for item in (
                    module_item.get("activities", [])
                    for module_item in learning.get("modules", [])
                    if isinstance(module_item, dict)
                )
                for item in item
                if isinstance(item, dict)
            ]
            learning_activity = next(
                (item for item in learning_activities if item.get("id") == activity_id), None
            )
            if not isinstance(learning_activity, dict):
                raise ProofFailure("learner_learning", "dedicated_activity_not_in_enrollment")

            activity_body = _page_json(
                learner,
                "GET",
                f"/v1/activities/{activity_id}",
                stage="learner_activity",
                expected={200},
            )
            media = activity_body.get("media")
            if (
                not isinstance(media, dict)
                or media.get("state") != "approved"
                or media.get("playback_available") is not True
            ):
                raise ProofFailure(
                    "learner_activity", "media_is_not_server_authorized_for_playback"
                )
            if (
                media.get("media_id") != asset_id
                or media.get("media_version_id") != media_version_id
            ):
                raise ProofFailure("learner_activity", "media_identity_mismatch")
            delivery = media.get("delivery")
            if not isinstance(delivery, dict) or delivery.get("protocol") != "hls":
                raise ProofFailure("learner_activity", "hls_delivery_missing")
            progressive_url = _delivery_url(
                delivery.get("progressive_url"), stage="progressive_url"
            )
            manifest_url = _delivery_url(delivery.get("manifest_url"), stage="manifest_url")
            proof["delivery"] = {
                "descriptor_state": media.get("state"),
                "playback_available": media.get("playback_available"),
                "protocol": delivery.get("protocol"),
                "media_id": media.get("media_id"),
                "media_version_id": media.get("media_version_id"),
                "duration_seconds": media.get("duration_seconds"),
                "width": media.get("width"),
                "height": media.get("height"),
                "rendition_count": len(media.get("renditions", []))
                if isinstance(media.get("renditions"), list)
                else None,
                "captions_count": len(media.get("captions", []))
                if isinstance(media.get("captions"), list)
                else None,
                "private_same_origin_paths": {
                    "progressive": _safe_path(progressive_url),
                    "manifest": _safe_path(manifest_url),
                },
            }
            proof["stages"]["learner_activity"] = (
                "approved_binding_and_private_hls_descriptor_verified"
            )

            progressive_status, progressive_headers, progressive_body = _private_media_request(
                learner.page,
                progressive_url,
                stage="progressive_get",
                expected={200},
            )
            if not progressive_body:
                raise ProofFailure(
                    "progressive_get", "progressive_body_empty", status=progressive_status
                )
            progressive_length = progressive_headers.get("content-length")
            proof["playback"] = {
                "progressive": {
                    "status": progressive_status,
                    "bytes": len(progressive_body),
                    "content_length_matches": progressive_length == str(len(progressive_body)),
                    "cache_control_private_no_store": progressive_headers.get("cache-control")
                    == "private, no-store",
                    "ffprobe": _ffprobe(progressive_body),
                }
            }
            if progressive_length != str(len(progressive_body)):
                raise ProofFailure(
                    "progressive_get",
                    "progressive_content_length_mismatch",
                    status=progressive_status,
                )
            if not proof["playback"]["progressive"]["ffprobe"].get("ok"):
                raise ProofFailure(
                    "progressive_get", "progressive_ffprobe_failed", status=progressive_status
                )

            head_status, head_headers, head_body = _private_media_request(
                learner.page,
                progressive_url,
                method="HEAD",
                stage="progressive_head",
                expected={200},
            )
            range_status, range_headers, range_body = _private_media_request(
                learner.page,
                progressive_url,
                headers={"range": "bytes=0-127"},
                stage="progressive_range",
                expected={206},
            )
            proof["playback"]["head"] = {
                "status": head_status,
                "empty_body": not head_body,
                "content_length_matches": head_headers.get("content-length")
                == str(len(progressive_body)),
            }
            proof["playback"]["range"] = {
                "status": range_status,
                "prefix_matches": range_body == progressive_body[:128],
                "content_range": range_headers.get("content-range")
                == f"bytes 0-127/{len(progressive_body)}",
            }
            if head_body or head_headers.get("content-length") != str(len(progressive_body)):
                raise ProofFailure("progressive_head", "head_receipt_mismatch", status=head_status)
            if (
                range_body != progressive_body[:128]
                or range_headers.get("content-range") != f"bytes 0-127/{len(progressive_body)}"
            ):
                raise ProofFailure(
                    "progressive_range", "range_receipt_mismatch", status=range_status
                )

            master_status, master_headers, master_body = _private_media_request(
                learner.page,
                manifest_url,
                stage="hls_master",
                expected={200},
            )
            master_text = master_body.decode("utf-8")
            variant_url = _playlist_child(master_text, base_url=manifest_url, stage="hls_master")
            variant_status, variant_headers, variant_body = _private_media_request(
                learner.page,
                variant_url,
                stage="hls_variant",
                expected={200},
            )
            segment_url = _playlist_child(
                variant_body.decode("utf-8"), base_url=variant_url, stage="hls_variant"
            )
            segment_status, segment_headers, segment_body = _private_media_request(
                learner.page,
                segment_url,
                stage="hls_segment",
                expected={200},
            )
            if not segment_body:
                raise ProofFailure("hls_segment", "hls_segment_empty", status=segment_status)
            proof["playback"]["hls"] = {
                "master": {
                    "status": master_status,
                    "playlist": master_headers.get("cache-control") == "private, no-store",
                },
                "variant": {
                    "status": variant_status,
                    "playlist": variant_headers.get("cache-control") == "private, no-store",
                },
                "segment": {
                    "status": segment_status,
                    "bytes": len(segment_body),
                    "non_empty": True,
                    "cache_control_private_no_store": segment_headers.get("cache-control")
                    == "private, no-store",
                },
            }
            proof["playback"]["renderer"] = _renderer_probe(
                learner.page, progressive_url, stage="renderer"
            )
            proof["stages"]["playback"] = (
                "progressive_ffprobe_seek_range_and_hls_rendition_verified"
            )

            try:
                learner.page.goto(
                    LEARNER_ORIGIN + f"/activity/{activity_id}",
                    wait_until="domcontentloaded",
                    timeout=30_000,
                )
                learner.page.wait_for_load_state("networkidle", timeout=30_000)
                learner.page.screenshot(path=str(output / "learner-playback.png"), full_page=False)
                proof["screenshots"].append("learner-playback.png")
            except Exception:
                proof["stages"]["learner_screenshot"] = "unavailable"

            if any(activity.external for activity in activities):
                raise ProofFailure("network_scope", "external_request_was_attempted")
            proof["network_scope"] = {
                "external_requests": 0,
                "blocked_unapproved_writes": [
                    {"surface": item.origin, **blocked}
                    for item in activities
                    for blocked in item.blocked
                    if blocked["method"] not in {method for method, _ in ALLOWED_AUTH_WRITES}
                ],
            }
            proof["status"] = "passed"
    except ProofFailure as failure:
        proof["failure"] = {
            "stage": failure.stage,
            "reason": failure.reason,
            "status": failure.status,
        }
    except Exception as error:
        proof["failure"] = {
            "stage": "unexpected",
            "reason": type(error).__name__,
            "status": None,
        }
    finally:
        for activity in reversed(activities):
            with suppress(Exception):
                activity.close()
        if browser is not None:
            with suppress(Exception):
                browser.close()
        proof["elapsed_seconds"] = round(time.monotonic() - started, 2)
        proof["browser"] = {
            "headless": True,
            "console_counts": {
                origin: activity.console_counts
                for origin, activity in zip(
                    (COACH_ORIGIN, ADMIN_ORIGIN, LEARNER_ORIGIN), activities, strict=False
                )
            },
            "blocked_request_count": sum(len(activity.blocked) for activity in activities),
        }
        _write_proof(output, proof)
    print(json.dumps({"status": proof["status"], "output": str(output)}))
    return 0 if proof["status"] == "passed" else 1


if __name__ == "__main__":
    sys.exit(main())
