"""Mounted-route and complete-report browser proof for the Sales Xray UX slice.

The API responses are bounded synthetic fixtures. No provider is called and no
private audio is used; the WAV is generated as four seconds of silence.
"""

import hashlib
import json
import os
import wave
from io import BytesIO
from pathlib import Path
from urllib.parse import urlparse

from playwright.sync_api import Page, sync_playwright

BASE_URL = os.environ.get("SALES_XRAY_BASE_URL", "http://127.0.0.1:3016")
AUDIT_DIR = Path(
    os.environ.get(
        "SALES_XRAY_UX_EVIDENCE_DIR",
        r"D:\AC-authority-closers-release-audit\sales-xray-measurement-ux-20260913",
    )
)
SOURCE_SHA = "00" * 32
CITATION = {"doc": "Doc-1", "sections": ["source section"]}
TRANSCRIPT = {
    "source_sha256": SOURCE_SHA,
    "revision": "scribe-browser-r1",
    "timebase_id": "1ms",
    "duration_ms": 4000,
    "segments": [
        {
            "id": "s1",
            "speaker_id": "speaker-1",
            "start_ms": 1000,
            "end_ms": 2200,
            "text": "कल follow-up करूया — next step तय करते हैं।",
        },
        {
            "id": "s2",
            "speaker_id": "speaker-2",
            "start_ms": 2500,
            "end_ms": 3200,
            "text": "हे useful कसे होईल? बजट ₹15,000 है।",
        },
    ],
}
REPORT = {
    "summary": "ग्राहकाने next step मान्य केला; exact time अभी तय नहीं है।",
    "strengths": [
        {
            "title": "You clarified the decision",
            "explanation": "The call ended with a concrete next step.",
            "evidence": [
                {
                    "segment_id": "s1",
                    "start_ms": 1500,
                    "end_ms": 2200,
                    "quote": "कल follow-up करूया — next step तय करते हैं।",
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
                    "quote": "हे useful कसे होईल? बजट ₹15,000 है।",
                }
            ],
        }
    ],
    "objection_analysis": [],
    "closing_analysis": [],
    "verdict": "Keep the direct close and ask one earlier diagnostic question.",
    "review_status": "draft_not_dipak_adjudicated",
    "source_label": "Server-derived source-bound draft",
    "source_sha256": SOURCE_SHA,
    "transcript_revision": "scribe-browser-r1",
    "dimensions": [
        {
            "dimension_id": f"dimension-{index}",
            "label": f"Dimension {index}",
            "status": "unknown",
            "observation": "There is not enough evidence for a client-side conclusion.",
            "citations": [CITATION],
        }
        for index in range(1, 9)
    ],
    "report_sections": [
        {
            "number": index,
            "title": f"Report section {index}",
            "required": "Keep this section grounded in the call.",
            "citations": [CITATION],
        }
        for index in range(1, 10)
    ],
}
RECORDING = {
    "id": "recording-1",
    "state": "completed",
    "source_revision": "source-1",
    "source_sha256": SOURCE_SHA,
    "source_bytes": 128,
    "content_type": "audio/wav",
    "created_at": "2026-09-13T00:00:00Z",
    "latest_run": {
        "id": "run-1",
        "state": "completed",
        "recipe_revision": "audioatlas-48000-v1",
        "provider_calls": 0,
        "has_report": True,
    },
    "has_report": True,
}


def silence_wav() -> bytes:
    buffer = BytesIO()
    with wave.open(buffer, "wb") as output:
        output.setnchannels(2)
        output.setsampwidth(2)
        output.setframerate(48000)
        output.writeframes(b"\x00\x00" * 48000 * 4 * 2)
    return buffer.getvalue()


def json_response(route, body, status=200):
    import json

    route.fulfill(
        status=status,
        content_type="application/json",
        body=json.dumps(body),
    )


def synthetic_measurements():
    source = {
        "recording_id": "recording-1",
        "source_sha256": SOURCE_SHA,
        "clock": "decoded_audio_track",
        "container_video_sync_certified": False,
        "source_rate": 48000,
        "decoded_rate": 16000,
        "physical_channels": 2,
        "duration_ms": 4000,
    }
    return {
        "schema": "ac.sales-xray.measurement-view/1",
        "availability": "available",
        "source": source,
        "checkpoint": {
            "stage": "C1",
            "cache_key": "ab" * 32,
            "manifest_sha256": "cd" * 32,
            "payload_sha256": "ef" * 32,
        },
        "audioatlas": {
            **source,
            "status": "available",
            "profile": "audioatlas-native-0.1-40ms-10ms",
            "window_ms": 40,
            "hop_ms": 10,
            "sample_count": 64000,
            "feature_sha256": "12" * 32,
            "channels": [
                {
                    "channel_index": channel_index,
                    "level": {
                        "status": "available",
                        "value": -18,
                        "unit": "dBFS",
                        "available_fraction": None,
                    },
                    "pitch": {
                        "status": "available",
                        "value": 190,
                        "unit": "Hz",
                        "available_fraction": 0.75,
                    },
                    "series": [
                        {
                            "measurement": kind,
                            "unit": unit,
                            "clock": "decoded_audio_track",
                            "window_ms": 40,
                            "hop_ms": 10,
                            "display_stride": 100,
                            "points": [
                                {"start_ms": index * 1000, "value": value}
                                for index, value in enumerate(values)
                            ],
                        }
                        for kind, unit, values in (
                            ("dbfs", "dBFS", [-20, -16, None, -18]),
                            ("f0_hz", "Hz", [180, 190, None, 210]),
                        )
                    ],
                }
                for channel_index in range(2)
            ],
        },
        "signallab": {
            "status": "unavailable",
            "reason": "source_inspected_adapter_not_implemented",
            "runtime_output": False,
        },
    }


def route_api(route) -> None:
    path = urlparse(route.request.url).path
    if path.endswith("/workspace"):
        json_response(
            route,
            {
                "intake_enabled": True,
                "authenticated": True,
                "sign_in_url": None,
                "message": "Synthetic QA workspace ready.",
            },
        )
    elif path.endswith("/recordings"):
        json_response(route, {"recordings": [RECORDING]})
    elif path.endswith("/runs/run-1/report"):
        json_response(
            route,
            {
                "id": "run-1",
                "recording_id": "recording-1",
                "recipe_revision": "audioatlas-48000-v1",
                "state": "completed",
                "message": "Saved report ready.",
                "provider_calls": 0,
                "report": REPORT,
            },
        )
    elif path.endswith("/recordings/recording-1/transcript"):
        json_response(route, TRANSCRIPT)
    elif path.endswith("/recordings/recording-1/source"):
        route.fulfill(status=200, content_type="audio/wav", body=silence_wav())
    elif path.endswith("/recordings/recording-1/plan"):
        json_response(route, {"detail": "No processing plan."}, status=404)
    elif path.endswith("/recordings/recording-1/measurements"):
        json_response(route, synthetic_measurements())
    else:
        route.continue_()


def workspace_route(route) -> None:
    json_response(
        route,
        {
            "person_id": "person-1",
            "session_id": "session-1",
            "selected_tenant_id": "tenant-1",
            "workspaces": [{"tenant_id": "tenant-1", "name": "Synthetic QA workspace"}],
        },
    )


def install_routes(page: Page) -> None:
    page.route("**/v1/me/workspaces", workspace_route)
    page.route("**/v1/conversation/**", route_api)
    page.add_init_script(
        """
        window.__playMode = 'resolve';
        window.__printCalls = 0;
        window.print = () => { window.__printCalls += 1; };
        Object.defineProperty(HTMLMediaElement.prototype, 'play', {
          configurable: true,
          value: function () {
            return window.__playMode === 'reject'
              ? Promise.reject(new DOMException('Synthetic blocked playback', 'NotAllowedError'))
              : Promise.resolve();
          }
        });
        window.__seekTimes = [];
        const currentTimeDescriptor = Object.getOwnPropertyDescriptor(
          HTMLMediaElement.prototype, 'currentTime'
        );
        Object.defineProperty(HTMLMediaElement.prototype, 'currentTime', {
          configurable: true,
          get: function () { return currentTimeDescriptor.get.call(this); },
          set: function (value) {
            window.__seekTimes.push(value);
            return currentTimeDescriptor.set.call(this, value);
          }
        });
        """
    )


def open_report(page: Page) -> None:
    page.goto(BASE_URL, wait_until="networkidle")
    page.wait_for_timeout(350)
    page.locator(".recording-history-item").click()
    page.locator('[aria-label="Sales call report"]').wait_for()
    page.wait_for_timeout(250)


def assert_mobile_header_contained(page: Page) -> None:
    header = page.locator(".studio-header").bounding_box()
    brand = page.locator(".studio-header > a").bounding_box()
    assert header and brand
    assert brand["y"] >= header["y"]
    assert brand["y"] + brand["height"] <= header["y"] + header["height"] + 1
    assert page.evaluate("document.documentElement.scrollWidth <= window.innerWidth")


def main() -> None:
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        page = browser.new_page(viewport={"width": 1280, "height": 900})
        install_routes(page)
        open_report(page)

        report = page.locator('[aria-label="Sales call report"]')
        assert report.is_visible()
        page.locator("audio").evaluate("el => el.load()")
        page.wait_for_timeout(500)
        assert "Source moments" in report.inner_text()
        assert "Recommended next steps" in report.inner_text()
        assert "Internal testing" not in page.locator("body").inner_text()
        assert "Advanced: checkpoints" not in page.locator("body").inner_text()
        assert page.locator(".studio-moment").count() == 2
        page.get_by_role("button", name="Print / save PDF", exact=True).click()
        assert page.evaluate("window.__printCalls") == 1

        disclosures = page.locator(".studio-finding-evidence")
        assert disclosures.count() > 0
        assert not disclosures.first.evaluate("el => el.open")
        disclosures.first.locator("summary").focus()
        page.keyboard.press("Enter")
        assert disclosures.first.evaluate("el => el.open")
        assert REPORT["strengths"][0]["evidence"][0]["quote"] in disclosures.first.inner_text()
        disclosures.first.locator("summary").click()

        page.get_by_role("tab", name="Call moments", exact=True).click()
        first_moment = page.locator(".studio-moment").first
        first_moment.click()
        assert first_moment.get_attribute("aria-pressed") == "true"
        page.wait_for_timeout(50)
        assert page.evaluate("window.__seekTimes.includes(1.5)")

        page.evaluate("window.__playMode = 'reject'")
        page.locator(".studio-moment").nth(1).click()
        page.wait_for_timeout(50)
        assert "Playback was blocked" in page.locator(".studio-playback-status").inner_text()

        page.evaluate("document.querySelector('audio')?.remove()")
        first_moment.click()
        assert "playback is unavailable" in page.locator(".studio-playback-status").inner_text()
        AUDIT_DIR.mkdir(parents=True, exist_ok=True)
        page.screenshot(
            path=str(AUDIT_DIR / "report-playback-recovery.png"),
            full_page=True,
            animations="disabled",
        )

        # Reload to restore the authorized source element before the visual matrix.
        page.set_viewport_size({"width": 1280, "height": 900})
        page.evaluate("window.__playMode = 'resolve'")
        open_report(page)
        page.evaluate("window.__originalAudio = document.querySelector('audio')")
        page.get_by_role("tab", name="Sales factors", exact=True).click()
        factors = page.locator('[aria-label="Sales factors"]')
        assert factors.locator("details").count() == 8
        factors.locator("summary").first.click()
        assert REPORT["dimensions"][0]["observation"] in factors.inner_text()
        page.get_by_role("tab", name="Transcript", exact=True).click()
        page.locator("summary").filter(has_text="Read full transcript").click()
        page.get_by_role("searchbox", name="Search transcript phrases").fill("useful")
        assert page.locator("[data-segment-id]").count() == 1
        page.locator("[data-segment-id]").click()
        assert page.evaluate("window.__seekTimes.includes(2.5)")
        page.get_by_role("searchbox", name="Search transcript phrases").fill("")
        assert page.locator("[data-segment-id]").count() == 2
        page.get_by_role("tab", name="Sound", exact=True).click()
        page.locator("summary").filter(has_text="Sound of the recording").click()
        page.get_by_text("-18.0 dBFS", exact=True).wait_for()
        page.get_by_role("combobox", name="Audio channel", exact=True).select_option("1")
        page.get_by_role("button", name="Pitch estimate", exact=True).click()
        assert page.get_by_role("slider", name="Inspect pitch estimate over time").is_visible()
        page.get_by_role("slider").fill("2")
        assert "Not available" in page.locator("output").inner_text()
        page.get_by_role("slider").fill("1")
        assert "190.0 Hz" in page.locator("output").inner_text()
        # Every section is independently usable, while the same audio element remains mounted.
        for tab_name in (
            "Overview",
            "Sales factors",
            "Call moments",
            "Transcript",
            "Sound",
            "Next steps",
        ):
            page.get_by_role("tab", name=tab_name, exact=True).click()
            assert page.get_by_role("tabpanel").count() == 1
            page.screenshot(
                path=str(AUDIT_DIR / f"section-{tab_name.lower().replace(' ', '-')}.png"),
                full_page=True,
                animations="disabled",
            )
        assert page.evaluate("window.__originalAudio === document.querySelector('audio')")
        page.get_by_role("tab", name="Transcript", exact=True).click()
        assert page.get_by_role("searchbox", name="Search transcript phrases").input_value() == ""
        page.get_by_role("tab", name="Sound", exact=True).click()
        assert "190.0 Hz" in page.locator("output").inner_text()
        assert page.get_by_role("combobox", name="Audio channel", exact=True).input_value() == "1"
        page.emulate_media(media="print")
        assert not page.locator(".studio-header").is_visible()
        assert not page.locator(".studio-report-actions").is_visible()
        assert not page.get_by_role("searchbox", name="Search transcript phrases").is_visible()
        assert not page.get_by_role("combobox", name="Audio channel", exact=True).is_visible()
        assert not page.get_by_role("tablist").is_visible()
        assert report.is_visible()
        assert "AI draft · Dipak has not reviewed this" in report.inner_text()
        page.screenshot(
            path=str(AUDIT_DIR / "report-print-layout.png"), full_page=True, animations="disabled"
        )
        page.pdf(path=str(AUDIT_DIR / "synthetic-report.pdf"), format="A4", print_background=True)
        page.emulate_media(media="screen")
        assert page.locator(".studio-language-control select").count() == 0
        assert "Upload your call" in page.locator(".studio-steps").inner_text()
        page.get_by_role("tab", name="Transcript", exact=True).click()
        for segment in TRANSCRIPT["segments"]:
            assert segment["text"] in report.inner_text()
        search = page.get_by_role("searchbox", name="Search transcript phrases")
        search.fill("बजट")
        assert page.locator("[data-segment-id]").count() == 1
        assert TRANSCRIPT["segments"][1]["text"] in page.locator("[data-segment-id]").inner_text()
        search.fill("")
        assert REPORT["summary"] in report.inner_text()
        for section in ("Overview", "Transcript"):
            page.get_by_role("tab", name=section, exact=True).click()
            for width, height in ((1280, 900), (390, 844), (320, 780)):
                page.set_viewport_size({"width": width, "height": height})
                assert_mobile_header_contained(page)
                page.screenshot(
                    path=str(AUDIT_DIR / f"mixed-script-{section.lower()}-{width}.png"),
                    full_page=True,
                    animations="disabled",
                )
        tab = page.get_by_role("tab", name="Overview", exact=True)
        tab.focus()
        tab.press("End")
        assert page.locator('[role="tab"][aria-selected="true"]').evaluate(
            "el => el === document.activeElement"
        )
        assert page.evaluate("document.documentElement.scrollWidth <= window.innerWidth")
        page.locator('[role="tab"][aria-selected="true"]').press("Home")

        browser.close()
        root = Path(__file__).resolve().parents[3]
        receipt = {
            "schema": "ac.sales-xray.report-navigation-browser/1",
            "source_commit": os.environ.get("SALES_XRAY_SOURCE_COMMIT", "see source file hashes"),
            "source_files": {
                str(path.relative_to(root)): hashlib.sha256(path.read_bytes()).hexdigest()
                for path in [
                    root / "apps/sales-xray-web/app/call-studio.tsx",
                    root / "apps/sales-xray-web/app/report-explorer.tsx",
                    root / "apps/sales-xray-web/app/finding-evidence.tsx",
                    root / "apps/sales-xray-web/app/report-explorer.module.css",
                ]
            },
            "url": BASE_URL,
            "fixture_api": True,
            "media_play_substituted_for_recovery": True,
            "provider_calls": 0,
            "checks": [
                "six usable sections",
                "collapsed source evidence expands by keyboard and remains complete for print",
                "same media element across navigation",
                "source moment seek and blocked/missing recovery",
                "transcript filter and exact seek",
                "retained sound channel and cursor",
                "English shell without global language controls",
                "literal Hindi/Marathi/English mixed transcript and report; Devanagari search",
                "keyboard Home/End and selected focus at320px",
                "print includes hidden sections and excludes tab controls",
            ],
            "result": "passed",
            "artifacts": [
                {
                    "file": p.name,
                    "sha256": hashlib.sha256(p.read_bytes()).hexdigest(),
                    "bytes": p.stat().st_size,
                }
                for p in sorted(AUDIT_DIR.iterdir())
                if p.suffix in {".png", ".pdf"}
            ],
        }
        (AUDIT_DIR / "navigation-browser-receipt.json").write_text(
            json.dumps(receipt, indent=2), encoding="utf-8"
        )


if __name__ == "__main__":
    main()
