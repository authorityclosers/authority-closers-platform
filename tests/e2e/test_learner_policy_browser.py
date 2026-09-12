"""Read-only policy and signup presentation at phone and desktop widths."""

from __future__ import annotations

import json
import os
from collections.abc import Iterator
from pathlib import Path
from urllib.parse import urlsplit

import pytest

pytest.importorskip("playwright.sync_api")
from playwright.sync_api import Browser, Route, expect, sync_playwright  # noqa: E402

POLICY_VERSION = "ac-learner-terms-privacy-2026-09-13-v1"


@pytest.fixture(scope="module")
def policy_browser() -> Iterator[Browser]:
    if not os.getenv("AC_LEARNER_E2E_BASE_URL"):
        pytest.skip("set AC_LEARNER_E2E_BASE_URL to run the browser regression")
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        try:
            yield browser
        finally:
            browser.close()


@pytest.mark.e2e
@pytest.mark.parametrize("width", [320, 1440])
@pytest.mark.parametrize("path", ["terms", "privacy", "register"])
def test_published_policies_and_consent_reflow(
    policy_browser: Browser, width: int, path: str
) -> None:
    base_url = os.environ["AC_LEARNER_E2E_BASE_URL"].rstrip("/")
    origin = urlsplit(base_url)
    context = policy_browser.new_context(
        viewport={"width": width, "height": 1024}, service_workers="block"
    )
    blocked: list[str] = []

    def reads_only(route: Route) -> None:
        url = urlsplit(route.request.url)
        if route.request.method not in {"GET", "HEAD", "OPTIONS"} or (url.scheme, url.netloc) != (
            origin.scheme,
            origin.netloc,
        ):
            blocked.append(f"{route.request.method} {url.path}")
            route.abort()
        else:
            route.continue_()

    context.route("**/*", reads_only)
    page = context.new_page()
    try:
        page.goto(f"{base_url}/{path}", wait_until="domcontentloaded")
        expect(page.locator("h1")).to_have_count(1)
        if path == "register":
            consent = page.get_by_role("checkbox", name="I am 18 or older")
            expect(consent).to_be_enabled()
            expect(consent).not_to_be_checked()
            expect(page.get_by_role("button", name="Continue with Google")).to_be_disabled()
            expect(page.locator('input[name="consent_version"]')).to_have_value(POLICY_VERSION)
            expect(page.locator('label a[href="/terms"]')).to_be_visible()
            expect(page.locator('label a[href="/privacy"]')).to_be_visible()
        else:
            expect(page.locator(".policy-hero__status")).to_contain_text(POLICY_VERSION)
            expect(page.locator(".policy-hero__status")).to_contain_text("13 September 2026")
            expect(page.locator('a[href="mailto:admin@authorityclosers.com"]')).to_be_visible()
            expect(page.locator(".policy-copy > section")).to_have_count(
                8 if path == "terms" else 9
            )
            expect(page.locator("main")).not_to_contain_text("Staging test document")
        page.evaluate("document.fonts.ready")
        geometry = page.evaluate(
            """() => ({
              viewport: innerWidth,
              document: Math.max(document.documentElement.scrollWidth, document.body.scrollWidth),
              overflowing: [...document.querySelectorAll(
                'main h1, .policy-copy p, .policy-copy h2, .policy-hero__status strong, '
                + '.policy-contact a, label'
              )].filter(e => {
                const r = e.getBoundingClientRect();
                return r.width > 0 && (r.left < -1 || r.right > innerWidth + 1
                  || e.scrollWidth > e.clientWidth + 1);
              }).map(e => e.tagName + ':' + e.className)
            })"""
        )
        evidence = os.getenv("AC_LEARNER_POLICY_EVIDENCE_DIR")
        if evidence:
            output = Path(evidence)
            output.mkdir(parents=True, exist_ok=True)
            image = output / f"{path}-{width}.png"
            proof = output / f"{path}-{width}.json"
            if image.exists() or proof.exists():
                raise FileExistsError("Use a fresh AC_LEARNER_POLICY_EVIDENCE_DIR")
            proof.write_text(
                json.dumps({"geometry": geometry, "blockedRequests": blocked}, indent=2) + "\n",
                encoding="utf-8",
            )
            page.screenshot(path=str(image), full_page=True)
        assert not blocked, f"Unexpected requests blocked: {blocked}"
        assert geometry["document"] <= width + 1, geometry
        assert not geometry["overflowing"], geometry
    finally:
        context.close()
