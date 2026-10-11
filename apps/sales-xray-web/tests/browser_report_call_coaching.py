"""Fictional own-call API bootstrap; no real account or deployed read."""

import json
import os
from pathlib import Path
from urllib.parse import urlsplit

from playwright.sync_api import expect, sync_playwright

BASE = os.environ["SALES_XRAY_BASE_URL"].rstrip("/")
OUT = Path(os.environ["SALES_XRAY_UX_EVIDENCE_DIR"])


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    errors, outside, api, media, proof = [], [], [], [], []
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
                elif address.path.startswith("/v1/me/coaching/media/fictional-impact/"):
                    media.append(address.path)
                    route.fulfill(status=503, content_type="text/plain", body="Unavailable")
                elif address.path.startswith("/v1/"):
                    api.append(address.path)
                    route.abort()
                else:
                    route.continue_()

            page.route("**/*", boundary)
            assert page.goto(BASE + "/review-fixture/report/coaching").status == 200
            coaching = page.locator('[data-call-coaching][data-state="ready"]')
            expect(coaching).to_be_visible()
            expect(coaching).to_contain_text("Fictional API focus")
            expect(coaching).to_contain_text("Your next-call mission")
            call_link = coaching.get_by_role("link", name="Open full coaching for this call")
            expect(call_link).to_be_visible()
            expect(call_link).to_have_attribute(
                "href", "/coaching?call=7b6443d3-9b2d-4f97-9e70-5e82e54f8738"
            )
            expect(coaching.get_by_role("link", name="My coaching across calls")).to_be_visible()
            coaching.locator("button").first.click()
            expect(page.get_by_role("status")).to_contain_text("ms ·")
            lesson = coaching.locator("details").first
            lesson.locator("summary").click()
            example = coaching.get_by_role("region", name="Coaching example for this focus")
            expect(example).to_contain_text("Placeholder · neutral narration")
            expect(example.locator("audio")).to_have_count(0)
            assert len(media) == (0 if width == 390 else 2)
            example.get_by_text("Read this clip", exact=True).click()
            example.get_by_role("button", name="Next slide", exact=True).click()
            expect(example).to_contain_text("Wait for their answer.")
            example.get_by_role("button", name="Previous slide", exact=True).click()
            expect(example).to_contain_text("समस्या का असर क्या है?")
            example.get_by_role("button", name="Play coaching clip", exact=True).click()
            expect(example.get_by_role("status")).to_contain_text("Narration is unavailable")
            example.get_by_role("button", name="Try clip again", exact=True).click()
            expect(example.get_by_role("status")).to_contain_text("Narration is unavailable")
            expect(coaching).to_contain_text("Your next-call mission")
            expect(lesson).to_contain_text("not words from the call")
            assert page.evaluate("document.documentElement.scrollWidth <= innerWidth + 1")
            expect(lesson).to_contain_text("not words from the call")
            expect(lesson.locator("ol li").first).to_be_visible()
            assert page.evaluate("document.documentElement.scrollWidth <= innerWidth + 1")
            if width == 390:
                targets = coaching.locator("button, summary, a").evaluate_all(
                    "items => items.filter(el => el.checkVisibility()).map(el => "
                    "({label: el.getAttribute('aria-label') || el.textContent.trim(), "
                    "height: el.getBoundingClientRect().height, "
                    "width: el.getBoundingClientRect().width}))"
                )
                assert targets and all(
                    item["height"] >= 44 and item["width"] >= 44 for item in targets
                ), targets
            lesson.locator("summary").click()
            for theme in ["light", "dark"]:
                page.locator("html").evaluate(
                    "(el, theme) => el.setAttribute('data-theme', theme)", theme
                )
                page.evaluate("window.scrollTo(0, 0)")
                page.screenshot(path=str(OUT / f"report-call-coaching-{width}-{theme}.png"))
                example.screenshot(
                    path=str(OUT / f"report-call-coaching-media-{width}-{theme}.png")
                )
            proof.append(
                {
                    "width": width,
                    "bootstrap": True,
                    "source": True,
                    "lesson": True,
                    "full_call_coaching_link": True,
                    "media_click_retry": True,
                }
            )
            page.close()
        browser.close()
    assert not errors, errors
    assert not outside, outside
    assert not api, api
    assert len(media) == 4, media
    assert all(path.startswith("/v1/me/coaching/media/fictional-impact/") for path in media)
    (OUT / "browser-proof.json").write_text(
        json.dumps({"checks": proof, "api_reads": 0, "fictional_media_requests": len(media)})
    )
    print(json.dumps(proof))


if __name__ == "__main__":
    main()
