"""Audit the actual dev shell with fictional report data and intercepted APIs.

SALES_XRAY_BASE_URL=http://127.0.0.1:3026 SALES_XRAY_UX_EVIDENCE_DIR=<output>
uv run python apps/sales-xray-web/tests/browser_phone_parity.py
"""

import json
import os
from pathlib import Path
from urllib.parse import urlsplit

from playwright.sync_api import expect, sync_playwright

BASE = os.environ["SALES_XRAY_BASE_URL"].rstrip("/")
OUT = Path(os.environ["SALES_XRAY_UX_EVIDENCE_DIR"])
assert BASE in {
    "http://127.0.0.1:3026",
    "https://salesxray-dev.authorityclosers.com",
}


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    expect.set_options(timeout=15_000)
    checks, errors, api_requests = [], [], []
    with sync_playwright() as runtime:
        browser = runtime.chromium.launch(headless=True)
        for width, height in [(360, 800), (390, 844), (430, 932), (1440, 900)]:
            page = browser.new_page(
                viewport={"width": width, "height": height}, reduced_motion="reduce"
            )
            page.on("pageerror", lambda error: errors.append(str(error)))

            def boundary(route):
                url = urlsplit(route.request.url)
                if url.path.startswith("/v1/"):
                    api_requests.append({"method": route.request.method, "path": url.path})
                    route.fulfill(status=404, content_type="application/json", body="{}")
                elif url.netloc != urlsplit(BASE).netloc:
                    route.abort()
                else:
                    route.continue_()

            page.route("**/*", boundary)
            response = page.goto(f"{BASE}/review-fixture/shell", wait_until="networkidle")
            assert response.status == 200
            workspace = page.locator("[data-report-modes]")
            expect(workspace).to_be_visible()
            report = page.locator(".studio-report")
            report_width = report.bounding_box()["width"]
            padding = page.locator("#main-content").evaluate(
                "e => [getComputedStyle(e).paddingLeft, getComputedStyle(e).paddingRight]"
            )
            section_checks = []

            def capture_section(
                label, panel, page=page, width=width, section_checks=section_checks
            ):
                """Check both ends inside the real report scroll container."""
                scroller = page.locator(".studio-main")
                panel.evaluate(
                    "e => { const s = e.closest('.studio-main'); "
                    "s.scrollTop += e.getBoundingClientRect().top - "
                    "s.getBoundingClientRect().top - 80; }"
                )
                page.screenshot(path=str(OUT / f"{label}-{width}.png"))
                panel.evaluate(
                    "e => { const s = e.closest('.studio-main'); "
                    "s.scrollTop += e.getBoundingClientRect().bottom - "
                    "s.getBoundingClientRect().bottom; }"
                )
                metrics = scroller.evaluate("e => ({width: e.clientWidth, scroll: e.scrollWidth})")
                assert metrics["scroll"] <= metrics["width"] + 1, (label, metrics)
                assert page.evaluate("document.documentElement.scrollWidth <= innerWidth + 1")
                page.screenshot(path=str(OUT / f"{label}-end-{width}.png"))
                section_checks.append({"section": label, **metrics})

            if width < 900:
                assert report_width >= width - 34, (width, report_width)
                assert padding == ["0px", "0px"], padding
                nav = page.get_by_role("navigation", name="Mobile Sales Xray navigation")
                expect(nav).to_be_visible()
                expect(nav.get_by_role("link", name="Dashboard", exact=True)).to_have_attribute(
                    "href", "/dashboard"
                )
                expect(nav.get_by_role("link", name="New analysis")).to_be_visible()
                controls = nav.locator("a, button")
                assert controls.count() in (4, 5)
                for control in controls.all():
                    box = control.bounding_box()
                    assert box["width"] >= 44 and box["height"] >= 44
            page.screenshot(path=str(OUT / f"shell-{width}.png"))
            if width < 900:
                for section in ["overview", "moments", "analysis", "coaching"]:
                    page.locator(f'[data-report-sections] a[title="{section.title()}"]').click()
                    heading = page.locator(f'[data-report-mode-section="{section}"]').get_by_role(
                        "heading", name=section.title(), exact=True
                    )
                    expect(heading).to_be_in_viewport()
                    metrics = page.locator(".studio-main").evaluate(
                        "e => ({width: e.clientWidth, scroll: e.scrollWidth})"
                    )
                    assert metrics["scroll"] <= metrics["width"] + 1, metrics
                    assert page.evaluate("document.documentElement.scrollWidth <= innerWidth + 1")
                    capture_section(
                        section, page.locator(f'[data-report-mode-section="{section}"]')
                    )
                page.locator('summary[aria-label="Report view and text size"]').click()
                page.get_by_title("Tabbed view", exact=True).click()
            for section in ["Overview", "Transcript", "Moments", "Analysis", "Coaching"]:
                page.get_by_role("tab", name=section, exact=True).click()
                expect(workspace).to_have_attribute("data-report-section", section.lower())
                assert page.evaluate("document.documentElement.scrollWidth <= innerWidth + 1")
                assert page.locator(".studio-main").evaluate(
                    "e => e.scrollWidth <= e.clientWidth + 1"
                )
                capture_section(
                    f"tab-{section.lower()}",
                    page.locator(f'[data-report-mode-section="{section.lower()}"]'),
                )
            # The header reader and the generated DOCX use separate scroll surfaces.
            page.locator(".studio-main").evaluate("e => { e.scrollTop = 0; }")
            page.get_by_role("button", name="Open transcript reader", exact=True).click()
            reader = page.get_by_role("dialog", name="Transcript reader", exact=True)
            expect(reader).to_be_visible()
            assert reader.evaluate("e => e.scrollWidth <= e.clientWidth + 1")
            page.screenshot(path=str(OUT / f"transcript-reader-{width}.png"))
            reader.get_by_role("button", name="Close transcript reader").click()
            page.locator('summary[aria-label="Report view and text size"]').click()
            page.get_by_title("Document view", exact=True).click()
            preview = page.get_by_role("region", name="Sales Xray document preview")
            expect(preview).to_be_visible(timeout=30_000)
            assert preview.evaluate("e => e.scrollWidth <= e.clientWidth + 1")
            for section, label in [
                ("overview", "Overview"),
                ("coaching", "Coaching"),
                ("moments", "Moments"),
                ("missed", "Missed chances"),
                ("skills", "Skills"),
                ("facts", "Facts"),
            ]:
                page.locator(f'[data-report-sections] a[title="{label}"]').click()
                heading = preview.locator(f'[id$="-heading-{section}"]')
                expect(heading).to_be_in_viewport(ratio=1)
                assert page.locator(".studio-main").evaluate(
                    "e => e.scrollWidth <= e.clientWidth + 1"
                )
                page.screenshot(path=str(OUT / f"document-{section}-{width}.png"))
            if width < 900:
                page.get_by_role("navigation", name="Mobile Sales Xray navigation").get_by_role(
                    "link", name="Dashboard", exact=True
                ).click()
                page.wait_for_url("**/dashboard")
                expect(
                    page.get_by_role("navigation", name="Mobile Sales Xray navigation").get_by_role(
                        "link", name="Dashboard", exact=True
                    )
                ).to_have_attribute("aria-current", "page")
            checks.append(
                {
                    "width": width,
                    "height": height,
                    "report_width": report_width,
                    "shell_padding": padding,
                    "sections": section_checks,
                }
            )
            page.close()
        browser.close()
    assert not errors, errors
    assert all(request["method"] == "GET" for request in api_requests), api_requests
    proof = {
        "origin": BASE,
        "checks": checks,
        "page_errors": errors,
        "intercepted_api_requests": api_requests,
    }
    (OUT / "browser-proof.json").write_text(json.dumps(proof, indent=2) + "\n")
    print(json.dumps(checks, indent=2))


if __name__ == "__main__":
    main()
