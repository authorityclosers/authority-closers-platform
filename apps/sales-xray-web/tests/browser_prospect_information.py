"""Fictional six-section Prospect Information proof; no API or external requests."""

import json
import os
from pathlib import Path
from urllib.parse import urlsplit

from playwright.sync_api import expect, sync_playwright

BASE = os.environ["SALES_XRAY_BASE_URL"].rstrip("/")
OUT = Path(os.environ["SALES_XRAY_UX_EVIDENCE_DIR"])


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    failures, external, api, proof = [], [], [], []
    with sync_playwright() as runtime:
        browser = runtime.chromium.launch(headless=True)
        for width, height in [(390, 844), (1440, 900)]:
            page = browser.new_page(viewport={"width": width, "height": height})
            page.on("pageerror", lambda e: failures.append(str(e)))

            def boundary(route):
                url = urlsplit(route.request.url)
                if url.netloc != urlsplit(BASE).netloc:
                    external.append(url.netloc)
                    route.abort()
                elif url.path.startswith("/v1/"):
                    api.append(url.path)
                    route.abort()
                else:
                    route.continue_()

            page.route("**/*", boundary)
            assert (
                page.goto(f"{BASE}/review-fixture/prospects", wait_until="networkidle").status
                == 200
            )
            sections = page.locator("[data-prospect-section]")
            assert sections.count() == 6
            assert sections.nth(0).locator("h2").inner_text() == "What You Need to Know Now"
            assert sections.nth(1).get_attribute("open") is None
            company = page.locator('[data-fact-label="Contradiction"]').first
            expect(company.locator("dd")).to_have_text("Example company")
            company.locator("summary").click()
            expect(company).to_contain_text("Example company two.")
            expect(company).to_contain_text("Person edit · locked")
            sections.nth(2).locator(":scope > summary").click()
            expect(sections.nth(2)).to_contain_text("Approximately [2–3) lakh INR per year")
            expect(sections.nth(2)).to_contain_text("Ability to investUnknown")
            for theme in ["light", "dark"]:
                page.evaluate("window.scrollTo(0, 0)")
                page.locator("html").evaluate(
                    "(element, theme) => element.setAttribute('data-theme', theme)", theme
                )
                page.screenshot(path=str(OUT / f"prospect-{width}-{theme}.png"))
                assert page.evaluate("document.documentElement.scrollWidth <= innerWidth + 1")
            proof.append(
                {"width": width, "sections": 6, "locked_value_retained": True, "no_overflow": True}
            )
            page.close()
        browser.close()
    assert not failures, failures
    assert not external, external
    assert not api, api
    (OUT / "browser-proof.json").write_text(
        json.dumps(
            {
                "checks": proof,
                "page_errors": failures,
                "external_requests": external,
                "api_requests": api,
            },
            indent=2,
        )
    )
    print(json.dumps(proof))


if __name__ == "__main__":
    main()
