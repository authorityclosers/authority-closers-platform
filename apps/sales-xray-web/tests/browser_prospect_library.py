"""Invented list API only: phone controls, unavailable state and honest skeleton."""

import json
import os
from pathlib import Path
from urllib.parse import urlsplit

from playwright.sync_api import expect, sync_playwright

BASE = os.environ["SALES_XRAY_BASE_URL"].rstrip("/")
OUT = Path(os.environ["SALES_XRAY_UX_EVIDENCE_DIR"])
PROSPECT_ID = "00000000-0000-0000-0000-000000000004"
PAYLOAD = {
    "schema": "ac.sales-xray.prospects/1",
    "prospects": [
        {
            "prospect_id": PROSPECT_ID,
            "name": "Fictional व्यवसाय prospect",
            "revision": 1,
            "owner_person_id": "00000000-0000-0000-0000-000000000001",
            "stage": None,
            "tags": [],
            "photo_url": None,
            "contact": None,
            "fields": [],
            "buyer_intent": None,
            "next_step": None,
            "last_promise": None,
            "call_count": 0,
            "last_call": None,
        }
    ],
    "total": 1,
    "stage_filters": [],
    "next_offset": None,
}


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
            state = {"failed": False}

            def boundary(route, request, *, state=state):
                address = urlsplit(route.request.url)
                if address.netloc != urlsplit(BASE).netloc:
                    outside.append(address.netloc)
                    route.abort()
                elif address.path == "/v1/conversation/prospects":
                    route.fulfill(
                        status=503 if state["failed"] else 200,
                        json={"detail": "Prospects unavailable."} if state["failed"] else PAYLOAD,
                    )
                elif address.path.startswith("/v1/"):
                    route.fulfill(status=401, json={"detail": "Fictional preview only."})
                else:
                    route.continue_()

            page.route("**/*", boundary)
            assert page.goto(BASE + "/review-fixture/prospects/library").status == 200
            feed = page.get_by_role("feed", name="Prospects list")
            expect(feed).to_contain_text("Fictional व्यवसाय prospect")
            page.get_by_role("button", name="Hover summary for Fictional व्यवसाय prospect").focus()
            expect(page.get_by_role("tooltip")).to_contain_text(PROSPECT_ID)
            page.get_by_role("button", name="All", exact=True).focus()
            assert page.evaluate("document.documentElement.scrollWidth <= innerWidth + 1")
            if width == 390:
                assert feed.locator("button, a").evaluate_all(
                    "items => items.every(el => el.getBoundingClientRect().height >= 44)"
                )
                assert page.get_by_role("searchbox", name="Search prospects").evaluate(
                    "el => el.getBoundingClientRect().height >= 44"
                )
            for theme in ["light", "dark"]:
                page.locator("html").evaluate(
                    "(el, theme) => el.setAttribute('data-theme', theme)", theme
                )
                page.screenshot(path=str(OUT / f"prospect-list-{width}-{theme}.png"))
            state["failed"] = True
            page.get_by_role("searchbox", name="Search prospects").fill("new search")
            notice = page.get_by_role("alert").filter(has_text="Prospects unavailable")
            expect(notice).to_be_visible()
            expect(feed).to_have_count(0)
            expect(page.get_by_test_id("empty-prospects")).to_have_count(0)
            retry = notice.get_by_role("button", name="Try again")
            if width == 390:
                assert retry.evaluate("el => el.getBoundingClientRect().height >= 44")
            state["failed"] = False
            retry.click()
            expect(feed).to_contain_text("Fictional व्यवसाय prospect")
            proof.append(
                {"width": width, "list": True, "source_identity": True, "unavailable_retry": True}
            )
            page.close()
        browser.close()
    assert not errors, errors
    assert not outside, outside
    (OUT / "browser-proof.json").write_text(json.dumps(proof))
    print(json.dumps(proof))


if __name__ == "__main__":
    main()
