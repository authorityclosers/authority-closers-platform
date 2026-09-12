"""Browser regression for the consent-gated learner Google registration path."""

from __future__ import annotations

import os
from urllib.parse import parse_qs, urlencode, urlsplit

import pytest

try:
    from playwright.sync_api import Browser, Page, Route, expect, sync_playwright
except ImportError:
    if os.getenv("AC_REQUIRE_GOOGLE_REGISTRATION_BROWSER_TEST") == "1":
        raise RuntimeError("Playwright is required for the registration browser gate") from None
    pytest.skip("Playwright is unavailable", allow_module_level=True)


def _browser_base_url() -> str:
    raw = os.getenv("AC_LEARNER_E2E_BASE_URL")
    required = os.getenv("AC_REQUIRE_GOOGLE_REGISTRATION_BROWSER_TEST") == "1"
    if not raw:
        if required:
            pytest.fail("The registration browser gate requires its loopback URL")
        pytest.skip("set AC_LEARNER_E2E_BASE_URL to run the browser regression")
    if required and raw != "http://127.0.0.1:3181":
        pytest.fail("The required registration browser gate permits only its exact loopback URL")
    return raw.rstrip("/")


def _route_request(route: Route, base_url: str, captured: list[str], blocked: list[str]) -> None:
    request = route.request
    target, base = urlsplit(request.url), urlsplit(base_url)
    if (target.scheme, target.netloc) != (base.scheme, base.netloc) or request.method not in {
        "GET",
        "HEAD",
        "OPTIONS",
    }:
        blocked.append(f"{request.method} {target.netloc}{target.path}")
        route.abort()
    elif target.path == "/v1/auth/google/start":
        if request.method != "GET":
            blocked.append(f"{request.method} {target.path}")
            route.abort()
            return
        captured.append(request.url)
        route.fulfill(status=204)
    else:
        route.continue_()


def _registration_page(
    browser: Browser, base_url: str, *, javascript: bool = True
) -> tuple[Page, list[str], list[str]]:
    context = browser.new_context(java_script_enabled=javascript, service_workers="block")
    captured: list[str] = []
    blocked: list[str] = []
    context.route("**/*", lambda route: _route_request(route, base_url, captured, blocked))
    return context.new_page(), captured, blocked


@pytest.mark.e2e
@pytest.mark.parametrize("course", [None, "authority-closers-free-course"])
def test_register_page_submits_explicit_google_consent(course: str | None) -> None:
    base_url = _browser_base_url()

    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        try:
            page, submitted_urls, blocked = _registration_page(browser, base_url)
            suffix = "?" + urlencode({"course": course}) if course else ""
            page.goto(f"{base_url.rstrip('/')}/register{suffix}")

            google_form = page.locator('form[action*="action=register"]')
            consent = page.get_by_role("checkbox", name="I confirm")
            google_button = google_form.get_by_role("button", name="Continue with Google")
            assert consent.is_visible()
            assert google_button.is_visible()
            assert google_button.is_disabled()
            assert submitted_urls == []

            expect(consent).to_be_enabled()
            consent.check()
            expect(consent).to_be_checked()
            expect(google_button).to_be_enabled()
            consent.uncheck()
            expect(consent).not_to_be_checked()
            expect(google_button).to_be_disabled()
            assert submitted_urls == []
            consent.check()
            expect(google_button).to_be_enabled()
            google_button.click()

            assert len(submitted_urls) == 1
            assert blocked == []
            submitted = urlsplit(submitted_urls[0])
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
    base_url = _browser_base_url()

    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        try:
            page, submitted_urls, blocked = _registration_page(browser, base_url, javascript=False)
            page.goto(f"{base_url.rstrip('/')}/register", wait_until="domcontentloaded")
            password_form = page.locator("form").first
            expect(password_form).to_have_attribute("method", "post")
            for name in ("firstName", "email", "whatsappNumber", "password", "consent"):
                expect(password_form.locator(f'input[name="{name}"]')).to_be_disabled()
            expect(page.get_by_role("button", name="Show password")).to_be_disabled()
            expect(page.get_by_role("button", name="Create free account")).to_be_disabled()
            expect(page.get_by_role("button", name="Continue with Google")).to_be_disabled()
            assert submitted_urls == []
            assert blocked == []
        finally:
            browser.close()
