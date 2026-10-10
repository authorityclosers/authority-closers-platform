"""Fictional own-call API bootstrap; no real account or deployed read."""

import json
import os
from pathlib import Path
from urllib.parse import urlsplit

from playwright.sync_api import expect, sync_playwright

BASE = os.environ["SALES_XRAY_BASE_URL"].rstrip("/")
OUT = Path(os.environ["SALES_XRAY_UX_EVIDENCE_DIR"])


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    errors, outside, api, proof = [], [], [], []
    with sync_playwright() as runtime:
        browser = runtime.chromium.launch(headless=True)
        for width, height in [(390, 844), (1440, 900)]:
            page = browser.new_page(
                viewport={"width": width, "height": height}, reduced_motion="reduce"
            )
            page.on("pageerror", lambda error: errors.append(str(error)))

            def boundary(route):
                address = urlsplit(route.request.url)
                if address.netloc != urlsplit(BASE).netloc:
                    outside.append(address.netloc)
                    route.abort()
                elif address.path.startswith("/v1/"):
                    api.append(address.path)
                    route.abort()
                else:
                    route.continue_()

            page.route("**/*", boundary)
            assert page.goto(BASE + "/review-fixture/report/coaching").status == 200
            coaching = page.locator('[data-call-coaching][data-state="ready"]')
            expect(coaching).to_be_visible()
            expect(coaching).to_contain_text("Fictional API focus")
            expect(coaching).to_contain_text("Your next-call mission")
            expect(coaching.get_by_role("link", name="My coaching across calls")).to_be_visible()
            coaching.locator("button").first.click()
            expect(page.get_by_role("status")).to_contain_text("ms ·")
            lesson = coaching.locator("details").first
            lesson.locator("summary").click()
            expect(lesson).to_contain_text("not words from the call")
            expect(lesson.locator("ol li").first).to_be_visible()
            assert page.evaluate("document.documentElement.scrollWidth <= innerWidth + 1")
            if width == 390:
                assert coaching.locator("button, summary").evaluate_all(
                    "items => items.every(el => el.getBoundingClientRect().height >= 44)"
                )
            lesson.locator("summary").click()
            for theme in ["light", "dark"]:
                page.locator("html").evaluate(
                    "(el, theme) => el.setAttribute('data-theme', theme)", theme
                )
                page.evaluate("window.scrollTo(0, 0)")
                page.screenshot(path=str(OUT / f"call-coaching-{width}-{theme}.png"))
            proof.append({"width": width, "bootstrap": True, "source": True, "lesson": True})
            page.close()
        browser.close()
    assert not errors, errors
    assert not outside, outside
    assert not api, api
    (OUT / "browser-proof.json").write_text(json.dumps({"checks": proof, "api_reads": 0}))
    print(json.dumps(proof))


if __name__ == "__main__":
    main()
