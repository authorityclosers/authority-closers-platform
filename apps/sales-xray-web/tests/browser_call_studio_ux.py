"""Mounted-route smoke proof for the bounded Sales Xray UX slice.

This exercises the actual Next route with the analysis API unavailable. It
checks that the language control is usable, interface labels change without
claiming translated report content, and the 320px layout remains mounted.
"""

from pathlib import Path

from playwright.sync_api import sync_playwright


BASE_URL = "http://127.0.0.1:3016"
SCREENSHOT = Path(r"D:\AC-authority-closers-release-audit\sales-xray-live-ux-20260913.png")


def main() -> None:
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        page = browser.new_page(viewport={"width": 1280, "height": 900})
        page.route(
            "**/v1/me/workspaces",
            lambda route: route.fulfill(
                status=200,
                content_type="application/json",
                body='{"person_id":"person-1","session_id":"session-1","selected_tenant_id":"tenant-1","workspaces":[{"tenant_id":"tenant-1","name":"Synthetic QA workspace"}]}',
            ),
        )
        page.route(
            "**/v1/conversation/workspace",
            lambda route: route.fulfill(
                status=200,
                content_type="application/json",
                body='{"intake_enabled":true,"authenticated":true,"sign_in_url":null,"message":"Synthetic QA workspace ready."}',
            ),
        )
        page.route(
            "**/v1/conversation/recordings",
            lambda route: route.fulfill(
                status=200,
                content_type="application/json",
                body='{"recordings":[]}',
            ),
        )
        page.goto(BASE_URL, wait_until="networkidle")
        page.wait_for_timeout(350)

        language = page.locator(".studio-language-control select")
        assert language.count() == 1
        assert "Upload your call" in page.locator(".studio-steps").inner_text()
        assert page.get_by_text("Start with your sales call", exact=True).count() == 1

        for mode, expected_step in (
            ("en", "Upload your call"),
            ("hi", "कॉल अपलोड करें"),
            ("mr", "कॉल अपलोड करा"),
            ("en-hi-mixed", "Upload कॉल करें"),
        ):
            language.select_option(mode)
            assert expected_step in page.locator(".studio-steps").inner_text()
        language.select_option("hi")
        assert page.get_by_text("हिन्दी · देवनागरी", exact=True).count() >= 1

        page.set_viewport_size({"width": 320, "height": 780})
        page.wait_for_timeout(100)
        assert page.locator("main#main").is_visible()
        SCREENSHOT.parent.mkdir(parents=True, exist_ok=True)
        page.screenshot(path=str(SCREENSHOT), full_page=True)

        browser.close()


if __name__ == "__main__":
    main()
