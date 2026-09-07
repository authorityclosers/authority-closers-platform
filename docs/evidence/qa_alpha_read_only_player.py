"""Isolated mounted-player QA: synthetic API/envelope, local reviewed film bytes.

No live credentials, server writes, feature flags, external delivery or signing
verification. This proves the browser playback/UI path, not authenticated staging.
"""

from __future__ import annotations

import argparse
import base64
import json
import sys
from datetime import UTC, datetime
from pathlib import Path
from urllib.parse import quote, urlparse

from playwright.sync_api import expect, sync_playwright

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts"))
import qa_alpha_activity as qa  # noqa: E402


def media_interceptor(source, denial, film):
    def intercept(route):
        parsed = urlparse(route.request.url)
        if route.request.url == source:
            route.fulfill(
                status=200,
                content_type="video/mp4",
                body=film,
                headers={"Cache-Control": "no-store"},
            )
        elif (
            denial["value"] and parsed.path == f"/v1/activities/{qa.VIDEO_UNAVAILABLE.activity_id}"
        ):
            qa._json_response(route, {"title": "Synthetic playback denied"}, status=403)
        else:
            route.fallback()

    return intercept


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--width", type=int, choices=(1440,), help="Run only remaining desktop case"
    )
    args = parser.parse_args()
    origin = "http://learner.localhost:3100"
    run = (
        ROOT
        / "docs/evidence/screenshots/alpha-read-only-player-2026-09-07"
        / datetime.now(UTC).strftime("run-%Y%m%dT%H%M%SZ")
    )
    run.mkdir(parents=True, exist_ok=False)
    film = (
        ROOT
        / "tools/media-player-stress/.artifacts/staging-alpha-public-films-12s-v1"
        / "caminandes-12s/progressive.mp4"
    ).read_bytes()
    original_activity = qa._activity_response
    results = []
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(channel="chrome", headless=True)
        try:
            cases = (
                ((1440, "light"),)
                if args.width
                else ((320, "dark"), (390, "light"), (390, "dark"), (1440, "light"))
            )
            for width, theme in cases:
                now = int(datetime.now(UTC).timestamp())
                key = "synthetic/caminandes.mp4"
                claims = {
                    "typ": "AC-MEDIA",
                    "token_type": "playback",
                    "iat": now,
                    "exp": now + 180,
                    "activity_id": qa.VIDEO_UNAVAILABLE.activity_id,
                    "activity_version": "1",
                    "asset_id": "synthetic-asset",
                    "version_id": "synthetic-version",
                    "binding_id": "synthetic-binding",
                    "enrollment_id": qa.CANONICAL_ENROLLMENT_ID,
                    "delivery_grant_id": "synthetic-grant",
                    "key": key,
                }
                payload = (
                    base64.urlsafe_b64encode(json.dumps(claims).encode()).rstrip(b"=").decode()
                )
                synthetic_url = (
                    f"https://media.example.invalid/v1/media/playback/{quote(key, safe='')}"
                    f"?token=AC-MEDIA.{payload}.{'a' * 43}"
                )

                def activity_response(fixture, source=synthetic_url):
                    response = original_activity(fixture)
                    response["allowed_actions"] = []
                    response["media"] = {
                        "state": "approved",
                        "reason": "approved_media_delivery_available",
                        "binding_id": "synthetic-binding",
                        "media_id": "synthetic-asset",
                        "media_version_id": "synthetic-version",
                        "activity_version": "1",
                        "content_type": "video/mp4",
                        "duration_seconds": 12.032,
                        "width": 1920,
                        "height": 1080,
                        "renditions": [],
                        "captions": [],
                        "playback_available": True,
                        "delivery": {
                            "protocol": "hls",
                            "manifest_url": "https://media.example.invalid/master.m3u8",
                            "progressive_url": source,
                        },
                    }
                    return response

                qa._activity_response = activity_response
                case = {
                    "width": width,
                    "theme": theme,
                    "network": {
                        "blocked_writes": [],
                        "unknown_api_blocked": [],
                        "fixture_reads": [],
                        "blocked_external": [],
                    },
                }
                context = browser.new_context(
                    viewport={"width": width, "height": 900},
                    color_scheme=theme,
                    service_workers="block",
                )
                try:
                    context.add_init_script(
                        "window.qaOnline = true; Object.defineProperty(navigator, 'onLine', "
                        "{get: () => window.qaOnline});"
                        f"localStorage.setItem('ac-appearance-theme',{json.dumps(theme)});"
                        "localStorage.setItem('ac-appearance-motion','reduced');"
                    )
                    qa._install_fixture_routes(context, case, origin, qa.VIDEO_UNAVAILABLE)
                    deny_refresh = {"value": False}

                    context.route("**/*", media_interceptor(synthetic_url, deny_refresh, film))
                    page = context.new_page()
                    page.set_default_timeout(20_000)
                    page.set_default_navigation_timeout(60_000)
                    page.goto(
                        f"{origin}/activity/{qa.VIDEO_UNAVAILABLE.activity_id}",
                        wait_until="domcontentloaded",
                    )
                    expect(page.locator('[data-playback-mode="read-only"]')).to_be_visible()
                    qa._assert_requested_theme(page, theme)
                    expect(
                        page.get_by_text(
                            "Playback only — progress is not recorded for this lesson.", exact=True
                        )
                    ).to_be_visible()
                    page.locator("video").evaluate("video => {video.muted = true;}")
                    page.get_by_role("button", name="Play lesson", exact=True).click()
                    try:
                        page.wait_for_function(
                            "() => {const v = document.querySelector('video'); "
                            "return v && !v.paused && v.currentTime > 2.5 && v.videoWidth > 0;}"
                        )
                    except Exception:
                        print(
                            json.dumps(
                                page.locator("video").evaluate(
                                    "v => ({paused:v.paused,time:v.currentTime,ready:v.readyState,"
                                    "error:v.error?.code,width:v.videoWidth,hidden:document.hidden,"
                                    "state:v.parentElement.dataset.mediaState,hasSource:v.hasAttribute('src')})"
                                )
                            )
                        )
                        raise
                    observed = page.locator("video").evaluate(
                        "v => ({width:v.videoWidth,height:v.videoHeight,"
                        "duration:v.duration,advanced:v.currentTime>2.5})"
                    )
                    assert observed["width"] == 1920 and observed["height"] == 1080
                    assert page.evaluate("document.documentElement.scrollWidth <= innerWidth"), (
                        "Horizontal overflow"
                    )
                    page.screenshot(path=str(run / f"{width}-{theme}-playing.png"), full_page=True)
                    # A full-page capture can outlast a 12-second clip. Do not
                    # seek an already-ended/paused video back away from end.
                    page.locator("video").evaluate(
                        "v => {if (!v.ended) v.currentTime = v.duration - 0.15;}"
                    )
                    page.wait_for_function("() => document.querySelector('video')?.ended === true")
                    expect(
                        page.get_by_text(
                            "Playback ended. Progress has not been recorded.", exact=True
                        ).first
                    ).to_be_visible()
                    page.evaluate("window.qaOnline = false; dispatchEvent(new Event('offline'));")
                    deny_refresh["value"] = True
                    page.evaluate("window.qaOnline = true; dispatchEvent(new Event('online'));")
                    expect(
                        page.get_by_role("heading", name="Reopen this lesson to continue")
                    ).to_be_visible()
                    expect(page.locator("video")).to_have_count(0)
                    page.screenshot(path=str(run / f"{width}-{theme}-denied.png"), full_page=True)
                    assert not case["network"]["blocked_writes"], "Unexpected attempted mutation"
                    assert not case["network"]["unknown_api_blocked"], "Unexpected API read"
                    results.append(
                        {
                            "width": width,
                            "theme": theme,
                            "decoded": observed,
                            "attempted_writes": 0,
                            "reconnect_denial_stopped": True,
                            "horizontal_overflow": False,
                            "status": "pass",
                        }
                    )
                finally:
                    context.close()
        finally:
            browser.close()
    report = {
        "evidence": (
            "Synthetic API/envelope with locally fulfilled reviewed MP4; "
            "not server authentication, HLS/ABR, staging or performance proof"
        ),
        "cases": results,
    }
    (run / "report.json").write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"cases": len(results), "failures": 0, "report": str(run / "report.json")}))


if __name__ == "__main__":
    main()
