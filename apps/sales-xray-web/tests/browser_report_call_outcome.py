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
    errors, outside, unexpected, proof = [], [], [], []
    with sync_playwright() as runtime:
        browser = runtime.chromium.launch(headless=True)
        for width, height in [(390, 844), (1440, 900)]:
            page = browser.new_page(
                viewport={"width": width, "height": height},
                reduced_motion="reduce",
                is_mobile=width == 390,
                has_touch=width == 390,
            )
            page.on("pageerror", lambda error: errors.append(str(error)))

            def boundary(route):
                address = urlsplit(route.request.url)
                if address.netloc != urlsplit(BASE).netloc:
                    outside.append(address.netloc)
                    route.abort()
                elif address.path.startswith("/v1/"):
                    # No outcome API is mounted or forwarded by this fictional fixture.
                    unexpected.append({"path": address.path, "method": route.request.method})
                    route.abort()
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
            editor.get_by_label("Reason for Lost").fill("दूसरा विकल्प चुना।")
            editor.get_by_role("button", name="Save outcome").click()
            expect(notice).to_contain_text("Your outcome couldn't be confirmed")
            expect(editor.locator("strong + span")).to_have_text("Unconfirmed")
            expect(editor.get_by_role("button", name="Won", exact=True)).to_be_disabled()
            expect(editor.get_by_role("button", name="Follow-up", exact=True)).to_be_disabled()
            expect(editor.get_by_label("Reason for Lost")).to_be_disabled()
            expect(editor.get_by_label("Reason for Lost")).to_have_value("दूसरा विकल्प चुना।")
            assert page.evaluate("document.documentElement.scrollWidth <= innerWidth + 1")
            for theme in ["light", "dark"]:
                page.locator("html").evaluate(
                    "(el, theme) => el.setAttribute('data-theme', theme)", theme
                )
                page.screenshot(path=str(OUT / f"outcome-lost-unconfirmed-{width}-{theme}.png"))
            with page.expect_navigation(wait_until="domcontentloaded") as navigation:
                editor.get_by_role("button", name="Reload", exact=True).click()
            assert navigation.value.status == 200
            expect(editor.locator("strong + span")).to_have_text("Unrecorded")
            expect(editor.get_by_role("button", name="Follow-up", exact=True)).to_be_enabled()
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
            expect(notice).to_contain_text("Your outcome couldn't be confirmed")
            expect(editor.locator("strong + span")).to_have_text("Unconfirmed")
            expect(date).to_have_value("2026-10-12")
            expect(editor.get_by_label("Deal amount")).to_have_value("123.0000")
            expect(currency).to_have_value("INR")
            expect(date).to_be_disabled()
            expect(editor.get_by_role("button", name="Save outcome")).to_be_disabled()
            expect(editor.get_by_role("button", name="Reload", exact=True)).to_be_enabled()
            assert page.evaluate("document.documentElement.scrollWidth <= innerWidth + 1")
            if width == 390:
                assert editor.locator("button, input").evaluate_all(
                    "items => items.every(el => el.getBoundingClientRect().height >= 44)"
                )
            for theme in ["light", "dark"]:
                page.locator("html").evaluate(
                    "(el, theme) => el.setAttribute('data-theme', theme)", theme
                )
                page.screenshot(
                    path=str(OUT / f"outcome-follow-up-unconfirmed-{width}-{theme}.png")
                )
            proof.append(
                {
                    "width": width,
                    "human_reason_and_date": True,
                    "explicit_value": True,
                    "unconfirmed_write_disabled": True,
                    "explicit_reload_before_next_write": True,
                    "filled_human_values_retained": True,
                }
            )
            page.close()
        browser.close()
    assert not errors, errors
    assert not outside, outside
    assert not unexpected, unexpected
    (OUT / "browser-proof.json").write_text(json.dumps(proof))
    print(json.dumps(proof))


if __name__ == "__main__":
    main()
