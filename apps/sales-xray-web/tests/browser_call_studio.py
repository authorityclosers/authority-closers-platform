"""Mocked browser contract for the CallStudio upload-to-report flow.

This script uses a Playwright-owned headless browser and intercepts only the
localhost conversation API. It never contacts a provider or sends source bytes
outside the page route mock. The receipt records request metadata and byte
counts, never request bodies or page error text.
"""

from __future__ import annotations

import argparse
import hashlib
import io
import json
import struct
import time
import wave
from pathlib import Path
from urllib.parse import urlparse

from playwright.sync_api import expect, sync_playwright


def synthetic_wav(seconds: int = 4, sample_rate: int = 16_000) -> bytes:
    stream = io.BytesIO()
    samples = [0] * (sample_rate * seconds)
    with wave.open(stream, "wb") as output:
        output.setnchannels(1)
        output.setsampwidth(2)
        output.setframerate(sample_rate)
        output.writeframes(struct.pack("<" + "h" * len(samples), *samples))
    return stream.getvalue()


def report(source_sha256: str) -> dict:
    citation = {"doc": "Doc-1", "sections": ["source section"]}
    return {
        "summary": "The prospect asked for a clear next step.",
        "strengths": [
            {
                "title": "You clarified the decision",
                "explanation": "The call ended with a concrete next step.",
                "evidence": [
                    {
                        "segment_id": "s1",
                        "start_ms": 1500,
                        "end_ms": 2200,
                        "quote": "Let us agree on the next step.",
                    }
                ],
            }
        ],
        "missed_opportunities": [],
        "improvements": [
            {
                "title": "Name the objection earlier",
                "explanation": "Surface the concern before presenting another feature.",
                "evidence": [
                    {
                        "segment_id": "s2",
                        "start_ms": 2500,
                        "end_ms": 3200,
                        "quote": "What would make this useful?",
                    }
                ],
            }
        ],
        "objection_analysis": [
            {
                "title": "The concern was acknowledged",
                "explanation": "The seller recognized the question before moving on.",
                "evidence": [
                    {
                        "segment_id": "s2",
                        "start_ms": 2500,
                        "end_ms": 3200,
                        "quote": "What would make this useful?",
                    }
                ],
            }
        ],
        "closing_analysis": [
            {
                "title": "A next step was named",
                "explanation": "The call ended with a clear follow-up action.",
                "evidence": [
                    {
                        "segment_id": "s1",
                        "start_ms": 1500,
                        "end_ms": 2200,
                        "quote": "Let us agree on the next step.",
                    }
                ],
            }
        ],
        "verdict": "Keep the direct close and ask one earlier diagnostic question.",
        "review_status": "draft_not_dipak_adjudicated",
        "source_label": "Server-derived source-bound draft",
        "source_sha256": source_sha256,
        "transcript_revision": "scribe-test-r1",
        "dimensions": [
            {
                "dimension_id": f"dimension-{index}",
                "label": f"Dimension {index}",
                "status": "unknown",
                "observation": "There is not enough evidence for a client-side conclusion.",
                "citations": [citation],
            }
            for index in range(1, 9)
        ],
        "report_sections": [
            {
                "number": number,
                "title": f"Report section {number}",
                "required": "Keep this section grounded in the call.",
                "citations": [citation],
            }
            for number in range(1, 10)
        ],
    }


def run() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--url", default="http://127.0.0.1:8016")
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--browser-executable")
    args = parser.parse_args()
    assert urlparse(args.url).hostname in {"127.0.0.1", "localhost"}
    args.output.parent.mkdir(parents=True, exist_ok=True)

    audio = synthetic_wav()
    source_sha256 = hashlib.sha256(audio).hexdigest()
    receipt: dict = {
        "status": "running",
        "started_unix": time.time(),
        "route_mocks": True,
        "provider_calls": 0,
        "external_request_count": 0,
        "external_source_bytes": 0,
        "mocked_source_bytes": 0,
        "checks": [],
        "api_sequence": [],
        "failure_stage": None,
    }
    upload_attempts = 0
    api_requests: list[dict] = []
    all_requests: list[dict[str, str]] = []

    def fulfill(route, payload: dict, status: int = 200) -> None:
        route.fulfill(
            status=status,
            content_type="application/json",
            body=json.dumps(payload, ensure_ascii=False),
        )

    def handle_api(route) -> None:
        nonlocal upload_attempts
        request = route.request
        path = urlparse(request.url).path
        method = request.method
        entry = {"method": method, "path": path}
        api_requests.append(entry)
        receipt["api_sequence"].append(entry)
        if path.endswith("/workspace") and method == "GET":
            fulfill(
                route,
                {
                    "intake_enabled": True,
                    "authenticated": True,
                    "sign_in_url": None,
                    "message": "Ready for a synthetic call.",
                },
            )
            return
        if path.endswith("/recordings") and method == "GET":
            fulfill(route, {"recordings": []})
            return
        if path.endswith("/intake/quote") and method == "POST":
            assert path == "/v1/conversation/intake/quote"
            assert request.headers.get("content-type") == "application/json"
            assert request.headers.get("idempotency-key")
            body = json.loads(request.post_data or "{}")
            assert body == {
                "source_sha256": source_sha256,
                "source_bytes": len(audio),
                "content_type": "audio/wav",
                "duration_ms": 4000,
                "purpose": "internal_analysis",
            }
            entry["idempotency_key_present"] = True
            entry["body_shape"] = sorted(body)
            fulfill(
                route,
                {
                    "id": "quote-1",
                    "recording_id": "recording-1",
                    "source_revision": "source-1",
                    "recipe_revision": "dipak-report-v1",
                    "cost_label": "No charge in this test workspace",
                    "privacy_summary": "Synthetic review data stays within the approved workspace.",
                    "providers": ["synthetic-review"],
                    "expires_at": "2099-01-01T00:00:00Z",
                    "quote_fingerprint": "f" * 64,
                    "privacy_revision": "privacy-1",
                    "output_kind": "measurements",
                },
            )
            return
        if path.endswith("/quotes/quote-1/approve") and method == "POST":
            assert path == "/v1/conversation/quotes/quote-1/approve"
            assert request.headers.get("content-type") == "application/json"
            body = json.loads(request.post_data or "{}")
            assert body == {
                "quote_fingerprint": "f" * 64,
                "privacy_revision": "privacy-1",
                "accepted": True,
            }
            entry["body_shape"] = sorted(body)
            fulfill(route, {"accepted": True})
            return
        if path.endswith("/recordings/recording-1/source") and method == "PUT":
            assert path == "/v1/conversation/recordings/recording-1/source"
            assert request.headers.get("content-type") == "application/octet-stream"
            assert request.headers.get("x-analysis-quote") == "quote-1"
            upload_attempts += 1
            body = request.post_data_buffer or b""
            receipt["mocked_source_bytes"] = len(body)
            entry.update(
                {
                    "bytes": len(body),
                    "content_type": request.headers.get("content-type"),
                    "quote_header": request.headers.get("x-analysis-quote"),
                }
            )
            assert body == audio
            if upload_attempts == 1:
                fulfill(route, {"detail": "synthetic_upload_failure"}, status=422)
            else:
                fulfill(route, {"accepted": True})
            return
        if path.endswith("/runs") and method == "POST":
            assert path == "/v1/conversation/runs"
            assert request.headers.get("content-type") == "application/json"
            assert request.headers.get("idempotency-key")
            body = json.loads(request.post_data or "{}")
            assert body == {
                "recording_id": "recording-1",
                "source_revision": "source-1",
                "quote_id": "quote-1",
                "recipe_revision": "dipak-report-v1",
            }
            entry["idempotency_key_present"] = True
            entry["body_shape"] = sorted(body)
            fulfill(route, {"id": "run-1", "state": "running", "message": "Queued for analysis."})
            return
        if path.endswith("/recordings/recording-1/transcript") and method == "GET":
            fulfill(
                route,
                {
                    "source_sha256": source_sha256,
                    "revision": "scribe-test-r1",
                    "timebase_id": "1ms",
                    "duration_ms": 4000,
                    "segments": [
                        {
                            "id": "s1",
                            "speaker_id": "speaker-1",
                            "start_ms": 1000,
                            "end_ms": 2200,
                            "text": "Let us agree on the next step.",
                        },
                        {
                            "id": "s2",
                            "speaker_id": "speaker-2",
                            "start_ms": 2500,
                            "end_ms": 3200,
                            "text": "What would make this useful?",
                        },
                    ],
                },
            )
            return
        if path.endswith("/runs/run-1/report") and method == "GET":
            fulfill(
                route,
                {
                    "id": "run-1",
                    "recording_id": "recording-1",
                    "state": "completed",
                    "message": "Report ready.",
                    "report": report(source_sha256),
                },
            )
            return
        raise AssertionError(f"unexpected mocked route: {method} {path}")

    def guard_non_local(route) -> None:
        url = route.request.url
        hostname = urlparse(url).hostname
        if url.startswith("blob:") or hostname in {"127.0.0.1", "localhost"}:
            route.continue_()
            return
        receipt["external_request_count"] += 1
        route.abort()

    stage = "start"
    try:
        with sync_playwright() as playwright:
            launch = {"headless": True}
            if args.browser_executable:
                launch["executable_path"] = args.browser_executable
            browser = playwright.chromium.launch(**launch)
            context = browser.new_context(
                viewport={"width": 1440, "height": 1000},
                reduced_motion="reduce",
                accept_downloads=False,
            )
            page = context.new_page()
            page.on(
                "request",
                lambda request: all_requests.append({"method": request.method, "url": request.url}),
            )
            page.route("**/*", guard_non_local)
            page.route("**/v1/conversation/**", handle_api)
            try:
                stage = "initial_workspace"
                response = page.goto(args.url)
                assert response is not None and response.status == 200
                page.wait_for_load_state("networkidle")
                expect(
                    page.get_by_role("heading", name="Start with your sales call")
                ).to_be_visible()

                stage = "source_selection_and_change"
                stage = "source_first_selected"
                page.get_by_label("Choose sales call audio", exact=True).set_input_files(
                    {"name": "first.wav", "mimeType": "audio/wav", "buffer": audio}
                )
                expect(
                    page.get_by_text("Selecting a file does not upload it.", exact=False)
                ).to_be_visible()
                expect(page.get_by_role("button", name="Continue to analysis")).to_be_enabled(
                    timeout=5000
                )
                stage = "source_changed"
                page.get_by_label("Choose sales call audio", exact=True).set_input_files(
                    {"name": "replacement.wav", "mimeType": "audio/wav", "buffer": audio}
                )
                expect(page.get_by_role("heading", name="replacement.wav")).to_be_visible()
                stage = "source_change_cleared_quote"
                expect(page.get_by_text("Ready to analyze", exact=True)).to_have_count(0)
                assert [item["path"] for item in api_requests] == ["/v1/conversation/workspace"]
                receipt["checks"].append("source_selection_and_change_stays_local")

                stage = "quote_and_permission_gate"
                page.get_by_role("button", name="Continue to analysis").click()
                expect(page.get_by_text("Ready to analyze", exact=True)).to_be_visible()
                expect(page.get_by_role("button", name="Analyze my call")).to_be_disabled()
                assert not any(item["method"] == "PUT" for item in api_requests)
                page.get_by_role("checkbox").check()
                assert not any(item["path"].endswith("/approve") for item in api_requests)
                receipt["checks"].append("quote_and_permission_required_before_upload")

                stage = "upload_failure_and_retry"
                stage = "upload_first_click"
                page.get_by_role("button", name="Analyze my call").click()
                stage = "upload_error_visible"
                page.wait_for_timeout(250)
                expect(page.locator(".notice.error[role=alert]")).to_contain_text(
                    "synthetic_upload_failure"
                )
                stage = "no_fake_report_after_failure"
                expect(page.get_by_text("Your sales call report", exact=True)).to_have_count(0)
                stage = "retry_button_available"
                expect(page.get_by_role("button", name="Analyze my call")).to_be_enabled()
                stage = "upload_retry_click"
                page.get_by_role("button", name="Analyze my call").click()
                stage = "job_started_after_retry"
                expect(page.get_by_text("Your call is being processed", exact=True)).to_be_visible()
                receipt["checks"].append("failed_upload_can_retry_without_fake_report")

                stage = "report_poll_and_evidence_seek"
                page.wait_for_timeout(3000)
                report_region = page.get_by_role("region", name="Sales call report")
                expect(report_region).to_be_visible(timeout=5000)
                expect(report_region).to_contain_text("The prospect asked for a clear next step.")
                expect(report_region).to_contain_text("Name the objection earlier")
                expect(report_region).not_to_contain_text("AI draft · Dipak has not reviewed this")
                expect(report_region).to_contain_text(
                    "Review status: draft; Dipak has not adjudicated this report."
                )
                expect(report_region).not_to_contain_text("draft_not_dipak_adjudicated")
                report_region.get_by_role("button", name="00:01–00:02").first.click()
                current_time = page.locator("audio").evaluate("element => element.currentTime")
                assert abs(float(current_time) - 1.5) < 0.05
                receipt["checks"].append("report_poll_and_evidence_seeks_local_audio")

                stage = "privacy_and_network_boundary"
                assert page.evaluate("Object.keys(localStorage).length") == 0
                assert page.evaluate("Object.keys(sessionStorage).length") == 0
                assert receipt["mocked_source_bytes"] == len(audio)
                assert receipt["external_source_bytes"] == 0
                assert receipt["external_request_count"] == 0
                assert upload_attempts == 2
                approval_index = next(
                    index
                    for index, item in enumerate(api_requests)
                    if item["path"].endswith("/quotes/quote-1/approve")
                )
                upload_index = next(
                    index
                    for index, item in enumerate(api_requests)
                    if item["path"].endswith("/recordings/recording-1/source")
                )
                assert approval_index < upload_index
                assert all(
                    urlparse(request["url"]).hostname in {"127.0.0.1", "localhost"}
                    or request["url"].startswith("blob:")
                    for request in all_requests
                )
                receipt["checks"].append("no_persistent_source_data_or_external_provider_request")
                receipt["status"] = "passed"
            finally:
                context.close()
                browser.close()
    except Exception:
        receipt["status"] = "failed"
        receipt["failure_stage"] = stage
    finally:
        receipt["finished_unix"] = time.time()
        args.output.write_text(json.dumps(receipt, indent=2), encoding="utf-8")
    return 0 if receipt["status"] == "passed" else 1


if __name__ == "__main__":
    raise SystemExit(run())
