"""Opt-in companion to the app-root browser journeys; public config only, no session."""

from __future__ import annotations

import os
from pathlib import Path
from urllib.parse import urlsplit

import pytest
from playwright.sync_api import expect, sync_playwright

pytestmark = pytest.mark.e2e


def test_app_root_update_card(tmp_path: Path) -> None:
    origin = os.environ.get("WB_BASE_URL", "").rstrip("/")
    if not origin:
        pytest.skip("Set WB_BASE_URL to an existing dev workbench for this root journey")
    host = urlsplit(origin).hostname
    assert host in {"127.0.0.1", "localhost", "salesxray-dev.authorityclosers.com"}
    config = {
        "min_app_version": {"android": "999.0.0", "ios": "0.0.0", "desktop": "0.0.0"},
        "recommended_app_version": {"android": "999.0.0", "ios": "0.0.0", "desktop": "0.0.0"},
        "features_off": [],
        "message": None,
    }
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        try:
            context = browser.new_context(
                viewport={"width": 363, "height": 735},
                user_agent="Mozilla/5.0 (Linux; Android 14) SalesXrayApp/1.0.0",
                service_workers="block",
            )
            # Fictional config is the only mocked API; never send a customer session.
            context.route("**/v1/app/config", lambda route: route.fulfill(json=config))
            page = context.new_page()
            page.goto(origin + "/login/", wait_until="domcontentloaded")
            expect(
                page.get_by_role("heading", name="Update Sales X-Ray", exact=True)
            ).to_be_visible()
            expect(page.get_by_role("button", name="Not now", exact=True)).to_have_count(0)
            expect(page.get_by_role("link", name="Open Google Play")).to_have_attribute(
                "href",
                "https://play.google.com/store/apps/details?id=com.authorityclosers.salesxray",
            )
            assert page.evaluate("document.documentElement.scrollWidth <= innerWidth")
            page.screenshot(path=str(tmp_path / "update-card-363x735.png"))
        finally:
            browser.close()
