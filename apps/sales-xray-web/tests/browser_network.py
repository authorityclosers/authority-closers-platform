"""Browser/network receipt for the standalone app against the real AC example API.

No page.route, response interception or recorded customer data. Start the app with
AC_CONVERSATION_API_ORIGIN=http://127.0.0.1:8016 and the actual ASGI API first.
All audio/checkpoint input below is generated synthetic test data in memory.
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


def synthetic_audio() -> bytes:
    content = io.BytesIO()
    with wave.open(content, "wb") as output:
        output.setnchannels(1)
        output.setsampwidth(2)
        output.setframerate(16000)
        output.writeframes(struct.pack("<16000h", *([0] * 16000)))
    return content.getvalue()


def checkpoint(audio: bytes) -> dict:
    sha = hashlib.sha256(audio).hexdigest()
    feature_sha = "b" * 64
    return {
        "schema": "ac.sales-xray.signal-checkpoint/1", "stage": "C1",
        "source_sha256": sha, "feature_sha256": feature_sha,
        "source_rate": 16000, "source_channels": 1, "source_codec": "pcm_s16le",
        "acoustics": {"format": "ac.audioatlas.features/1", "rate": 16000,
            "channels": 1, "sample_count": 16000, "rows": 100,
            "window_samples": 640, "hop_samples": 160,
            "source_sha256": sha, "feature_sha256": feature_sha},
        "timebase": {"clock": "decoded_audio_track", "rate": 16000,
            "source_track_start_seconds": 0, "source_track_time_base": "1/16000",
            "source_mapping_status": "uncertified_codec_delay_origin_and_discontinuities",
            "container_video_sync_certified": False},
        "display": {"channels": [{"channel": 0, "time_s": [0, .1, .2],
            "dbfs": [-20, None, -21], "f0_hz": [None, None, None], "display_stride": 10}]},
    }


def run() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--url", default="http://127.0.0.1:3016")
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--browser-executable")
    args = parser.parse_args()
    assert urlparse(args.url).hostname in {"127.0.0.1", "localhost"}
    args.output.mkdir(parents=True, exist_ok=True)
    receipt = {"started_unix": time.time(), "app_origin": args.url,
               "fixture_kind": "generated_synthetic_only", "route_mocks": False,
               "checks": [], "requests": [], "page_errors": [], "status": "running"}
    with sync_playwright() as p:
        launch = {"headless": True}
        if args.browser_executable:
            launch["executable_path"] = args.browser_executable
        browser = p.chromium.launch(**launch)
        context = browser.new_context(viewport={"width": 1440, "height": 1100}, reduced_motion="reduce", accept_downloads=True)
        page = context.new_page()
        page.on("request", lambda request: receipt["requests"].append({"method": request.method, "url": request.url}))
        page.on("pageerror", lambda error: receipt["page_errors"].append(str(error)))
        try:
            response = page.goto(args.url)
            assert response is not None and response.status == 200
            page.wait_for_load_state("networkidle")
            expect(page.get_by_role("heading", name="A conversation about the next step")).to_be_visible()
            expect(page.get_by_text("SYNTHETIC EXAMPLE", exact=True)).to_be_visible()
            assert any("/v1/conversation/example" in r["url"] for r in receipt["requests"])
            assert any("/v1/conversation/capabilities" in r["url"] for r in receipt["requests"])
            receipt["checks"].append("real_http_example_and_capabilities")
            page.screenshot(path=str(args.output / "sales-xray-desktop.png"), full_page=True)

            page.get_by_role("searchbox", name="Search transcript").fill("discount")
            expect(page.locator(".transcript-row")).to_have_count(1)
            page.locator(".transcript-row").click()
            expect(page.locator(".focus-panel blockquote")).to_contain_text("discount")
            page.get_by_role("searchbox", name="Search transcript").fill("not-in-this-script")
            expect(page.get_by_text("No matching evidence.", exact=False)).to_be_visible()
            page.get_by_role("searchbox", name="Search transcript").fill("")
            receipt["checks"].append("transcript_search_evidence_selection_empty_result")

            page.get_by_role("button", name="Review notes", exact=True).click()
            page.get_by_role("button", name="Measurement & attribution", exact=False).click()
            page.get_by_label("Proposed correction", exact=True).fill("Synthetic reproduction: verify the attribution on this selected span.")
            page.get_by_role("button", name="Prepare local proposal").click()
            with page.expect_download() as event:
                page.get_by_role("link", name="Download JSON").click()
            download = event.value
            proposal = json.loads(Path(download.path()).read_text(encoding="utf-8"))
            assert proposal["state"] == "local_unsubmitted_proposal" and proposal["submitted"] is False
            assert proposal["reviewer_identity"] is None and proposal["lane"] == "measurements"
            assert proposal["run_id"] == "synthetic-example-v1" and proposal["segment_id"] == "u4"
            page.get_by_label("Proposed correction", exact=True).fill("A changed correction invalidates the prepared export.")
            expect(page.get_by_role("link", name="Download JSON")).to_have_count(0)
            page.get_by_role("button", name="Source & evidence", exact=True).click()
            page.get_by_role("button", name="Review notes", exact=True).click()
            expect(page.get_by_label("Proposed correction", exact=True)).to_have_value("A changed correction invalidates the prepared export.")
            receipt["checks"].append("local_review_export_revision_and_lane_no_submission_edit_invalidates_export")

            page.get_by_role("button", name="Source & evidence", exact=True).click()
            expect(page.locator(".weight-comparison")).to_contain_text("95")
            expect(page.locator(".weight-comparison")).to_contain_text("100")
            expect(page.get_by_text("Numeric publication is withheld", exact=False)).to_be_visible()
            receipt["checks"].append("unresolved_95_100_discrepancy_preserved")

            audio = synthetic_audio()
            native = checkpoint(audio)
            request_boundary = len(receipt["requests"])
            page.get_by_label("Open local checkpoint JSON", exact=True).set_input_files({"name": "synthetic-c1.json", "mimeType": "application/json", "buffer": json.dumps(native).encode()})
            expect(page.get_by_role("heading", name="Local audio · acoustic checkpoint")).to_be_visible()
            expect(page.get_by_role("heading", name="Acoustics ready. Transcript unavailable.")).to_be_visible()
            expect(page.get_by_text("Uncertified", exact=True)).to_be_visible()
            expect(page.get_by_text("No usable values in this channel.", exact=False)).to_be_visible()
            page.get_by_label("Choose matching local audio", exact=True).set_input_files({"name": "synthetic.wav", "mimeType": "audio/wav", "buffer": audio})
            expect(page.get_by_text("Source SHA-256 matched.", exact=False)).to_be_visible()
            expect(page.locator("audio")).to_have_count(1)
            page.locator("audio").evaluate("audio => audio.play()")
            page.wait_for_function("document.querySelector('audio').currentTime > 0")
            page.locator("audio").evaluate("audio => audio.pause()")
            page.screenshot(path=str(args.output / "sales-xray-synthetic-c1.png"), full_page=True)
            receipt["checks"].append("native_c1_import_nulls_clocks_and_sha_matched_local_playback")

            page.get_by_role("button", name="Review notes", exact=True).click()
            page.get_by_label("Proposed correction", exact=True).fill("Synthetic reproduction: inspect the unavailable level window.")
            expect(page.get_by_role("button", name="Prepare local proposal")).to_be_disabled()
            page.get_by_label("Measurement series", exact=True).select_option("0")
            expect(page.get_by_role("button", name="Prepare local proposal")).to_be_disabled()
            page.get_by_label("Exact measurement point", exact=True).select_option("1")
            page.get_by_role("button", name="Prepare local proposal").click()
            with page.expect_download() as event:
                page.get_by_role("link", name="Download JSON").click()
            measurement_proposal = json.loads(Path(event.value.path()).read_text(encoding="utf-8"))
            assert measurement_proposal["anchor"]["physical_channel_index"] == 0
            assert measurement_proposal["anchor"]["time_ms"] == 100
            assert measurement_proposal["anchor"]["value"] is None
            assert measurement_proposal["anchor"]["window_ms"] == 40
            assert measurement_proposal["anchor"]["hop_ms"] == 10
            assert measurement_proposal["anchor"]["measurement_revision"] == "b" * 64
            assert measurement_proposal["source_evidence"]["source_sha256"] == hashlib.sha256(audio).hexdigest()
            assert measurement_proposal["source_evidence"]["audio_sha256_matched"] is True
            assert measurement_proposal["source_evidence"]["feature_binary_verified"] is False
            assert measurement_proposal["transcript_revision"] is None and measurement_proposal["segment_id"] is None
            assert measurement_proposal["reviewer_identity"] is None and measurement_proposal["submitted"] is False
            page.evaluate("window.scrollTo(0, 0)")
            page.screenshot(path=str(args.output / "sales-xray-measurement-review.png"), full_page=True)
            page.get_by_role("button", name="Workbench", exact=True).click()
            receipt["checks"].append("typed_measurement_anchor_explicit_point_revision_profile_source_proof_no_transcript_invention")

            conflict = json.loads(json.dumps(native))
            conflict["display"]["channels"][0]["dbfs"][0] = -1
            page.get_by_label("Open local checkpoint JSON", exact=True).set_input_files({"name": "conflicting-revision.json", "mimeType": "application/json", "buffer": json.dumps(conflict).encode()})
            expect(page.locator('.notice[role="alert"]')).to_contain_text("new immutable revision")
            expect(page.locator("audio")).to_have_count(1)
            receipt["checks"].append("same_revision_conflict_preserves_original_checkpoint_and_audio")

            page.get_by_label("Choose matching local audio", exact=True).set_input_files({"name": "wrong-source.wav", "mimeType": "audio/wav", "buffer": audio + b"wrong"})
            expect(page.get_by_text("This audio does not match", exact=False)).to_be_visible()
            expect(page.locator("audio")).to_have_count(0)
            page.get_by_label("Open local checkpoint JSON", exact=True).set_input_files({"name": "bad.json", "mimeType": "application/json", "buffer": b'{"schema":"unknown"}'})
            expect(page.locator('.notice[role="alert"]')).to_contain_text("Use a Sales Xray checkpoint")
            expect(page.get_by_role("heading", name="Local audio · acoustic checkpoint")).to_be_visible()
            new_requests = receipt["requests"][request_boundary:]
            assert all(r["url"].startswith("blob:") for r in new_requests), new_requests
            receipt["checks"].append("wrong_source_rejected_invalid_import_preserves_current_no_file_network_transfer")

            page.get_by_role("button", name="Session library", exact=False).click()
            page.get_by_role("button", name="Clear local session data").click()
            expect(page.locator(".library-row")).to_have_count(1)
            page.locator(".library-row").click()
            page.reload()
            page.wait_for_load_state("networkidle")
            expect(page.get_by_role("heading", name="A conversation about the next step")).to_be_visible()
            page.get_by_role("button", name="Switch to dark appearance").click()
            expect(page.locator(".xray-app")).to_have_attribute("data-theme", "dark")
            page.screenshot(path=str(args.output / "sales-xray-dark.png"), full_page=True)
            page.get_by_role("button", name="Switch to light appearance").click()
            page.set_viewport_size({"width": 390, "height": 844})
            page.screenshot(path=str(args.output / "sales-xray-mobile.png"), full_page=True)
            assert page.evaluate("document.documentElement.scrollWidth <= window.innerWidth"), "horizontal overflow"
            assert page.evaluate("Object.keys(localStorage).length === 0"), "unexpected local persistence"
            page.reload()
            page.wait_for_load_state("networkidle")
            page.keyboard.press("Tab")
            expect(page.get_by_role("link", name="Skip to conversation")).to_be_focused()
            receipt["checks"].append("session_clear_light_dark_mobile_reflow_reduced_motion_keyboard_no_local_storage")
            assert not receipt["page_errors"], receipt["page_errors"]
            assert all(r["method"] == "GET" for r in receipt["requests"]), "unexpected mutation"
            assert all(r["url"].startswith("blob:") or urlparse(r["url"]).hostname in {"127.0.0.1", "localhost"} for r in receipt["requests"]), "unexpected external request"
            receipt["status"] = "passed"
        except Exception as error:
            receipt["status"] = "failed"
            receipt["failure"] = str(error)
            page.screenshot(path=str(args.output / "sales-xray-failure.png"), full_page=True)
            raise
        finally:
            receipt["finished_unix"] = time.time()
            (args.output / "browser-network.json").write_text(json.dumps(receipt, indent=2), encoding="utf-8")
            context.close()
            browser.close()


if __name__ == "__main__":
    run()
