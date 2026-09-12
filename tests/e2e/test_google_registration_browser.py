"""Browser regression for the consent-gated learner Google registration path."""

from __future__ import annotations

import os
from urllib.parse import parse_qs, urlencode, urlsplit

import pytest

pytest.importorskip("playwright.sync_api")
from playwright.sync_api import Route, expect, sync_playwright  # noqa: E402


@pytest.mark.e2e
@pytest.mark.parametrize("course", [None, "authority-closers-free-course"])
def test_register_page_submits_explicit_google_consent(course: str | None) -> None:
    base_url = os.getenv("AC_LEARNER_E2E_BASE_URL")
    if not base_url:
        pytest.skip("set AC_LEARNER_E2E_BASE_URL to run the browser regression")

    submitted_url: str | None = None
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        try:
            page = browser.new_page()

            def capture_google_start(route: Route) -> None:
                nonlocal submitted_url
                assert route.request.method == "GET"
                submitted_url = route.request.url
                route.fulfill(status=204)

            page.route("**/v1/auth/google/start**", capture_google_start)
            suffix = "?" + urlencode({"course": course}) if course else ""
            page.goto(f"{base_url.rstrip('/')}/register{suffix}")

            google_form = page.locator('form[action*="action=register"]')
            consent = page.get_by_role("checkbox", name="I confirm")
            google_button = google_form.get_by_role("button", name="Continue with Google")
            assert consent.is_visible()
            assert google_button.is_visible()
            assert google_button.is_disabled()
            assert submitted_url is None

            expect(consent).to_be_enabled()
            consent.check()
            expect(consent).to_be_checked()
            expect(google_button).to_be_enabled()
            consent.uncheck()
            expect(consent).not_to_be_checked()
            expect(google_button).to_be_disabled()
            assert submitted_url is None
            consent.check()
            expect(google_button).to_be_enabled()
            google_button.click()

            assert submitted_url is not None
            submitted = urlsplit(submitted_url)
            assert submitted.netloc == urlsplit(base_url).netloc
            assert submitted.path == "/v1/auth/google/start"
            assert parse_qs(submitted.query) == {
                "action": ["register"],
                "surface": ["learner"],
                "consent": ["true"],
                "return_path": ["/onboarding" + suffix],
            }
        finally:
            browser.close()


@pytest.mark.e2e
def test_registration_keeps_credentials_inert_without_javascript() -> None:
    base_url = os.getenv("AC_LEARNER_E2E_BASE_URL")
    if not base_url:
        pytest.skip("set AC_LEARNER_E2E_BASE_URL to run the browser regression")

    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        try:
            page = browser.new_page(java_script_enabled=False)
            page.goto(f"{base_url.rstrip('/')}/register", wait_until="domcontentloaded")
            password_form = page.locator("form").first
            expect(password_form).to_have_attribute("method", "post")
            for name in ("firstName", "email", "whatsappNumber", "password", "consent"):
                expect(password_form.locator(f'input[name="{name}"]')).to_be_disabled()
            expect(page.get_by_role("button", name="Show password")).to_be_disabled()
            expect(page.get_by_role("button", name="Create free account")).to_be_disabled()
            expect(page.get_by_role("button", name="Continue with Google")).to_be_disabled()
        finally:
            browser.close()
