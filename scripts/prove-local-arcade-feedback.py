"""Real local Arcade layout and editorial-feedback proof on a synthetic learner.

Uses normal sign-in and the actual API, not response fixtures. Theme and viewport
are emulated for visual inspection. Does not alter course assessment/progress.
"""

from __future__ import annotations

import json
import os
import re
import traceback
from datetime import UTC, datetime
from pathlib import Path
from urllib.parse import urlsplit

from playwright.sync_api import Route, expect, sync_playwright

ROOT = Path(__file__).resolve().parents[1]
ORIGIN = "http://learner.localhost:3100"
VIEWPORTS = ((320, 740), (390, 844), (768, 1024), (1440, 1000))


def local_only(route: Route) -> None:
    parsed = urlsplit(route.request.url)
    if f"{parsed.scheme}://{parsed.netloc}" == ORIGIN:
        route.continue_()
    else:
        route.abort()


def endpoint(url: str) -> str:
    """Keep diagnostic route structure without publishing synthetic record IDs."""
    if urlsplit(url).path.startswith("/v1/media/read/"):
        return "/v1/media/read/:private-object"
    return re.sub(
        r"/[0-9a-f]{8}-(?:[0-9a-f]{4}-){3}[0-9a-f]{12}(?=/|$)",
        "/:id",
        urlsplit(url).path,
    )


def main() -> int:
    output = (
        ROOT
        / ".tmp/local-platform/new/arcade-feedback"
        / datetime.now(UTC).strftime("%Y%m%dT%H%M%S%fZ")
    )
    output.mkdir(parents=True, exist_ok=False)
    proof = {
        "status": "incomplete",
        "views": [],
        "checks": [],
        "page_errors": [],
        "failed_requests": [],
        "api_responses": [],
    }
    stage = "sign-in"
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        context = browser.new_context(viewport={"width": 390, "height": 844})
        context.route("**/*", local_only)
        page = context.new_page()
        page.set_default_timeout(30000)
        navigation_epoch = 0
        request_epochs = {}
        successful_gets = set()
        failed_get_paths = []

        def navigated(frame) -> None:
            nonlocal navigation_epoch
            if frame == page.main_frame:
                navigation_epoch += 1

        def navigate(path: str) -> None:
            nonlocal navigation_epoch
            # Mark before goto: cancelled requests can arrive before the new
            # document's frame event. Only cancelled GETs use this classification.
            navigation_epoch += 1
            page.goto(ORIGIN + path, wait_until="networkidle")

        page.on("framenavigated", navigated)
        page.on("request", lambda request: request_epochs.update({request: navigation_epoch}))
        page.on("pageerror", lambda error: proof["page_errors"].append(str(error)[:400]))

        def failed_request(request) -> None:
            record = {
                "path": endpoint(request.url),
                "failure": request.failure,
                "method": request.method,
                "navigation_changed": request_epochs.get(request) != navigation_epoch,
            }
            proof["failed_requests"].append(record)
            # Match exact paths in memory, before record-ID redaction. No URLs,
            # headers or response bodies are written to the diagnostic artifact.
            failed_get_paths.append((record, urlsplit(request.url).path))

        page.on("requestfailed", failed_request)

        def record_api_status(response) -> None:
            if response.request.method == "GET" and response.status == 200:
                successful_gets.add(urlsplit(response.url).path)
            path = endpoint(response.url)
            if path.startswith(("/v1/auth/", "/v1/practice/")) or path == "/v1/me":
                # Endpoint/status only: never cookies, tokens, query strings or bodies.
                proof["api_responses"].append(
                    {"path": path, "status": response.status, "method": response.request.method}
                )

        page.on("response", record_api_status)

        def matrix(state: str) -> None:
            for theme in ("light", "dark"):
                page.emulate_media(color_scheme=theme, reduced_motion="reduce")
                # Let the app's system-theme listener settle before setting the
                # declared layout input. This is not a Settings workflow test.
                page.wait_for_timeout(120)
                for width, height in VIEWPORTS:
                    page.set_viewport_size({"width": width, "height": height})
                    page.evaluate("theme => document.documentElement.dataset.theme = theme", theme)
                    page.wait_for_timeout(120)
                    metrics = page.evaluate(
                        """() => {
                        const body = document.querySelector('[data-session-scroll="body"]');
                        const footer = body?.nextElementSibling;
                        const rect = footer?.getBoundingClientRect();
                        return {
                            width: innerWidth, height: innerHeight,
                            documentWidth: document.documentElement.scrollWidth,
                            scrollWidth: body?.scrollWidth, clientWidth: body?.clientWidth,
                            footer: rect ? {top: rect.top, bottom: rect.bottom} : null,
                            reduced: matchMedia('(prefers-reduced-motion: reduce)').matches,
                            theme: document.documentElement.dataset.theme,
                            tone: document.querySelector('[data-feedback-tone]')
                                ?.dataset.feedbackTone,
                            rewardNumberLines: [...document.querySelectorAll(
                                '[aria-label="Practice rewards and activity"] ' +
                                'button > span:nth-child(2)'
                            )].map(value => {
                                const range = document.createRange();
                                range.selectNodeContents(value);
                                return range.getClientRects().length;
                            }),
                        };
                    }"""
                    )
                    name = f"{state}-{theme}-{width}.png"
                    page.screenshot(path=str(output / name))
                    proof["views"].append({"screen": state, "file": name, **metrics})
                    assert metrics["theme"] == theme
                    assert metrics["reduced"] is True
                    assert metrics["documentWidth"] <= width + 1
                    if state == "hub":
                        assert len(metrics["rewardNumberLines"]) == 3
                    assert all(lines == 1 for lines in metrics["rewardNumberLines"])
                    if metrics["scrollWidth"] is not None:
                        assert metrics["scrollWidth"] <= metrics["clientWidth"] + 1
                    if metrics["footer"]:
                        assert metrics["footer"]["top"] >= 0
                        assert metrics["footer"]["bottom"] <= height + 1
            page.set_viewport_size({"width": 390, "height": 844})
            page.evaluate("document.documentElement.dataset.theme = 'light'")

        try:
            navigate("/login")
            expect(page.get_by_label("Email address")).to_be_enabled()
            page.get_by_label("Email address").fill("learner@ac.localhost")
            page.get_by_label("Password", exact=True).fill(
                os.environ["AC_LOCAL_BROWSER_TEST_PASSWORD"]
            )
            page.get_by_role("button", name="Sign in", exact=True).click()
            page.wait_for_url(lambda url: url.startswith(ORIGIN) and urlsplit(url).path != "/login")
            assert context.request.get(ORIGIN + "/v1/me").status == 200
            stage = "hub"
            navigate("/practice")
            expect(page.get_by_role("heading", name="Practice Arcade", exact=True)).to_be_visible()
            expect(page.get_by_role("button", name="View your week", exact=True)).to_be_visible()
            matrix("hub")
            expect(
                page.get_by_role("link", name="Academy leaderboard", exact=True)
            ).to_have_attribute("href", "/leaderboard")
            week = page.get_by_role("button", name="View your week", exact=True)
            week.click()
            expect(page.get_by_role("dialog")).to_be_visible()
            page.get_by_role("button", name="Close reward details", exact=True).click()
            expect(week).to_be_focused()
            proof["checks"].append("weekly details restore focus")

            stage = "intro"
            navigate("/practice?set=match")
            expect(
                page.get_by_role("heading", name="Connect the concern", exact=True)
            ).to_be_visible()
            matrix("intro")
            page.get_by_role("button", name="Start a new practice", exact=True).click()
            group = page.get_by_role("group", name="Match each statement to a question", exact=True)
            expect(group).to_be_visible()
            stage = "matching"
            matrix("matching")
            check = page.get_by_role("button", name="Check my response", exact=True)
            expect(check).to_be_disabled()

            pairs = (
                ("I need my partner involved.", "What will your partner need to evaluate?"),
                ("We cannot start until November.", "What changes for you in November?"),
                ("I am unsure it fits our team.", "Which part feels least relevant to your team?"),
            )

            def select_pairs(correct: bool) -> None:
                for index, (left, _) in enumerate(pairs):
                    right = pairs[index if correct else (index + 1) % len(pairs)][1]
                    group.get_by_role("button", name=re.compile("^" + re.escape(left))).click()
                    group.locator(":scope > div").nth(1).get_by_role(
                        "button", name=re.compile(re.escape(right))
                    ).click()

            select_pairs(False)
            expect(check).to_be_enabled()
            check.click()
            stage = "retry"
            expect(page.locator('[data-feedback-tone="retry"]')).to_be_visible()
            matrix("retry")
            page.get_by_role("button", name="Try a different answer", exact=True).click()
            expect(group).to_be_visible()
            select_pairs(True)
            check.click()
            stage = "success"
            expect(page.locator('[data-feedback-tone="success"]')).to_be_visible()
            matrix("success")
            proof["checks"].append(
                "real false and true editorial responses use distinct screen states"
            )
            assert (
                page.locator('[data-feedback-tone="success"]').inner_text().find("official score")
                == -1
            )
            navigation_epoch += 1
            page.reload(wait_until="networkidle")
            expect(page.locator('[data-feedback-tone="success"]')).to_be_visible()
            proof["checks"].append("confirmed response survives reload")
            assert not proof["page_errors"]
            # Next development cleanup/navigation can cancel duplicate API or
            # chunk reads. A cancelled GET must cross an observed navigation or
            # have an exact-path 200 counterpart. Failed writes, missing assets
            # and non-cancellation network errors are never waived.
            for failure, exact_path in failed_get_paths:
                assert failure["failure"] == "net::ERR_ABORTED" and failure["method"] == "GET"
                if failure["navigation_changed"]:
                    failure["classification"] = "cancelled GET across observed navigation"
                else:
                    assert exact_path in successful_gets
                    failure["classification"] = "cancelled GET with exact-path 200 counterpart"
            proof["status"] = "passed"
        except Exception as error:
            proof["status"] = "failed"
            proof["stage"] = stage
            proof["error_type"] = type(error).__name__
            try:
                proof["alerts"] = page.get_by_role("alert").all_text_contents()
            except Exception:
                proof["alerts_unavailable"] = True
            proof["script_line"] = next(
                (
                    frame.lineno
                    for frame in reversed(traceback.extract_tb(error.__traceback__))
                    if Path(frame.filename) == Path(__file__)
                ),
                None,
            )
            if stage != "sign-in":
                try:
                    page.screenshot(path=str(output / "failure.png"))
                    proof["visible_text"] = page.locator("main").inner_text()[:1800]
                except Exception:
                    proof["failure_view_unavailable"] = True
        finally:
            browser.close()
    (output / "proof.json").write_text(json.dumps(proof, indent=2), encoding="utf-8")
    print(json.dumps({"status": proof["status"], "stage": stage, "evidence": str(output)}))
    return 0 if proof["status"] == "passed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
