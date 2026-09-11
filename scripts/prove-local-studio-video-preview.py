"""Actual local Coach upload and private preview. No publication or learner grants.

Only the existing disposable synthetic course and the licensed 12-second fixture
are accepted. This is not proof of the full-length 4K course or large uploads.
Credentials exist only in process memory and normal sign-in form fields.
"""

from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import os
import re
import time
from datetime import UTC, datetime
from pathlib import Path
from urllib.parse import urlsplit

from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location(
    "upload_proof", ROOT / "scripts" / "prove-local-studio-video-upload.py"
)
assert spec and spec.loader
shared = importlib.util.module_from_spec(spec)
spec.loader.exec_module(shared)

_UUID_PATH = r"[0-9a-f]{8}-[0-9a-f]{4}-[1-8][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}"
_VIDEO_METADATA_READY = "v => v.readyState >= 1 && v.videoWidth > 0"
_VIDEO_PLAYED = "v => v.currentTime > 1"
_VIDEO_SEEKED = "(v,t) => !v.seeking && v.currentTime >= t && v.readyState >= 2"


def _request_decision(
    url: str,
    method: str,
    *,
    coach_origin: str,
    permitted_upload: re.Pattern[str],
) -> tuple[bool, str | None]:
    """Return whether a browser request may proceed and, if denied, its kind."""
    parsed = urlsplit(url)
    request_origin = f"{parsed.scheme}://{parsed.netloc}"
    normalized_method = method.upper()
    if request_origin != coach_origin:
        return False, "external"
    if (
        normalized_method in {"GET", "HEAD"}
        or (normalized_method, parsed.path) in shared.ALLOWED_AUTH_WRITES
        or (normalized_method in {"POST", "PUT"} and permitted_upload.fullmatch(parsed.path))
    ):
        return True, None
    return False, "blocked_write"


def _sanitized_request_record(url: str, method: str, kind: str) -> dict[str, str]:
    """Keep denial evidence useful without persisting query strings or credentials."""
    parsed = urlsplit(url)
    return {"kind": kind, "method": method.upper(), "path": parsed.path or "/"}


def _preview_response_kind(path: str, prefix: str) -> str | None:
    if re.fullmatch(
        rf"{re.escape(prefix)}/videos/{_UUID_PATH}/versions/{_UUID_PATH}/preview",
        path,
        flags=re.IGNORECASE,
    ):
        return "descriptor"
    if re.fullmatch(
        rf"{re.escape(prefix)}/videos/{_UUID_PATH}/versions/{_UUID_PATH}/preview/bytes",
        path,
        flags=re.IGNORECASE,
    ):
        return "bytes"
    return None


def _preview_response_record(response, prefix: str) -> dict[str, object] | None:
    parsed = urlsplit(response.url)
    if "/preview" not in parsed.path:
        return None
    kind = (
        _preview_response_kind(parsed.path, prefix)
        if not parsed.query and not parsed.fragment
        else None
    )
    headers = response.headers
    return {
        "kind": kind or "unexpected_preview",
        "method": response.request.method.upper(),
        "path": parsed.path or "/",
        "status": int(response.status),
        "content_type": headers.get("content-type"),
        "content_length": headers.get("content-length"),
        "content_range": headers.get("content-range"),
        "accept_ranges": headers.get("accept-ranges"),
        "cache_control": headers.get("cache-control"),
    }


def _media_type(value: object) -> str:
    return str(value or "").split(";", 1)[0].strip().lower()


def _assert_preview_responses(responses: list[dict[str, object]]) -> None:
    if any(item.get("kind") == "unexpected_preview" for item in responses):
        raise shared.ProofFailure("requests", "unexpected_preview_response_path")
    descriptors = [item for item in responses if item.get("kind") == "descriptor"]
    bytes_responses = [item for item in responses if item.get("kind") == "bytes"]
    if not descriptors or not any(item.get("status") == 200 for item in descriptors):
        raise shared.ProofFailure("requests", "preview_descriptor_response_missing")
    if not bytes_responses or not any(item.get("status") in {200, 206} for item in bytes_responses):
        raise shared.ProofFailure("requests", "preview_bytes_response_missing")
    if any(item.get("status") != 200 for item in descriptors):
        raise shared.ProofFailure("requests", "preview_descriptor_status_invalid")
    if any(item.get("status") not in {200, 206} for item in bytes_responses):
        raise shared.ProofFailure("requests", "preview_bytes_status_invalid")
    for item in responses:
        if "no-store" not in str(item.get("cache_control") or "").lower():
            raise shared.ProofFailure("requests", "private_cache_policy_missing")
    for item in descriptors:
        if item.get("status") == 200 and _media_type(item.get("content_type")) != (
            "application/json"
        ):
            raise shared.ProofFailure("requests", "preview_descriptor_content_type_invalid")
    for item in bytes_responses:
        if item.get("status") not in {200, 206}:
            continue
        if _media_type(item.get("content_type")) != "video/mp4":
            raise shared.ProofFailure("requests", "preview_bytes_content_type_invalid")
        try:
            content_length = int(str(item.get("content_length")))
        except (TypeError, ValueError):
            raise shared.ProofFailure("requests", "preview_bytes_length_invalid") from None
        if not 1 <= content_length <= 8 * 1024**3:
            raise shared.ProofFailure("requests", "preview_bytes_length_invalid")
        if str(item.get("accept_ranges") or "").lower() != "bytes":
            raise shared.ProofFailure("requests", "preview_range_support_missing")
        if item.get("status") == 206 and not re.fullmatch(
            r"bytes \d+-\d+/\d+", str(item.get("content_range") or "")
        ):
            raise shared.ProofFailure("requests", "preview_content_range_invalid")


def _assert_network_scope(
    blocked_requests: list[dict[str, str]], external_requests: list[dict[str, str]]
) -> None:
    if external_requests:
        raise shared.ProofFailure("network_scope", "external_request_was_attempted")
    if blocked_requests:
        raise shared.ProofFailure("network_scope", "unapproved_write_was_attempted")


def _wait_for_video(
    page,
    video,
    predicate: str,
    *,
    timeout_ms: int,
    reason: str,
    arg: object | None = None,
) -> None:
    deadline = time.monotonic() + timeout_ms / 1000
    while time.monotonic() < deadline:
        ready = video.evaluate(predicate) if arg is None else video.evaluate(predicate, arg)
        if ready:
            return
        page.wait_for_timeout(100)
    raise shared.ProofFailure("preview", reason)


def main() -> int:
    argparse.ArgumentParser(description=__doc__).parse_args()
    sandbox = shared._load_sandbox()
    password = os.environ.get("AC_LOCAL_BROWSER_TEST_PASSWORD", "")
    if not password:
        raise RuntimeError("A transient local test password is required.")
    if not shared.FIXTURE.is_file() or shared.FIXTURE.stat().st_size != 14_538_778:
        raise RuntimeError("The exact licensed short test fixture is required.")
    with shared.FIXTURE.open("rb") as fixture:
        fixture_digest = hashlib.file_digest(fixture, "sha256").hexdigest()
    if fixture_digest != "7e7ee255d0ca2866ad528e9d6ddc0049a66883d6984ea9bf4d9fed188907bd4a":
        raise RuntimeError("The licensed short test fixture checksum has changed.")
    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%S%fZ")
    output = ROOT / ".tmp/local-platform/new/studio-video-preview" / stamp
    output.mkdir(parents=True, exist_ok=False)
    proof: dict = {
        "status": "incomplete",
        "environment": "local",
        "screenshots": [],
        "fixture": "licensed-bbb-12s",
        "fixture_sha256": fixture_digest,
        "not_full_length_course_proof": True,
    }
    stage = "login"
    responses: list[dict] = []
    upload_responses: list[dict] = []
    blocked_requests: list[dict[str, str]] = []
    external_requests: list[dict[str, str]] = []
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        activity = shared.BrowserActivity(
            browser, shared.COACH_ORIGIN, viewport={"width": 1440, "height": 1000}
        )
        page = activity.page
        prefix = f"/v1/admin/studio/programs/{sandbox['studio_program_id']}"
        permitted_upload = re.compile(
            re.escape(prefix) + r"/video-uploads(?:/[0-9a-f-]{36}/(?:bytes|complete))?$"
        )
        activity.context.unroute("**/*")

        def guard(route):
            request = route.request
            allowed, denied_kind = _request_decision(
                request.url,
                request.method,
                coach_origin=shared.COACH_ORIGIN,
                permitted_upload=permitted_upload,
            )
            if allowed:
                route.continue_()
            else:
                record = _sanitized_request_record(
                    request.url, request.method, denied_kind or "denied"
                )
                (external_requests if denied_kind == "external" else blocked_requests).append(
                    record
                )
                route.abort()

        def record(response):
            item = _preview_response_record(response, prefix)
            if item is not None:
                responses.append(item)
            upload_path = urlsplit(response.url).path
            if upload_path.startswith(prefix + "/video-uploads"):
                upload_responses.append(
                    {
                        "method": response.request.method,
                        "step": upload_path.rsplit("/", 1)[-1]
                        if upload_path.endswith(("/bytes", "/complete"))
                        else "intent",
                        "status": response.status,
                    }
                )

        activity.context.route("**/*", guard)
        page.on("response", record)
        try:
            shared._login_operations(
                activity,
                email="coach@ac.localhost",
                password=password,
                tenant_id=sandbox["academy_tenant_id"],
                destination="/studio",
                stage=stage,
            )
            stage = "editor"
            page.goto(shared.COACH_ORIGIN + f"/studio/programs/{sandbox['studio_program_id']}")
            page.wait_for_load_state("networkidle")
            stage = "upload"
            chooser = page.get_by_label("Choose a course video", exact=True)
            chooser.wait_for(state="attached", timeout=30_000)
            if chooser.is_disabled():
                raise shared.ProofFailure(stage, "upload_not_enabled")
            chooser.set_input_files(str(shared.FIXTURE))
            print("Normal Coach login complete; actual short fixture upload started.", flush=True)
            deadline = time.monotonic() + 600
            heading = page.get_by_role("heading", name="Your video is ready", exact=True)
            previous_stage = ""
            while time.monotonic() < deadline:
                if heading.count():
                    break
                for title in (
                    "Checking your file",
                    "Preparing a secure upload",
                    "Uploading your video",
                    "Checking the uploaded video",
                    "Preparing playback",
                    "This video couldn’t be processed",
                    "Let’s check your upload",
                    "Restore your editing access",
                    "Choose another video",
                    "Upload paused",
                    "This video is no longer available",
                ):
                    if page.get_by_role("heading", name=title, exact=True).count():
                        if title != previous_stage:
                            print(json.dumps({"upload_stage": title}), flush=True)
                            previous_stage = title
                        if title in {
                            "This video couldn’t be processed",
                            "Let’s check your upload",
                            "Restore your editing access",
                            "Choose another video",
                            "Upload paused",
                            "This video is no longer available",
                        }:
                            raise shared.ProofFailure(stage, "upload_needs_recovery")
                page.wait_for_timeout(1000)
            if not heading.count():
                raise shared.ProofFailure(stage, "ready_not_confirmed")
            print(
                "Upload and real processing confirmed ready; opening private preview.", flush=True
            )
            stage = "preview"
            panel = heading.locator("xpath=ancestor::section[1]")
            panel.get_by_role("button", name="Preview video", exact=True).click()
            video = panel.locator("video")
            video.wait_for(state="attached", timeout=30_000)
            if video.count() != 1:
                raise shared.ProofFailure(stage, "video_element_not_unique")
            _wait_for_video(
                page,
                video,
                _VIDEO_METADATA_READY,
                timeout_ms=30_000,
                reason="video_metadata_not_ready",
            )
            facts = video.evaluate(
                "v => ({width:v.videoWidth,height:v.videoHeight,duration:v.duration,"
                "controls:v.controls,autoplay:v.autoplay})"
            )
            if not (
                10 < facts["duration"] < 15
                and facts["width"] > 0
                and facts["controls"]
                and not facts["autoplay"]
            ):
                raise shared.ProofFailure(stage, "unexpected_actual_video_metadata")
            video.evaluate("async v => { v.muted=true; await v.play(); }")
            _wait_for_video(
                page,
                video,
                _VIDEO_PLAYED,
                timeout_ms=20_000,
                reason="video_playback_did_not_advance",
            )
            target = facts["duration"] * 0.65
            video.evaluate("(v,t) => {v.currentTime=t;}", target)
            _wait_for_video(
                page,
                video,
                _VIDEO_SEEKED,
                arg=target,
                timeout_ms=20_000,
                reason="video_seek_did_not_settle",
            )
            video.evaluate("v => v.pause()")
            proof["playback"] = {**facts, "played": True, "seeked": True}
            for width, height in [(1440, 1000), (390, 844)]:
                page.set_viewport_size({"width": width, "height": height})
                video.scroll_into_view_if_needed()
                page.wait_for_timeout(350)
                filename = f"coach-preview-{width}.png"
                page.screenshot(path=str(output / filename))
                proof["screenshots"].append(filename)
                if page.evaluate("document.documentElement.scrollWidth") > width:
                    raise shared.ProofFailure("layout", "horizontal_overflow")
            panel.get_by_role("button", name="Close video preview", exact=True).click()
            if panel.locator("video").count():
                raise shared.ProofFailure("close", "video_not_unloaded")
            _assert_network_scope(blocked_requests, external_requests)
            _assert_preview_responses(responses)
            proof.update(
                status="passed", normal_login=True, upload_processed=True, close_unloaded=True
            )
        except Exception as failure:
            proof["failure"] = {"stage": stage, "type": type(failure).__name__}
            if isinstance(failure, shared.ProofFailure):
                proof["failure"]["reason"] = str(failure)
            if urlsplit(page.url).path.startswith("/studio"):
                page.screenshot(path=str(output / "failure.png"), full_page=True)
                proof["screenshots"].append("failure.png")
        finally:
            proof["requests"] = responses
            proof["upload_requests"] = upload_responses
            proof["network_scope"] = {
                "external_count": len(external_requests),
                "blocked_count": len(blocked_requests),
                "denied_kinds": sorted(
                    {item["kind"] for item in [*external_requests, *blocked_requests]}
                ),
                "external_requests": external_requests,
                "blocked_requests": blocked_requests,
            }
            proof["javascript_errors"] = activity.console_counts.get("pageerror", 0)
            if proof["status"] == "passed" and (external_requests or blocked_requests):
                proof["status"] = "incomplete"
                proof["failure"] = {"stage": "network_scope", "reason": "denied_request"}
            if proof["javascript_errors"] and proof["status"] == "passed":
                proof["status"] = "incomplete"
                proof["failure"] = {"stage": "browser", "reason": "javascript_errors"}
            activity.close()
            browser.close()
            (output / "proof.json").write_text(json.dumps(proof, indent=2), encoding="utf-8")
    print(json.dumps({"status": proof["status"], "proof": str(output / "proof.json")}))
    return 0 if proof["status"] == "passed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
