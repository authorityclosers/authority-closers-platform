"""Built app, shared synthetic new-format report, real browser audio playback.

API responses are intercepted fixtures. This proves presentation, not hosted
authorization or inference quality; the separate PostgreSQL E2E suite owns those
local application boundaries. No external provider request is made.
"""

import hashlib
import json
import os
import wave
from io import BytesIO
from pathlib import Path
from urllib.parse import urlsplit

from playwright.sync_api import expect, sync_playwright

ROOT = Path(__file__).resolve().parents[3]
BASE = os.environ.get("SALES_XRAY_BASE_URL", "http://127.0.0.1:3206")
OUT = Path(os.environ["SALES_XRAY_UX_EVIDENCE_DIR"])


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    fixture = json.loads(
        (Path(__file__).parent / "fixtures/dipak-overview.json").read_text(encoding="utf-8")
    )
    buffer = BytesIO()
    with wave.open(buffer, "wb") as wav:
        wav.setnchannels(1)
        wav.setsampwidth(2)
        wav.setframerate(16000)
        wav.writeframes(b"\0\0" * 16000 * 5)
    audio = buffer.getvalue()
    sha = hashlib.sha256(audio).hexdigest()
    fixture["report"]["source_sha256"] = sha
    fixture["transcript"]["source_sha256"] = sha
    recording = {
        "id": "recording-1",
        "state": "completed",
        "source_revision": "source-1",
        "source_sha256": sha,
        "source_bytes": len(audio),
        "content_type": "audio/wav",
        "created_at": "2026-09-14T00:00:00Z",
        "has_report": True,
        "latest_run": {
            "id": "run-1",
            "state": "completed",
            "recipe_revision": "synthetic-v1",
            "provider_calls": 0,
            "has_report": True,
        },
    }
    errors: list[str] = []
    external: list[str] = []
    network: list[dict[str, str | int]] = []

    def route_api(route):
        path = urlsplit(route.request.url).path
        if path.endswith("/workspace"):
            body = {
                "authenticated": True,
                "intake_enabled": True,
                "sign_in_url": None,
                "message": "Synthetic QA workspace.",
            }
        elif path.endswith("/recordings"):
            body = {"recordings": [recording]}
        elif path.endswith("/transcript"):
            body = fixture["transcript"]
        elif path.endswith("/report"):
            body = {
                "id": "run-1",
                "recording_id": "recording-1",
                "recipe_revision": "synthetic-v1",
                "provider_calls": 0,
                "state": "completed",
                "message": "Report ready.",
                "report": fixture["report"],
            }
        elif path.endswith("/source"):
            route.fulfill(status=200, content_type="audio/wav", body=audio)
            return
        else:
            route.fulfill(
                status=404, content_type="application/json", body='{"detail":"Unavailable"}'
            )
            return
        route.fulfill(status=200, content_type="application/json", body=json.dumps(body))

    with sync_playwright() as playwright:
        browser = playwright.chromium.launch()
        page = browser.new_page(viewport={"width": 1280, "height": 1000}, reduced_motion="reduce")
        page.on("pageerror", lambda error: errors.append(str(error)))

        def boundary(route):
            url = urlsplit(route.request.url)
            if url.scheme in {"http", "https"} and url.netloc != urlsplit(BASE).netloc:
                external.append(url.hostname or "unknown")
                route.abort()
            else:
                route.continue_()

        page.route("**/*", boundary)
        page.route("**/v1/conversation/**", route_api)
        page.route(
            "**/v1/me/workspaces",
            lambda route: route.fulfill(
                status=200,
                content_type="application/json",
                body=json.dumps(
                    {
                        "person_id": "person-1",
                        "session_id": "session-1",
                        "selected_tenant_id": "tenant-1",
                        "workspaces": [{"tenant_id": "tenant-1", "name": "QA"}],
                    }
                ),
            ),
        )
        page.on(
            "response",
            lambda response: network.append(
                {
                    "path": urlsplit(response.url).path,
                    "status": response.status,
                }
            ),
        )
        page.goto(BASE, wait_until="networkidle")
        page.locator(".recording-history-item").click()
        expect(page.get_by_role("region", name="Sales call report")).to_be_visible()
        overview = page.get_by_label("Dipak’s call review", exact=True)
        expect(overview).to_be_visible()
        for number in ["05", "06", "07", "09", "10", "12", "14"]:
            summary = overview.locator(f'[data-review-point="{number}"] > summary')
            summary.focus()
            summary.press("Enter")
        for value in [
            fixture["report"]["overview"]["diagnosis"]["text"],
            fixture["report"]["overview"]["practice"]["success_condition"],
            fixture["report"]["overview"]["conversation_change"]["possible_effect"],
        ]:
            expect(overview.get_by_text(value, exact=False)).to_be_visible()
        expect(overview.get_by_text("Possible concern · inference", exact=True)).to_be_visible()
        expect(overview.locator('[data-review-point="13"]')).to_have_count(0)
        clips = overview.locator('[data-review-point="08"] button')
        expect(clips).to_have_count(2)
        clips.nth(1).click()
        page.wait_for_function("document.querySelector('audio').currentTime > 2.5")
        page.locator("audio").evaluate("audio => audio.pause()")
        page.get_by_role("tab", name="Overview", exact=True).click()
        for width in [1280, 390, 320]:
            page.set_viewport_size({"width": width, "height": 1000})
            assert page.evaluate("document.documentElement.scrollWidth <= innerWidth")
            page.screenshot(path=str(OUT / f"structured-overview-{width}.png"), full_page=True)
        page.evaluate("dispatchEvent(new Event('beforeprint'))")
        assert page.locator("[data-review-fold]:not([open])").count() == 0
        assert page.locator(".studio-finding-evidence:not([open])").count() == 0
        page.evaluate("dispatchEvent(new Event('afterprint'))")
        assert not errors and not external
        browser.close()
    files = [
        "app/dipak-overview.tsx",
        "app/dipak-overview.module.css",
        "app/overview-contract.ts",
        "app/report-contract.ts",
        "tests/fixtures/dipak-overview.json",
    ]
    receipt = {
        "schema": "ac.sales-xray.dipak-overview-browser/1",
        "passed": True,
        "fixture_api": True,
        "real_media_playback": True,
        "provider_calls": 0,
        "source_files": {
            name: hashlib.sha256((ROOT / "apps/sales-xray-web" / name).read_bytes()).hexdigest()
            for name in files
        },
        "viewports": [1280, 390, 320],
        "checks": [
            "structured source-linked fields",
            "mixed-script literal evidence",
            "keyboard disclosures",
            "real audio seek/play",
            "print expands all evidence",
            "no invented history",
            "no horizontal overflow",
        ],
        "browser_errors": errors,
        "external_requests": external,
        "network": network,
    }
    (OUT / "structured-browser-receipt.json").write_text(
        json.dumps(receipt, indent=2), encoding="utf-8"
    )
    print("Structured overview browser proof passed; provider calls: 0.")


if __name__ == "__main__":
    main()
