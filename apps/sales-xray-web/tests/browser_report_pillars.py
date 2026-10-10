"""Fictional Report screen proof; no customer data or API requests."""

import json
import os
from pathlib import Path
from urllib.parse import urlsplit

from playwright.sync_api import expect, sync_playwright

BASE = os.environ["SALES_XRAY_BASE_URL"].rstrip("/")
OUT = Path(os.environ["SALES_XRAY_UX_EVIDENCE_DIR"])
LABELS = [
    "The Big Picture",
    "How the Call Played Out",
    "What Worked & What Didn't",
    "Moments That Mattered",
    "Your Skills on This Call",
    "Where the Deal Stands",
]


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    failures, external, proof = [], [], []
    expect.set_options(timeout=30000)
    with sync_playwright() as runtime:
        browser = runtime.chromium.launch(headless=True)
        for width, height in [(390, 844), (1440, 900)]:
            page = browser.new_page(viewport={"width": width, "height": height})
            page.on("pageerror", lambda e: failures.append(str(e)))

            def boundary(route):
                if urlsplit(route.request.url).netloc != urlsplit(BASE).netloc:
                    external.append(urlsplit(route.request.url).netloc)
                    route.abort()
                else:
                    route.continue_()

            page.route("**/*", boundary)
            assert (
                page.goto(f"{BASE}/review-fixture/report/pillars", wait_until="networkidle").status
                == 200
            )
            headings = page.locator("[data-report-mode-section] h2")
            assert headings.all_text_contents() == LABELS
            skills = page.locator('[data-report-pillar="skills"] > details[class*="skill"]')
            assert skills.count() == 8
            assert skills.evaluate_all("items => items.every(item => !item.open)")
            expect(page.locator("[data-report-modes]")).not_to_contain_text(
                "Practice before the next call"
            )
            expect(page.locator("[data-report-modes]")).to_contain_text(
                "Not established in this report."
            )
            source = page.locator('[data-report-pillar="moments"] details').first
            source.locator("summary").click()
            source.locator("button").first.click()
            expect(page.get_by_role("status")).to_contain_text(
                "Understood. I won't schedule a follow-up."
            )
            page.get_by_title("Tabbed view", exact=True).click()
            page.get_by_role("tab", name="Your Skills on This Call", exact=True).click()
            expect(page.locator('[data-report-mode-section="skills"]')).to_be_visible()
            assert page.evaluate("document.documentElement.scrollWidth <= innerWidth + 1")
            page.get_by_title("Reading view", exact=True).click()
            page.evaluate("window.scrollTo(0, 0)")
            for theme in ["light", "dark"]:
                page.locator("html").evaluate(
                    "(element, theme) => element.setAttribute('data-theme', theme)", theme
                )
                page.screenshot(path=str(OUT / f"pillars-{width}-{theme}.png"))
                assert page.evaluate("document.documentElement.scrollWidth <= innerWidth + 1")
            proof.append(
                {
                    "width": width,
                    "pillars": 6,
                    "skills": 8,
                    "source_selection": True,
                    "no_overflow": True,
                }
            )
            page.close()
        browser.close()
    assert not failures, failures
    assert not external, external
    (OUT / "browser-proof.json").write_text(
        json.dumps(
            {"checks": proof, "page_errors": failures, "external_requests": external}, indent=2
        )
    )
    print(json.dumps(proof))


if __name__ == "__main__":
    main()
