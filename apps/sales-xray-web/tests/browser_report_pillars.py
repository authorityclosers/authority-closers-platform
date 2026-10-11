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
            page = browser.new_page(
                viewport={"width": width, "height": height},
                reduced_motion="reduce",
                is_mobile=width == 390,
                has_touch=width == 390,
            )
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
            page.get_by_role("tab", name="Sales skills", exact=True).click()
            expect(page.locator('[data-report-mode-section="skills"]')).to_be_visible()
            assert page.evaluate("document.documentElement.scrollWidth <= innerWidth + 1")
            page.get_by_title("Reading view", exact=True).click()
            expect(page.locator("[data-report-modes]")).to_contain_text("Synthetic call:")
            page.get_by_title("Story view", exact=True).click()
            assert headings.all_text_contents() == LABELS
            skills.first.locator("summary").click()
            expect(skills.first.get_by_role("link", name="Get coaching on this")).to_have_attribute(
                "href", "/coaching?focus=human_connection_trust"
            )
            skills.first.locator("summary").click()
            page.get_by_title("Coaching view", exact=True).click()
            coaching = page.locator("[data-call-coaching]")
            expect(coaching).to_be_visible()
            expect(coaching).to_contain_text("Your next-call mission")
            expect(
                page.get_by_role("heading", name="Coaching for this call", exact=True)
            ).to_be_visible()
            expect(coaching.get_by_role("link", name="My coaching across calls")).to_be_visible()
            assert page.evaluate("document.documentElement.scrollWidth <= innerWidth + 1")
            page.evaluate("window.scrollTo(0, 0)")
            if width == 390:
                assert page.get_by_title("Coaching view", exact=True).evaluate(
                    "el => { const r = el.getBoundingClientRect(); "
                    "return r.height >= 44 && r.width >= 44; }"
                )
                assert coaching.locator("button").evaluate_all(
                    "items => items.every(el => el.getBoundingClientRect().height >= 44)"
                )
            for theme in ["light", "dark"]:
                page.locator("html").evaluate(
                    "(element, theme) => element.setAttribute('data-theme', theme)", theme
                )
                page.screenshot(path=str(OUT / f"call-coaching-{width}-{theme}.png"))
            page.get_by_title("Story view", exact=True).click()
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
                    "call_coaching": True,
                    "no_overflow": True,
                }
            )
            page.goto(f"{BASE}/review-fixture/report", wait_until="networkidle")
            page.get_by_title("Tabbed view", exact=True).click()
            page.get_by_role("tab", name="Prospect", exact=True).click()
            signal = page.locator("[data-prospect-index]").first
            expect(signal).to_be_visible()
            assert signal.locator("[data-prospect-part]").count() == 3
            expect(signal).to_contain_text("A guess, not a fact")
            for theme in ["light", "dark"]:
                page.locator("html").evaluate(
                    "(element, theme) => element.setAttribute('data-theme', theme)", theme
                )
                page.screenshot(path=str(OUT / f"prospect-flat-{width}-{theme}.png"))
                assert page.evaluate("document.documentElement.scrollWidth <= innerWidth + 1")
            page.goto(f"{BASE}/review-fixture/report/pillars", wait_until="networkidle")
            for kind in ["won", "lost"]:
                page.get_by_role("button", name=f"Simulate {kind} analysis", exact=True).click()
                picture = page.locator('[data-report-pillar="overview"]')
                expect(picture).to_contain_text("Call outcome")
                expect(picture.locator('[data-gap="true"]').first).to_contain_text("Unknown")
                expect(picture).to_contain_text("Closing evidence")
                expect(picture.get_by_text("Won", exact=True)).to_have_count(0)
                expect(picture.get_by_text("Lost", exact=True)).to_have_count(0)
                status = page.locator('[data-report-pillar="facts"] [data-gap="true"]').first
                expect(status).to_contain_text("Current status")
                expect(status).to_contain_text("Unknown")
                closing = (
                    picture.locator("div")
                    .filter(has=page.get_by_role("heading", name="Closing evidence", exact=True))
                    .first
                )
                disclosure = closing.locator("details")
                if disclosure.get_attribute("open") is None:
                    disclosure.locator("summary").click()
                expect(closing.locator("blockquote")).to_have_text(
                    "Understood. I won't schedule a follow-up."
                )
                expect(disclosure.locator("summary")).to_contain_text("00:31")
                closing.get_by_role("button").click()
                expect(page.get_by_role("status")).to_contain_text(
                    "Understood. I won't schedule a follow-up."
                )
                page.evaluate("window.scrollTo(0, 0)")
                for theme in ["light", "dark"]:
                    page.locator("html").evaluate(
                        "(element, theme) => element.setAttribute('data-theme', theme)", theme
                    )
                    page.screenshot(path=str(OUT / f"analysis-{kind}-{width}-{theme}.png"))
                    assert page.evaluate("document.documentElement.scrollWidth <= innerWidth + 1")
            proof[-1]["human_outcome_boundary"] = True
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
