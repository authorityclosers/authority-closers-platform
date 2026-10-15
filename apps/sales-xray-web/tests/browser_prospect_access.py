"""Populated synthetic customer -> access loss -> existing sign-in/retry action."""

import copy
import json
import os
from pathlib import Path
from urllib.parse import urlsplit

from browser_prospect_library import PAYLOAD, PROSPECT_ID
from playwright.sync_api import expect, sync_playwright

BASE = os.environ["SALES_XRAY_BASE_URL"].rstrip("/")
OUT = Path(os.environ["SALES_XRAY_UX_EVIDENCE_DIR"])
LIST = copy.deepcopy(PAYLOAD)
LIST["prospects"][0]["profile_fields"] = {
    key: {
        "state": "known",
        "value": {"kind": "text", "text": text},
        "basis": "person",
        "locked": True,
        "set_at": "2026-10-11T00:00:00Z",
    }
    for key, text in [("business", "Example business"), ("role", "Founder")]
}
DETAIL = {
    "schema": "ac.sales-xray.prospects/1",
    "prospect": LIST["prospects"][0],
    "calls": [],
    "next_offset": None,
    "promises": [],
    "next_steps": [],
    "buyer_intent_history": [],
}


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    errors, outside, proof = [], [], []
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
                reads = []

                def boundary(route, request, *, reads=reads):
                    url = urlsplit(route.request.url)
                    if url.netloc != urlsplit(BASE).netloc:
                        outside.append(url.netloc)
                        route.abort()
                    elif url.path == "/v1/conversation/prospects":
                        reads.append(url.path)
                        route.fulfill(status=200, json=LIST)
                    elif url.path == f"/v1/conversation/prospects/{PROSPECT_ID}":
                        reads.append(url.path)
                        route.fulfill(status=200, json=DETAIL)
                    elif url.path.startswith(("/v1/", "/api/")):
                        route.fulfill(status=401, json={"detail": "Fictional preview only."})
                    else:
                        route.continue_()

                page.route("**/*", boundary)
                response = page.goto(BASE + "/review-fixture/prospects/library")
                assert response.status == 200
                states = page.get_by_role("group", name="Fictional prospect access states")

                def shot(name, theme, *, page=page, width=width):
                    page.locator("html").evaluate(
                        "(el, theme) => el.setAttribute('data-theme', theme)", theme
                    )
                    page.evaluate("window.scrollTo(0, 0)")
                    assert page.evaluate("document.documentElement.scrollWidth <= innerWidth + 1")
                    page.screenshot(path=str(OUT / f"{name}-{width}-{theme}.png"))

                for theme in ["light", "dark"]:
                    states.get_by_role("button", name="Signed out", exact=True).click()
                    states.get_by_role("button", name="Preview list", exact=True).click()
                    expect(page.get_by_text("Sign-in requested", exact=True)).to_have_count(0)
                    feed = page.get_by_role("feed", name="Prospects list")
                    expect(feed).to_contain_text("Fictional व्यवसाय prospect")
                    shot("prospect-access-list", theme)
                    count = len(reads)
                    states.get_by_role("button", name="Signed out", exact=True).click()
                    expect(
                        page.get_by_role("heading", name="Sign in to see your prospects")
                    ).to_be_visible()
                    expect(feed).to_have_count(0)
                    expect(page.get_by_role("searchbox")).to_have_count(0)
                    expect(page.locator('[aria-busy="true"]')).to_have_count(0)
                    assert len(reads) == count
                    shot("prospect-signed-out-list", theme)

                    states.get_by_role("button", name="Preview profile", exact=True).click()
                    expect(
                        page.get_by_role("heading", name="Fictional व्यवसाय prospect", exact=True)
                    ).to_be_visible()
                    assert page.locator("[data-prospect-section]").count() == 6
                    expect(page.locator('[data-prospect-section="1"]')).to_contain_text(
                        "Example business"
                    )
                    shot("prospect-access-profile", theme)
                    count = len(reads)
                    states.get_by_role("button", name="Checking access", exact=True).click()
                    expect(
                        page.locator('[aria-label="Checking prospect access"][aria-busy="true"]')
                    ).to_be_visible()
                    expect(
                        page.get_by_role("heading", name="Fictional व्यवसाय prospect", exact=True)
                    ).to_have_count(0)
                    expect(
                        page.get_by_role("region", name="Prospects account access")
                    ).to_have_count(0)
                    assert len(reads) == count

                    states.get_by_role("button", name="Signed out", exact=True).click()
                    expect(
                        page.get_by_role("heading", name="Sign in to see your prospects")
                    ).to_be_visible()
                    expect(page.locator('[aria-busy="true"]')).to_have_count(0)
                    expect(page.locator("[data-prospect-section]")).to_have_count(0)
                    sign_in = page.get_by_role(
                        "region", name="Prospects account access"
                    ).get_by_role("link", name="Sign in", exact=True)
                    assert (
                        sign_in.get_attribute("href") == "/login/"
                        or sign_in.get_attribute("href") == "/login"
                    )
                    sign_in.focus()
                    if width == 390:
                        assert sign_in.evaluate("el => el.getBoundingClientRect().height >= 44")
                    shot("prospect-signed-out-profile", theme)
                    sign_in.click()
                    expect(
                        page.get_by_role("status", name="").filter(has_text="Sign-in requested")
                    ).to_be_visible()
                    assert page.url.endswith(
                        "/review-fixture/prospects/library/"
                    ) or page.url.endswith("/review-fixture/prospects/library")
                    assert len(reads) == count

                    states.get_by_role("button", name="Workspace unavailable", exact=True).click()
                    corner = page.get_by_role("alert").filter(
                        has_text="Workspace access is unavailable"
                    )
                    expect(corner).to_be_visible()
                    expect(sign_in).to_have_count(0)
                    retry = corner.get_by_role("button", name="Try again")
                    if width == 390:
                        assert retry.evaluate("el => el.getBoundingClientRect().height >= 44")
                    assert len(reads) == count
                    retry.click()
                    expect(
                        page.get_by_role("heading", name="Fictional व्यवसाय prospect", exact=True)
                    ).to_be_visible()
                    expect(corner).to_have_count(0)
                proof.append(
                    {
                        "width": width,
                        "themes": ["light", "dark"],
                        "populated_list_and_six_section_profile": True,
                        "source_hidden_on_access_loss": True,
                        "no_private_reads_without_ready_access": True,
                        "sign_in_action_preserves_fixture_address": True,
                        "workspace_corner_retry": True,
                        "no_overflow": True,
                    }
                )
                page.close()
        finally:
            browser.close()
    assert not errors, errors
    assert not outside, outside
    receipt = {"origin": BASE, "proof": proof, "page_errors": errors, "external_requests": outside}
    (OUT / "prospect-access-receipt.json").write_text(json.dumps(receipt, indent=2))
    print(json.dumps(receipt))


if __name__ == "__main__":
    main()
