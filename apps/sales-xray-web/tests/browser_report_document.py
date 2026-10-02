"""Fictional dev-only Document regressions; no API or recording is used.

Run with SALES_XRAY_BASE_URL and SALES_XRAY_UX_EVIDENCE_DIR set:
uv run --with pypdf python apps/sales-xray-web/tests/browser_report_document.py
"""

import json
import os
from pathlib import Path
from urllib.parse import urlsplit

from playwright.sync_api import expect, sync_playwright
from pypdf import PdfReader

BASE = os.environ["SALES_XRAY_BASE_URL"].rstrip("/")
OUT = Path(os.environ["SALES_XRAY_UX_EVIDENCE_DIR"])
CALL = "00000000-0000-4000-8000-000000000002"
SUMMARY = "Synthetic call: the buyer declined a sale and a next step."


def pdf_text(path: Path) -> str:
    return " ".join(" ".join(p.extract_text() for p in PdfReader(path).pages).split())


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    expect.set_options(timeout=30_000)
    errors: list[str] = []
    external: list[str] = []
    proof: list[dict] = []
    with sync_playwright() as runtime:
        browser = runtime.chromium.launch(headless=True)
        for width, height in [(390, 844), (1440, 900)]:
            page = browser.new_page(
                viewport={"width": width, "height": height}, reduced_motion="reduce"
            )
            page.on("pageerror", lambda error: errors.append(str(error)))

            def boundary(route):
                if urlsplit(route.request.url).netloc != urlsplit(BASE).netloc:
                    external.append(urlsplit(route.request.url).netloc)
                    route.abort()
                else:
                    route.continue_()

            page.route("**/*", boundary)
            response = page.goto(
                f"{BASE}/review-fixture/shell?call={CALL}&view=tabs&section=overview",
                wait_until="networkidle",
            )
            assert response.status == 200
            workspace = page.locator("[data-report-modes]")
            # Tabs differs from the server's Reading default, proving hydration
            # before clicking a toolbar that may move into the shell.
            expect(workspace).to_have_attribute("data-view", "tabs")
            if width == 1440:
                expect(page.locator("[data-report-nav]")).to_have_attribute(
                    "data-placement", "toolbar"
                )
            page.get_by_title("Reading view", exact=True).click()
            expect(workspace).to_have_attribute("data-view", "reading")
            disclosure = workspace.locator("details").filter(
                has=page.locator("summary", has_text="Read the full summary")
            )
            assert disclosure.evaluate("el => el.open") is False
            expect(disclosure.locator("p")).not_to_be_visible()
            page.get_by_title("Document view", exact=True).click()
            expect(workspace).to_have_attribute("data-view", "document")
            summary = workspace.locator("[class*='inShort'] p")
            expect(summary).to_be_visible()
            assert summary.evaluate("el => el.closest('details') === null")
            expect(summary).to_have_text(SUMMARY)
            skills = workspace.locator("[data-document-skills] section")
            expect(skills).to_have_count(4)
            for skill in skills.all():
                expect(skill.locator("p")).to_be_visible()
            moments = workspace.locator('[aria-label="Key moments"] [data-moment]')
            assert moments.count() > 1
            for moment in moments.all():
                detail = moment.locator('[id^="moment-detail-"]')
                expect(detail).to_be_visible()
                expect(detail).to_have_attribute("aria-hidden", "false")
                assert detail.get_attribute("inert") is None
            assert not workspace.locator("[class*='docFooter']").count()
            for print_query in [False, True]:
                if print_query:
                    page.goto(
                        f"{BASE}/review-fixture/shell?call={CALL}&view=document&print=1",
                        wait_until="networkidle",
                    )
                    expect(workspace).to_have_attribute("data-view", "document")
                    expect(summary).to_be_visible()
                page.emulate_media(media="print")
                path = OUT / f"full-summary-{width}-{'renderer' if print_query else 'native'}.pdf"
                page.pdf(path=str(path), prefer_css_page_size=True, print_background=True)
                assert SUMMARY in pdf_text(path), "Full summary missing from PDF"
                long_report = PdfReader(path)
                assert len(long_report.pages) > 8, "Fixture must span more pages than panels"
                for i, pdf_page in enumerate(long_report.pages, 1):
                    assert f"Page {i} of {len(long_report.pages)}" in pdf_page.extract_text()
            page.emulate_media(media="screen")
            page.goto(
                f"{BASE}/review-fixture/shell?call={CALL}&view=tabs&section=transcript",
                wait_until="networkidle",
            )
            expect(workspace).to_have_attribute("data-view", "tabs")
            for view in ["document", "reading", "tabs", "document"]:
                page.get_by_title(
                    {"document": "Document view", "reading": "Reading view", "tabs": "Tabbed view"}[
                        view
                    ],
                    exact=True,
                ).click()
                expect(workspace).to_have_attribute("data-view", view)
                expect(workspace).to_have_attribute("data-report-section", "transcript")
                if view == "tabs":
                    continue
                page.wait_for_function(
                    """() => {
                      const w = document.querySelector('[data-report-modes]');
                      const h = w.querySelector('[data-report-mode-section="transcript"] h2');
                      let scroller = w.parentElement;
                      while (scroller && !(scroller.scrollHeight > scroller.clientHeight &&
                        ['auto', 'scroll', 'overlay'].includes(
                          getComputedStyle(scroller).overflowY)))
                        scroller = scroller.parentElement;
                      const top = scroller
                        ? scroller.getBoundingClientRect().top + scroller.clientTop : 0;
                      const offset = parseFloat(
                        w.style.getPropertyValue('--report-scroll-target-offset'));
                      const bounds = h.getBoundingClientRect();
                      return bounds.height > 0 && bounds.top >= top + offset - 2 &&
                        bounds.top <= top + offset + 2 && bounds.bottom < innerHeight;
                    }"""
                )
                heading = workspace.locator('[data-report-mode-section="transcript"] h2')
                bounds = heading.bounding_box()
                proof.append({"width": width, "view": view, "heading": bounds})
                page.screenshot(path=str(OUT / f"transcript-{view}-{width}.png"))
            page.goto(
                f"{BASE}/review-fixture/shell?call={CALL}&view=document&section=overview",
                wait_until="networkidle",
            )
            expect(workspace).to_have_attribute("data-view", "document")
            page.get_by_title("Reading view", exact=True).click()
            expect(workspace).to_have_attribute("data-view", "reading")
            workspace.locator('[data-report-mode-section="moments"] h2').evaluate(
                "el => el.scrollIntoView({block: 'start', behavior: 'instant'})"
            )
            expect(workspace).to_have_attribute("data-report-section", "moments")
            assert "section=overview" in page.url
            entries = page.evaluate("history.length")
            page.get_by_title("Document view", exact=True).click()
            expect(workspace).to_have_attribute("data-view", "document")
            expect(workspace).to_have_attribute("data-report-section", "moments")
            assert "section=moments" in page.url
            assert page.evaluate("history.length") == entries
            page.goto(
                f"{BASE}/review-fixture/document?call={CALL}&view=document&print=1",
                wait_until="networkidle",
            )
            expect(workspace).to_have_attribute("data-view", "document")
            expect(
                workspace.get_by_text("Transcript revision: synthetic-display-r1", exact=True)
            ).to_be_visible()
            assert page.evaluate("document.documentElement.scrollWidth <= innerWidth")
            page.screenshot(path=str(OUT / f"document-{width}.png"))
            path = OUT / f"document-{width}.pdf"
            page.emulate_media(media="print")
            page.pdf(path=str(path), prefer_css_page_size=True, print_background=True)
            reader = PdfReader(path)
            assert len(reader.pages) == 7
            for i, pdf_page in enumerate(reader.pages, 1):
                assert abs(float(pdf_page.mediabox.width) - 595.28) < 1
                assert abs(float(pdf_page.mediabox.height) - 841.89) < 1
                assert f"Page {i} of 7" in pdf_page.extract_text()
            assert "Transcript revision: synthetic-display-r1" in pdf_text(path)
            page.close()
        browser.close()
    assert not errors, errors
    assert not external, external
    (OUT / "document-regressions.json").write_text(
        json.dumps(
            {
                "base": BASE,
                "summary_pdf": "native and print=1 at both widths",
                "positions": proof,
                "revision": "synthetic-display-r1",
                "a4_pages": 7,
                "scrolled_view_toggle_replaces_history": True,
                "page_errors": errors,
                "external_requests": external,
            },
            indent=2,
        )
        + "\n"
    )
    print(json.dumps({"result": "passed", "positions": len(proof), "a4_pages": 7}))


if __name__ == "__main__":
    main()
