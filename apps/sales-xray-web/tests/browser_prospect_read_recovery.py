"""Shared dev: a stalled private GET ends, then an explicit retry restores fictional data."""

import json
import os
from pathlib import Path
from urllib.parse import urlsplit

from browser_prospect_access import DETAIL, LIST
from browser_prospect_library import PROSPECT_ID
from playwright.sync_api import expect, sync_playwright

BASE = os.environ["SALES_XRAY_BASE_URL"].rstrip("/")
OUT = Path(os.environ["SALES_XRAY_UX_EVIDENCE_DIR"])
MESSAGE = "Prospect information is unavailable. Try again."
SHELL_READS = {
    "/v1/me/sales-xray-profile",
    "/v1/updates",
    "/v1/notifications",
    "/v1/conversation/acquisition/submissions",
    "/v1/conversation/acquisition/submissions/summary",
    "/v1/organisation/invites",
}


def main():
    assert BASE == "http://127.0.0.1:3026", "Use committed shared dev only."
    OUT.mkdir(parents=True, exist_ok=True)
    errors, outside, unexpected, proof = [], [], [], []
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
                page.on("pageerror", lambda error: errors.append(str(error)))
                state = {"stall": False, "reads": 0}

                def boundary(route, request, *, state=state):
                    url = urlsplit(request.url)
                    if url.netloc != urlsplit(BASE).netloc:
                        outside.append(url.netloc)
                        route.abort()
                    elif url.path.startswith(("/v1/", "/api/")):
                        if request.method != "GET":
                            unexpected.append({"path": url.path, "method": request.method})
                            route.abort()
                        elif url.path in (
                            "/v1/conversation/prospects",
                            f"/v1/conversation/prospects/{PROSPECT_ID}",
                        ):
                            state["reads"] += 1
                            if not state["stall"]:
                                route.fulfill(
                                    status=200,
                                    json=LIST
                                    if url.path == "/v1/conversation/prospects"
                                    else DETAIL,
                                )
                        elif url.path in SHELL_READS:
                            route.fulfill(status=401, json={"detail": "Fictional preview only."})
                        else:
                            unexpected.append({"path": url.path, "method": request.method})
                            route.abort()
                    else:
                        route.continue_()

                page.route("**/*", boundary)
                assert page.goto(BASE + "/review-fixture/prospects/library").status == 200
                states = page.get_by_role("group", name="Fictional prospect access states")

                def shot(name, theme, *, page=page, width=width):
                    assert page.evaluate("document.documentElement.scrollWidth <= innerWidth + 1")
                    page.evaluate("window.scrollTo(0, 0)")
                    page.screenshot(path=str(OUT / f"{name}-{width}-{theme}.png"))

                for theme in ["light", "dark"]:
                    page.locator("html").evaluate(
                        "(el, theme) => el.setAttribute('data-theme', theme)", theme
                    )
                    for kind in ["list", "profile"]:
                        state["stall"] = False
                        states.get_by_role("button", name="Signed out", exact=True).click()
                        states.get_by_role("button", name=f"Preview {kind}", exact=True).click()
                        populated = (
                            page.get_by_role("feed", name="Prospects list")
                            if kind == "list"
                            else page.get_by_role(
                                "heading", name="Fictional व्यवसाय prospect", exact=True
                            )
                        )
                        expect(populated).to_be_visible()
                        if kind == "list":
                            before = state["reads"]
                            state["stall"] = True
                            page.get_by_role("searchbox", name="Search prospects").fill(
                                f"Fictional {theme}"
                            )
                        else:
                            # Re-enabling the same scope can retain already-loaded
                            # data. Unmount the profile to test a fresh initial GET.
                            states.get_by_role("button", name="Preview list", exact=True).click()
                            expect(page.get_by_role("feed", name="Prospects list")).to_be_visible()
                            before = state["reads"]
                            state["stall"] = True
                            states.get_by_role("button", name="Preview profile", exact=True).click()
                        expect(page.locator('[aria-busy="true"]')).to_be_visible()
                        expect(populated).to_have_count(0)
                        corner = page.get_by_role("alert").filter(has_text=MESSAGE)
                        expect(corner).to_be_visible(timeout=20_000)
                        expect(page.locator('[aria-busy="true"]')).to_have_count(0)
                        expect(populated).to_have_count(0)
                        assert state["reads"] == before + 1, "No automatic retry."
                        retry = corner.get_by_role("button", name="Try again", exact=True)
                        if width == 390:
                            assert retry.evaluate("el => el.getBoundingClientRect().height >= 44")
                        shot(f"prospect-timeout-{kind}", theme)
                        state["stall"] = False
                        retry.click()
                        expect(populated).to_be_visible()
                        expect(corner).to_have_count(0)
                        expect(page.locator('[aria-busy="true"]')).to_have_count(0)
                        assert state["reads"] == before + 2
                        if kind == "profile":
                            assert page.locator("[data-prospect-section]").count() == 6
                            expect(page.locator('[data-prospect-section="1"]')).to_contain_text(
                                "Example business"
                            )
                        shot(f"prospect-recovered-{kind}", theme)
                        proof.append(
                            {
                                "width": width,
                                "theme": theme,
                                "page": kind,
                                "stalled_get_deadline": True,
                                "loading_cleared": True,
                                "explicit_retry_restores_populated_data": True,
                                "no_automatic_retry": True,
                                "no_overflow": True,
                            }
                        )
                page.close()
        finally:
            browser.close()
    assert not errors, errors
    assert not outside, outside
    assert not unexpected, unexpected
    receipt = {
        "origin": BASE,
        "proof": proof,
        "page_errors": errors,
        "external_requests": outside,
        "unexpected_requests": unexpected,
        "api_requests_forwarded": 0,
    }
    (OUT / "prospect-read-recovery-receipt.json").write_text(json.dumps(receipt, indent=2))
    print(json.dumps(receipt))


if __name__ == "__main__":
    main()
