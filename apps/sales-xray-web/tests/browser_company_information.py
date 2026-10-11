"""Read-only company presentation: invented source/identities; no persistence API."""

import json
import os
from pathlib import Path
from urllib.parse import urlsplit

from playwright.sync_api import expect, sync_playwright

BASE = os.environ["SALES_XRAY_BASE_URL"].rstrip("/")
OUT = Path(os.environ["SALES_XRAY_UX_EVIDENCE_DIR"])


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    errors, outside, reads, proof = [], [], [], []
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
                elif address.path.startswith("/v1/conversation/companies"):
                    reads.append(address.path)
                    route.fulfill(status=404, json={"detail": "Fictional missing API."})
                elif address.path.startswith("/v1/"):
                    route.fulfill(status=401, json={"detail": "Fictional preview only."})
                else:
                    route.continue_()

            page.route("**/*", boundary)
            assert page.goto(BASE + "/review-fixture/prospects/companies").status == 200
            if width == 390:
                assert page.get_by_role("button", name="Show unavailable").evaluate(
                    "el => el.getBoundingClientRect().height >= 44"
                )
            companies = page.get_by_role("region", name="Companies", exact=True)
            button = companies.get_by_role("button")
            if width == 390:
                assert button.evaluate("el => el.getBoundingClientRect().height >= 44")
            button.click()
            profile = page.get_by_role("region", name="Company information")
            expect(profile.locator("dt")).to_have_count(4)
            expect(profile).to_contain_text("Person edit · locked")
            expect(profile).to_contain_text("CityUnknown")
            expect(profile).to_contain_text("Business sizeUnknown")
            source = profile.locator("summary").first
            source.click()
            expect(profile.locator("blockquote")).to_contain_text(
                "Fictional व्यवसाय manufactures test parts."
            )
            expect(profile.get_by_role("link", name="Fictional person")).to_have_attribute(
                "href", "/prospects/00000000-0000-0000-0000-000000000013"
            )
            assert page.evaluate("document.documentElement.scrollWidth <= innerWidth + 1")
            if width == 390:
                assert profile.locator("summary, a").evaluate_all(
                    "items => items.every(el => el.getBoundingClientRect().height >= 44)"
                )
            for theme in ["light", "dark"]:
                page.locator("html").evaluate(
                    "(el, theme) => el.setAttribute('data-theme', theme)", theme
                )
                page.screenshot(path=str(OUT / f"company-{width}-{theme}.png"))
            assert len(reads) == len(proof), "Preloaded Company pages must not read again."
            page.get_by_role("button", name="Show unavailable").click()
            notice = page.get_by_role("alert").filter(has_text="Companies are unavailable")
            expect(notice).to_be_visible()
            expect(page.get_by_role("region", name="Company information")).to_have_count(0)
            expect(page.get_by_text("No companies recorded yet.")).to_have_count(0)
            notice.get_by_role("button", name="Try again").click()
            expect(notice).to_be_visible()
            assert len(reads) == len(proof) + 1
            assert page.evaluate("document.documentElement.scrollWidth <= innerWidth + 1")
            if width == 390:
                assert notice.get_by_role("button").evaluate(
                    "el => el.getBoundingClientRect().height >= 44"
                )
            page.screenshot(path=str(OUT / f"company-unavailable-{width}.png"))
            proof.append(
                {
                    "width": width,
                    "list_to_profile": True,
                    "unknown_and_lock": True,
                    "explicit_person": True,
                    "source": True,
                    "preload_no_second_read": True,
                    "missing_api_retry": True,
                }
            )
            page.close()
        browser.close()
    assert not errors, errors
    assert not outside, outside
    (OUT / "browser-proof.json").write_text(json.dumps(proof))
    print(json.dumps(proof))


if __name__ == "__main__":
    main()
