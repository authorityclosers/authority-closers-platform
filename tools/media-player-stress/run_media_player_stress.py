#!/usr/bin/env python3
"""Browser stress harness for the development-only LearningLoopRuntime player.

The script is intentionally a test boundary:

* it runs the production ``VideoViewer`` through the Next development server;
* the API is an in-browser fake and never writes learner progress;
* media requests are fulfilled from ignored ``.artifacts`` files;
* the official sample is Blender's openly licensed Big Buck Bunny encode.

Start it through the repository's server helper, for example::

    python .agents/skills/webapp-testing/scripts/with_server.py \
      --server "pnpm --filter @ac/learner-web dev" --port 3000 -- \
      python tools/media-player-stress/run_media_player_stress.py
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from playwright.sync_api import (
    BrowserContext,
    Error as PlaywrightError,
    Page,
    Route,
    TimeoutError as PlaywrightTimeoutError,
    sync_playwright,
)


ROOT = Path(__file__).resolve().parents[2]
ARTIFACT_ROOT = ROOT / ".artifacts" / "media-player"
OUTPUT_ROOT = ARTIFACT_ROOT / "evidence"

FIXTURE_PATHS = {
    "official-bbb.mp4": ARTIFACT_ROOT
    / "official-bbb"
    / "BigBuckBunny_320x180.mp4",
    "tiny-16x9-320x180-4s.mp4": ARTIFACT_ROOT
    / "tiny-16x9-320x180-4s.mp4",
    "tiny-4x3-320x240-6s.mp4": ARTIFACT_ROOT / "tiny-4x3-320x240-6s.mp4",
    "tiny-235x-640x272-3s.mp4": ARTIFACT_ROOT
    / "tiny-235x-640x272-3s.mp4",
}

CAPTIONS = """WEBVTT

00:00.250 --> 00:01.200
Opening frame

00:01.200 --> 00:02.200
Playback control checkpoint

00:02.200 --> 00:03.400
Completion and retry checkpoint
"""

NETWORK_IDLE_TIMEOUT_MS = 90_000


@dataclass(frozen=True)
class CaseResult:
    name: str
    passed: bool
    details: str
    screenshot: str | None = None


def route_fixture(route: Route, request_url: str) -> None:
    name = Path(urlparse(request_url).path).name
    fixture = FIXTURE_PATHS.get(name)
    if fixture is None or not fixture.is_file():
        route.abort()
        return
    route.fulfill(
        path=str(fixture),
        headers={"Cache-Control": "no-store", "Accept-Ranges": "bytes"},
    )


def route_captions(route: Route) -> None:
    route.fulfill(
        status=200,
        content_type="text/vtt; charset=utf-8",
        body=CAPTIONS,
        headers={"Cache-Control": "no-store"},
    )


def add_browser_guards(context: BrowserContext) -> None:
    """Make fullscreen rejection deterministic without granting fullscreen."""

    context.add_init_script(
        """
        Object.defineProperty(document, "fullscreenEnabled", {
          configurable: true,
          value: true,
        });
        HTMLMediaElement.prototype.requestFullscreen = () =>
          Promise.reject(new DOMException("Harness rejection", "NotAllowedError"));
        document.exitFullscreen = () =>
          Promise.reject(new DOMException("Harness rejection", "NotAllowedError"));
        """
    )


def wait_for_metadata(page: Page, width: int, height: int, duration: float) -> None:
    page.wait_for_function(
        """
        ({width, height, duration}) => {
          const video = document.querySelector("video");
          return Boolean(
            video &&
            video.readyState >= 1 &&
            Number.isFinite(video.duration) &&
            video.videoWidth === width &&
            video.videoHeight === height &&
            Math.abs(video.duration - duration) < 1.2
          );
        }
        """,
        arg={"width": width, "height": height, "duration": duration},
        timeout=20_000,
    )


def assert_no_horizontal_overflow(page: Page) -> None:
    assert page.evaluate(
        "document.documentElement.scrollWidth <= window.innerWidth + 1"
    ), "the harness/player overflows horizontally"


def trace_entries(page: Page, event_type: str | None = None) -> list[dict[str, Any]]:
    locator = page.get_by_test_id("harness-trace-entry")
    entries: list[dict[str, Any]] = []
    for index in range(locator.count()):
        item = locator.nth(index)
        item_type = item.get_attribute("data-event-type") or ""
        if event_type is not None and item_type != event_type:
            continue
        sequence = item.get_attribute("data-sequence") or ""
        entries.append(
            {
                "type": item_type,
                "sequence": int(sequence) if sequence else None,
                "text": item.inner_text(),
            }
        )
    return entries


def goto_case(
    page: Page,
    base_url: str,
    fixture: str,
    scenario: str,
    width: int,
    height: int,
    duration: float,
) -> None:
    page.goto(
        f"{base_url}/dev-harness/media-player?fixture={fixture}&scenario={scenario}",
        wait_until="domcontentloaded",
        timeout=NETWORK_IDLE_TIMEOUT_MS,
    )
    page.wait_for_load_state("networkidle", timeout=NETWORK_IDLE_TIMEOUT_MS)
    page.get_by_test_id("media-player-harness").wait_for()
    page.locator("video").wait_for()
    wait_for_metadata(page, width, height, duration)
    assert page.locator("track[kind='captions']").count() == 1
    page.wait_for_function(
        """
        () => {
          const tracks = document.querySelector("video")?.textTracks;
          return Boolean(tracks && tracks.length === 1 && tracks[0].cues?.length);
        }
        """,
        timeout=10_000,
    )


def open_context(playwright: Any, width: int, height: int, reduced_motion: bool) -> BrowserContext:
    browser = playwright.chromium.launch(headless=True)
    context = browser.new_context(
        viewport={"width": width, "height": height},
        reduced_motion="reduce" if reduced_motion else "no-preference",
    )
    context.route(
        "**/dev-harness/media-player/fixtures/*.mp4",
        lambda route, request: route_fixture(route, request.url),
    )
    context.route(
        "**/dev-harness/media-player/captions.vtt",
        route_captions,
    )
    add_browser_guards(context)
    return context


def close_context(context: BrowserContext) -> None:
    browser = context.browser
    context.close()
    if browser is not None:
        browser.close()


def run_core_case(
    playwright: Any,
    base_url: str,
    fixture: str,
    viewport_width: int,
    viewport_height: int,
    media_width: int,
    media_height: int,
    duration: float,
    reduced_motion: bool,
    output_path: Path,
) -> CaseResult:
    name = f"core-{fixture}-{viewport_width}x{viewport_height}-{'reduce' if reduced_motion else 'normal'}"
    browser_context = open_context(playwright, viewport_width, viewport_height, reduced_motion)
    page = browser_context.new_page()
    console_errors: list[str] = []
    page_errors: list[str] = []
    page.on("console", lambda message: console_errors.append(message.text) if message.type == "error" else None)
    page.on("pageerror", lambda error: page_errors.append(str(error)))
    try:
        page.goto(
            f"{base_url}/dev-harness/media-player?fixture={fixture}&scenario=normal",
            wait_until="domcontentloaded",
            timeout=NETWORK_IDLE_TIMEOUT_MS,
        )
        page.wait_for_load_state("networkidle", timeout=NETWORK_IDLE_TIMEOUT_MS)
        page.get_by_test_id("media-player-harness").wait_for()
        page.locator("video").wait_for()
        wait_for_metadata(page, media_width, media_height, duration)
        assert_no_horizontal_overflow(page)
        assert page.evaluate("window.matchMedia('(prefers-reduced-motion: reduce)').matches") is reduced_motion
        assert page.locator("video track[kind='captions']").count() == 1
        page.wait_for_function("() => document.querySelector('video')?.textTracks[0]?.cues?.length", timeout=10_000)

        page.get_by_role("button", name="Play lesson").click()
        page.wait_for_function("() => document.querySelector('video')?.paused === false", timeout=5_000)
        page.get_by_role("button", name="Pause lesson").wait_for(timeout=5_000)
        page.get_by_role("button", name="Pause lesson").click()
        page.wait_for_function("() => document.querySelector('video')?.paused === true", timeout=5_000)
        page.get_by_role("button", name="Play lesson").wait_for(timeout=5_000)
        page.get_by_role("button", name="Play lesson").click()
        page.wait_for_function("() => document.querySelector('video')?.paused === false", timeout=5_000)

        page.get_by_label("Playback speed").select_option("1.5")
        assert page.locator(".momentum-video-controls select").input_value() == "1.5"
        page.get_by_role("button", name="Mute lesson").click()
        assert page.evaluate("document.querySelector('video')?.muted === true")
        page.get_by_role("button", name="Unmute lesson").click()
        assert page.evaluate("document.querySelector('video')?.muted === false")
        page.get_by_role("button", name="Hide captions").click()
        page.wait_for_function(
            "() => document.querySelector('video')?.textTracks[0]?.mode === 'hidden'",
            timeout=5_000,
        )
        page.get_by_role("button", name="Show captions").click()
        page.wait_for_function(
            "() => document.querySelector('video')?.textTracks[0]?.mode === 'showing'",
            timeout=5_000,
        )

        page.locator(".momentum-video-controls__play").focus()
        page.keyboard.press("Tab")
        assert page.evaluate("document.activeElement?.closest('[role=group]') !== null")

        page.get_by_text("Open transcript", exact=True).click()
        page.get_by_role("button", name=re.compile("Opening frame")).click()
        page.wait_for_function("() => (document.querySelector('video')?.currentTime || 0) >= 0.2", timeout=5_000)

        page.get_by_role("button", name="Enter fullscreen").click()
        page.get_by_role("status").filter(
            has_text="Fullscreen could not be opened. Try again."
        ).wait_for(timeout=5_000)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        page.screenshot(path=str(output_path), full_page=True)
        if console_errors or page_errors:
            raise AssertionError(f"browser errors: console={console_errors}, page={page_errors}")
        return CaseResult(name, True, "metadata, controls, transcript, focus, fullscreen rejection, and overflow passed", str(output_path))
    except (AssertionError, PlaywrightError, PlaywrightTimeoutError) as error:
        return CaseResult(name, False, str(error), None)
    finally:
        close_context(browser_context)


def run_abort_case(playwright: Any, base_url: str, output_path: Path) -> CaseResult:
    name = "abort-heartbeat-retries-same-sequence"
    browser_context = open_context(playwright, 390, 844, False)
    page = browser_context.new_page()
    try:
        goto_case(page, base_url, "tiny-4x3-320x240-6s", "abort-heartbeat", 320, 240, 6)
        page.get_by_role("button", name="Play lesson").click()
        page.locator("video").evaluate("video => { video.playbackRate = 2; }")
        page.get_by_test_id("harness-trace-entry").filter(has_text="heartbeat network abort").wait_for(timeout=8_000)
        page.wait_for_function(
            "() => document.querySelectorAll('[data-testid=harness-trace-entry][data-event-type=heartbeat]').length >= 2",
            timeout=8_000,
        )
        heartbeats = trace_entries(page, "heartbeat")
        assert [entry["sequence"] for entry in heartbeats[:2]] == [1, 1], heartbeats
        output_path.parent.mkdir(parents=True, exist_ok=True)
        page.screenshot(path=str(output_path), full_page=True)
        return CaseResult(name, True, "network abort retried the pending event without sequence drift", str(output_path))
    except (AssertionError, PlaywrightError, PlaywrightTimeoutError) as error:
        return CaseResult(name, False, str(error), None)
    finally:
        close_context(browser_context)


def run_expired_grant_case(playwright: Any, base_url: str, output_path: Path) -> CaseResult:
    name = "expired-grant-reacquisition"
    browser_context = open_context(playwright, 390, 844, False)
    page = browser_context.new_page()
    try:
        goto_case(page, base_url, "tiny-16x9-320x180-4s", "expired-grant", 320, 180, 4)
        page.get_by_role("button", name="Play lesson").click()
        page.get_by_test_id("harness-trace-entry").filter(has_text="harness-session-1 expired").wait_for(timeout=5_000)
        page.get_by_role("button", name="Play lesson").click()
        page.get_by_test_id("harness-trace-entry").filter(has_text="harness-session-2 valid").wait_for(timeout=5_000)
        page.wait_for_function("() => document.querySelector('video')?.paused === false", timeout=5_000)
        starts = trace_entries(page, "start")
        assert len(starts) == 2, starts
        output_path.parent.mkdir(parents=True, exist_ok=True)
        page.screenshot(path=str(output_path), full_page=True)
        return CaseResult(name, True, "expired first grant was rejected and a fresh grant started playback", str(output_path))
    except (AssertionError, PlaywrightError, PlaywrightTimeoutError) as error:
        return CaseResult(name, False, str(error), None)
    finally:
        close_context(browser_context)


def run_session_expired_case(playwright: Any, base_url: str, output_path: Path) -> CaseResult:
    name = "session-expired-safe-restart"
    browser_context = open_context(playwright, 390, 844, False)
    page = browser_context.new_page()
    try:
        goto_case(page, base_url, "tiny-4x3-320x240-6s", "session-expired", 320, 240, 6)
        page.get_by_role("button", name="Play lesson").click()
        page.locator("video").evaluate("video => { video.playbackRate = 2; }")
        page.get_by_test_id("harness-trace-entry").filter(has_text="playback session expired").wait_for(timeout=8_000)
        page.get_by_role("button", name="Retry server save").wait_for(timeout=8_000)
        page.get_by_role("button", name="Retry server save").click()
        page.get_by_test_id("harness-trace-entry").filter(has_text="harness-session-2 valid").wait_for(timeout=8_000)
        page.wait_for_function("() => document.querySelector('video')?.paused === false", timeout=5_000)
        starts = trace_entries(page, "start")
        assert len(starts) == 2, starts
        output_path.parent.mkdir(parents=True, exist_ok=True)
        page.screenshot(path=str(output_path), full_page=True)
        return CaseResult(name, True, "invalid session paused evidence and retry reacquired from a safe restart", str(output_path))
    except (AssertionError, PlaywrightError, PlaywrightTimeoutError) as error:
        return CaseResult(name, False, str(error), None)
    finally:
        close_context(browser_context)


def run_finish_retry_case(playwright: Any, base_url: str, output_path: Path) -> CaseResult:
    name = "finish-network-retry-without-duplicate-heartbeat"
    browser_context = open_context(playwright, 390, 844, False)
    page = browser_context.new_page()
    try:
        goto_case(page, base_url, "tiny-235x-640x272-3s", "finish-network", 640, 272, 3)
        page.get_by_role("button", name="Play lesson").click()
        page.locator("video").evaluate("video => { video.playbackRate = 2; }")
        page.get_by_role("button", name="Retry server save").wait_for(timeout=8_000)
        page.get_by_role("button", name="Retry server save").click()
        page.get_by_test_id("harness-trace-entry").filter(has_text="video_watch for").wait_for(timeout=8_000)
        finishes = trace_entries(page, "finish")
        heartbeats = trace_entries(page, "heartbeat")
        evidence = trace_entries(page, "evidence")
        assert len(finishes) == 2, finishes
        assert len(heartbeats) == 1, heartbeats
        assert len(evidence) == 1, evidence
        output_path.parent.mkdir(parents=True, exist_ok=True)
        page.screenshot(path=str(output_path), full_page=True)
        return CaseResult(name, True, "finish retry reused the closed-session path and did not append a heartbeat", str(output_path))
    except (AssertionError, PlaywrightError, PlaywrightTimeoutError) as error:
        return CaseResult(name, False, str(error), None)
    finally:
        close_context(browser_context)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-url", default="http://localhost:3000")
    parser.add_argument(
        "--output",
        type=Path,
        default=ARTIFACT_ROOT / "stress-results.json",
        help="Ignored JSON evidence output path",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    missing = [str(path) for path in FIXTURE_PATHS.values() if not path.is_file()]
    if missing:
        print("Missing media fixtures:", file=sys.stderr)
        print("\n".join(missing), file=sys.stderr)
        return 2

    results: list[CaseResult] = []
    with sync_playwright() as playwright:
        results.append(
            run_core_case(
                playwright,
                args.base_url,
                "tiny-16x9-320x180-4s",
                320,
                844,
                320,
                180,
                4,
                False,
                OUTPUT_ROOT / "core-320x180.png",
            )
        )
        results.append(
            run_core_case(
                playwright,
                args.base_url,
                "tiny-4x3-320x240-6s",
                390,
                844,
                320,
                240,
                6,
                False,
                OUTPUT_ROOT / "core-mobile-390.png",
            )
        )
        results.append(
            run_core_case(
                playwright,
                args.base_url,
                "tiny-235x-640x272-3s",
                320,
                844,
                640,
                272,
                3,
                True,
                OUTPUT_ROOT / "core-mobile-320-reduced-motion.png",
            )
        )
        results.append(
            run_core_case(
                playwright,
                args.base_url,
                "official-bbb",
                390,
                844,
                320,
                180,
                596,
                False,
                OUTPUT_ROOT / "official-bbb-mobile-390.png",
            )
        )
        results.append(
            run_abort_case(
                playwright,
                args.base_url,
                OUTPUT_ROOT / "abort-heartbeat.png",
            )
        )
        results.append(
            run_expired_grant_case(
                playwright,
                args.base_url,
                OUTPUT_ROOT / "expired-grant.png",
            )
        )
        results.append(
            run_session_expired_case(
                playwright,
                args.base_url,
                OUTPUT_ROOT / "session-expired.png",
            )
        )
        results.append(
            run_finish_retry_case(
                playwright,
                args.base_url,
                OUTPUT_ROOT / "finish-network.png",
            )
        )

    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(
            {
                "base_url": args.base_url,
                "results": [asdict(result) for result in results],
                "passed": all(result.passed for result in results),
            },
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    for result in results:
        marker = "PASS" if result.passed else "FAIL"
        print(f"[{marker}] {result.name}: {result.details}")
    print(f"Evidence JSON: {args.output}")
    return 0 if all(result.passed for result in results) else 1


if __name__ == "__main__":
    raise SystemExit(main())
