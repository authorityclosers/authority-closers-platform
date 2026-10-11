"""Shared-dev native nullable Report proof; invented source data only."""

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
    failures, external, api_reads, proof = [], [], [], []
    expect.set_options(timeout=30000)
    with sync_playwright() as runtime:
        browser = runtime.chromium.launch(headless=True)
        try:
            for width, height in [(1440, 900), (390, 844)]:
                page = browser.new_page(
                    viewport={"width": width, "height": height},
                    reduced_motion="reduce",
                    is_mobile=width == 390,
                    has_touch=width == 390,
                )
                page.on("pageerror", lambda error: failures.append(str(error)))

                def boundary(route):
                    url = urlsplit(route.request.url)
                    if url.netloc != urlsplit(BASE).netloc:
                        external.append(url.netloc)
                        route.abort()
                    elif url.path.startswith(("/api/", "/v1/")):
                        api_reads.append(url.path)
                        route.abort()
                    else:
                        route.continue_()

                page.route("**/*", boundary)
                response = page.goto(
                    f"{BASE}/review-fixture/report/legacy", wait_until="networkidle"
                )
                assert response.status == 200
                expect(page.locator("[data-nullable-report]")).to_be_visible()
                assert page.locator("[data-report-mode-section] h2").all_text_contents() == LABELS
                skills = page.locator('[data-report-pillar="skills"] > details[class*="skill"]')
                assert skills.count() == 8
                assert skills.evaluate_all("items => items.every(item => !item.open)")
                skill_panel = page.locator('[data-report-pillar="skills"]')
                expect(skill_panel).not_to_contain_text("Strongly Demonstrated")
                expect(skill_panel).not_to_contain_text("Needs Attention")
                expect(page.locator('[data-report-pillar="overview"]')).to_contain_text("Unknown")
                moments = page.locator('[data-report-pillar="moments"] details')
                assert moments.count() > 0
                source = moments.first
                source.locator("summary").click()
                quote = source.locator("blockquote").inner_text()
                assert quote.strip()
                source.get_by_role("button").first.click()
                expect(page.get_by_role("status")).to_contain_text(quote)
                source.locator("summary").click()
                page.evaluate("window.scrollTo(0, 0)")
                for theme in ["light", "dark"]:
                    page.locator("html").evaluate(
                        "(element, theme) => element.setAttribute('data-theme', theme)", theme
                    )
                    assert page.evaluate("document.documentElement.scrollWidth <= innerWidth + 1")
                    page.screenshot(path=str(OUT / f"legacy-report-{width}-{theme}.png"))
                page.get_by_title("Reading view", exact=True).click()
                expect(page.locator('[data-report-mode-section="overview"]')).to_be_visible()
                page.get_by_title("Document view", exact=True).click()
                document = page.get_by_role("region", name="Sales Xray document preview")
                expect(document).to_be_visible()
                expect(document).to_contain_text("The Big Picture")
                proof.append(
                    {
                        "width": width,
                        "nullable_native_parser": True,
                        "pillars": 6,
                        "skills": 8,
                        "no_invented_skill_state": True,
                        "literal_source_selection": True,
                        "retained_reading_and_document": True,
                        "no_overflow": True,
                    }
                )
                page.close()
        finally:
            browser.close()
    assert not failures, failures
    assert not external, external
    assert not api_reads, api_reads
    receipt = {"origin": BASE, "proof": proof, "page_errors": failures, "api_reads": api_reads}
    (OUT / "legacy-report-receipt.json").write_text(json.dumps(receipt, indent=2))
    print(json.dumps(receipt))


if __name__ == "__main__":
    main()
