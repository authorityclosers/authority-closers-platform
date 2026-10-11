"""Human-only outcome controls: absent persistence must never claim a saved fact."""

import json
import os
from pathlib import Path
from urllib.parse import urlsplit

from playwright.sync_api import expect, sync_playwright

BASE = os.environ["SALES_XRAY_BASE_URL"].rstrip("/")
OUT = Path(os.environ["SALES_XRAY_UX_EVIDENCE_DIR"])


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    errors, outside, proof = [], [], []
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
                    route.fulfill(status=401, json={"detail": "Fictional preview only."})
                else:
                    route.continue_()

            page.route("**/*", boundary)
            assert page.goto(BASE + "/review-fixture/report/outcomes").status == 200
            editor = page.get_by_role("region", name="Recorded call outcome")
            expect(editor).to_contain_text("Unrecorded")
            editor.get_by_role("button", name="Lost", exact=True).click()
            editor.get_by_role("button", name="Save outcome").click()
            notice = editor.get_by_role("alert")
            expect(notice).to_contain_text("Add a reason for Lost")
            editor.get_by_label("Reason for Lost").fill("Chose a different option.")
            editor.get_by_role("button", name="Save outcome").click()
            expect(notice).to_contain_text("Your outcome wasn't saved")
            editor.get_by_role("button", name="Follow-up", exact=True).click()
            date = editor.get_by_label("Follow-up date")
            expect(date).to_have_value("")
            date.fill("2026-10-12")
            editor.get_by_role("button", name="Deal value", exact=True).click()
            editor.get_by_label("Deal amount").fill("123.0000")
            currency = editor.get_by_label("Currency code")
            expect(currency).to_have_value("")
            currency.fill("INR")
            editor.get_by_role("button", name="Save outcome").click()
            expect(notice).to_contain_text("Your outcome wasn't saved")
            expect(editor.locator("strong + span")).to_have_text("Unrecorded")
            editor.get_by_role("button", name="Try again").click()
            expect(notice).to_contain_text("Your outcome wasn't saved")
            assert page.evaluate("document.documentElement.scrollWidth <= innerWidth + 1")
            if width == 390:
                assert editor.locator("button, input").evaluate_all(
                    "items => items.every(el => el.getBoundingClientRect().height >= 44)"
                )
            for theme in ["light", "dark"]:
                page.locator("html").evaluate(
                    "(el, theme) => el.setAttribute('data-theme', theme)", theme
                )
                page.screenshot(path=str(OUT / f"outcome-{width}-{theme}.png"))
            proof.append(
                {
                    "width": width,
                    "human_reason_and_date": True,
                    "explicit_value": True,
                    "honest_failed_retry": True,
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
