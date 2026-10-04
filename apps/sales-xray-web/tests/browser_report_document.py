"""Check the fictional DOCX on dev; no API, customer data or provider is used.

SALES_XRAY_BASE_URL=http://127.0.0.1:3026 SALES_XRAY_UX_EVIDENCE_DIR=<output>
uv run python apps/sales-xray-web/tests/browser_report_document.py
"""

import hashlib
import io
import json
import os
import xml.etree.ElementTree as ET
from pathlib import Path
from urllib.parse import urlsplit
from zipfile import ZipFile

from playwright.sync_api import expect, sync_playwright

BASE = os.environ["SALES_XRAY_BASE_URL"].rstrip("/")
OUT = Path(os.environ["SALES_XRAY_UX_EVIDENCE_DIR"])
SUMMARY = "Synthetic call: the buyer declined a sale and a next step."


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    expect.set_options(timeout=30_000)
    proof = []
    errors = []
    external = []
    with sync_playwright() as runtime:
        browser = runtime.chromium.launch(headless=True)
        for width, height in [(390, 844), (1440, 900)]:
            page = browser.new_page(viewport={"width": width, "height": height})
            page.on("pageerror", lambda error: errors.append(str(error)))

            def boundary(route):
                if urlsplit(route.request.url).netloc != urlsplit(BASE).netloc:
                    external.append(urlsplit(route.request.url).netloc)
                    route.abort()
                else:
                    route.continue_()

            page.route("**/*", boundary)
            response = page.goto(f"{BASE}/review-fixture/document", wait_until="networkidle")
            assert response.status == 200
            workspace = page.locator("[data-report-modes]")
            expect(workspace).to_have_attribute("data-view", "document")
            preview = page.get_by_role("region", name="Sales Xray document preview")
            expect(preview).to_be_visible()
            expect(preview).to_contain_text(SUMMARY)
            # DOCX run styles must retain the requested browser fallback.
            fonts = preview.locator("section.report-docx span").evaluate_all(
                "spans => [...new Set(spans.map(span => getComputedStyle(span).fontFamily))]"
            )
            assert fonts and all("Calibri" in font and "Arial" in font for font in fonts)
            headings = preview.locator("[data-report-mode-section]")
            assert headings.all_text_contents() == [
                "Overview",
                "Moments",
                "Analysis",
                "Coaching",
                "Transcript appendix",
            ]
            link = page.get_by_role("link", name="Download .docx", exact=True)
            url = link.get_attribute("href")
            # Read the actual preview's download Blob and compare all its bytes.
            preview_bytes = bytes(
                page.evaluate(
                    """async url => Array.from(
                new Uint8Array(await (await fetch(url)).arrayBuffer()))""",
                    url,
                )
            )
            with page.expect_download() as info:
                link.click()
            downloaded = info.value
            assert (
                downloaded.suggested_filename
                == "Fictional seller — sample call report – Sales Xray report.docx"
            )
            path = OUT / f"fictional-report-{width}.docx"
            downloaded.save_as(path)
            assert path.read_bytes() == preview_bytes
            with ZipFile(io.BytesIO(preview_bytes)) as archive:
                assert archive.testzip() is None
                xml = ET.fromstring(archive.read("word/document.xml"))  # noqa: S314 - trusted fixture generated in this test
                ns = {"w": "http://schemas.openxmlformats.org/wordprocessingml/2006/main"}
                text = "".join(t.text or "" for t in xml.findall(".//w:t", ns))
                assert SUMMARY in text
                assert "I don't want to set another step today. Please don't follow up." in text
                assert xml.findall(".//w:tbl", ns)
            page.screenshot(path=str(OUT / f"document-{width}.png"))
            sheet = preview.locator("section.report-docx").first
            base_width = sheet.bounding_box()["width"]
            for size, scale in [("125", 1.25), ("112.5", 1.125), ("100", 1.0)]:
                page.get_by_role("button", name=f"Text size {size}%", exact=True).click()
                assert link.get_attribute("href") == url
                assert abs(sheet.bounding_box()["width"] / base_width - scale) < 0.01
            # Keep page overflow inside the keyboard-accessible preview region.
            assert page.evaluate("document.documentElement.scrollWidth <= window.innerWidth + 1")
            page.get_by_title("Reading view", exact=True).click()
            expect(workspace).to_have_attribute("data-view", "reading")
            expect(preview).not_to_be_visible()
            page.get_by_title("Document view", exact=True).click()
            expect(page.get_by_role("region", name="Sales Xray document preview")).to_be_visible()
            proof.append(
                {
                    "width": width,
                    "bytes": len(preview_bytes),
                    "sha256": hashlib.sha256(preview_bytes).hexdigest(),
                    "preview_equals_download": True,
                    "preview_font_families": fonts,
                }
            )
            page.close()
        browser.close()
    assert not errors, errors
    assert not external, external
    (OUT / "browser-proof.json").write_text(
        json.dumps(
            {"checks": proof, "page_errors": errors, "external_requests": external}, indent=2
        )
    )
    print(json.dumps(proof, indent=2))


if __name__ == "__main__":
    main()
