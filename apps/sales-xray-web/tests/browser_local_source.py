"""Bounded private-source playback check; never screenshots or uploads source data."""
from __future__ import annotations

import argparse
import json
import time
from pathlib import Path
from urllib.parse import urlparse

from playwright.sync_api import expect, sync_playwright


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--url", default="http://127.0.0.1:8016")
    parser.add_argument("--checkpoint", required=True, type=Path)
    parser.add_argument("--audio", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--browser-executable", required=True)
    args = parser.parse_args()
    assert urlparse(args.url).hostname in {"localhost", "127.0.0.1"}
    receipt = {"status": "running", "started_unix": time.time(), "screenshots_taken": False,
               "source_uploaded": False, "paid_calls": 0, "stage": "start"}
    requests = []
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True, executable_path=args.browser_executable)
        context = browser.new_context(viewport={"width": 1280, "height": 900})
        page = context.new_page()
        page.on("request", lambda request: requests.append((request.method, request.url)))
        try:
            page.goto(args.url)
            page.wait_for_load_state("networkidle")
            expect(page.get_by_text("SYNTHETIC EXAMPLE", exact=True)).to_be_visible()
            boundary = len(requests)
            receipt["stage"] = "checkpoint_import"
            page.get_by_label("Open local checkpoint JSON", exact=True).set_input_files(args.checkpoint)
            expect(page.get_by_role("heading", name="Local audio · acoustic checkpoint")).to_be_visible()
            expect(page.get_by_role("heading", name="Acoustics ready. Transcript unavailable.")).to_be_visible()
            receipt["checkpoint_imported"] = True
            receipt["measurement_series"] = page.locator(".channel").count()
            receipt["stage"] = "source_hash_match"
            page.get_by_label("Choose matching local audio", exact=True).set_input_files(args.audio)
            expect(page.get_by_text("Source SHA-256 matched.", exact=False)).to_be_visible(timeout=30000)
            receipt["source_hash_matched"] = True
            receipt["stage"] = "local_codec_playback"
            page.get_by_role("button", name="Workbench", exact=True).click()
            page.locator("audio").evaluate("audio => audio.play()")
            page.wait_for_function("document.querySelector('audio').currentTime > 0.05", timeout=15000)
            page.locator("audio").evaluate("audio => audio.pause()")
            receipt["playback_advanced"] = True
            receipt["stage"] = "network_privacy"
            assert all(method == "GET" and url.startswith("blob:") for method, url in requests[boundary:])
            assert page.evaluate("Object.keys(localStorage).length === 0")
            receipt["only_blob_requests_after_import"] = True
            receipt["no_local_storage"] = True
            page.get_by_role("button", name="Session library", exact=True).click()
            page.get_by_role("button", name="Clear local session data").click()
            receipt["local_session_cleared"] = True
            receipt["status"] = "passed"
            receipt["stage"] = "complete"
        except Exception:
            # Avoid exception strings, screenshots, media names and browser DOM
            # dumps: the receipt records only which bounded check failed.
            receipt["status"] = "failed"
        finally:
            context.close()
            browser.close()
            receipt["finished_unix"] = time.time()
            args.output.write_text(json.dumps(receipt, indent=2), encoding="utf-8")
    print(json.dumps(receipt))
    return 0 if receipt["status"] == "passed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
