"""Browser regression for the consent-gated learner Google registration path."""

from __future__ import annotations

import os

import pytest

pytest.importorskip("playwright.sync_api")
from playwright.sync_api import Route, sync_playwright  # noqa: E402


@pytest.mark.e2e
def test_register_page_submits_explicit_google_consent() -> None:
    base_url = os.getenv("AC_LEARNER_E2E_BASE_URL")
    if not base_url:
        pytest.skip("set AC_LEARNER_E2E_BASE_URL to run the browser regression")

    submitted_url: str | None = None
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        page = browser.new_page()

        def capture_google_start(route: Route) -> None:
            nonlocal submitted_url
            submitted_url = route.request.url
            route.fulfill(status=204)

        page.route("**/v1/auth/google/start**", capture_google_start)
        page.goto(f"{base_url.rstrip('/')}/register")

        google_form = page.locator('form[action*="action=register"]')
        consent = google_form.get_by_role("checkbox", name="I confirm")
        assert consent.is_visible()
        assert google_form.get_by_role("button", name="Continue with Google").is_visible()

        consent.check()
        google_form.get_by_role("button", name="Continue with Google").click()

        assert submitted_url is not None
        assert "action=register" in submitted_url
        assert "surface=learner" in submitted_url
        assert "consent=true" in submitted_url
        browser.close()
