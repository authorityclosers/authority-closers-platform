"""Shared-dev fictional Report map: exact names, touch targets and playback."""

import json
import os
from pathlib import Path
from urllib.parse import urlsplit

from playwright.sync_api import expect, sync_playwright

BASE = os.environ["SALES_XRAY_BASE_URL"].rstrip("/")
OUT = Path(os.environ["SALES_XRAY_UX_EVIDENCE_DIR"])
LENSES = [
    ("Who talked", "who"),
    ("Call stages", "stages"),
    ("Talk share by minute", "talk-share"),
]


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    failures, external, api_reads, proof = [], [], [], []
    expect.set_options(timeout=10000)
    with sync_playwright() as runtime:
        browser = runtime.chromium.launch(headless=True)
        try:
            for width, height in [(390, 844), (1440, 900)]:
                page = browser.new_page(
                    viewport={"width": width, "height": height},
                    reduced_motion="reduce",
                    is_mobile=width == 390,
                    has_touch=width == 390,
                )
                page.on("pageerror", lambda error: failures.append(str(error)))

                def boundary(route):
                    url = urlsplit(route.request.url)
                    if url.netloc != urlsplit(BASE).netloc:
                        external.append(url.netloc)
                        route.abort()
                    elif url.path.startswith(("/api/", "/v1/")):
                        api_reads.append(url.path)
                        route.abort()
                    else:
                        route.continue_()

                page.route("**/*", boundary)
                for theme in ["light", "dark"]:
                    page.emulate_media(color_scheme=theme)
                    response = page.goto(BASE + "/review-fixture/shell", wait_until="networkidle")
                    assert response.status == 200
                    expect(page.locator("[data-full-shell-fixture]")).to_be_visible()
                    expect(page.locator("html")).to_have_attribute("data-theme", theme)
                    expect(page.locator("[data-full-shell-fixture]")).to_have_attribute(
                        "data-theme", theme
                    )
                    call_map = page.get_by_role("figure", name="Call map", exact=True)
                    controls = call_map.get_by_role("group", name="What the map shows")
                    expect(controls).to_be_visible()
                    assert controls.get_by_role("button").count() == 3
                    for label, name in LENSES:
                        button = controls.get_by_role("button", name=label, exact=True)
                        expect(button).to_be_visible()
                        assert button.evaluate("el => el.getBoundingClientRect().height") >= (
                            44 if width == 390 else 32
                        )
                        button.focus()
                        button.press("Enter")
                        expect(button).to_have_attribute("aria-pressed", "true")
                        assert controls.locator('[aria-pressed="true"]').count() == 1
                        assert page.evaluate(
                            "document.documentElement.scrollWidth <= innerWidth + 1"
                        )
                        page.screenshot(path=str(OUT / f"report-map-{name}-{width}-{theme}.png"))
                    slider = call_map.get_by_role(
                        "slider", name="Play the call from a point in time", exact=True
                    )
                    slider.focus()
                    slider.press("ArrowRight")
                    expect(
                        page.get_by_role("status").filter(has_text="Would play from")
                    ).to_be_visible()
                    proof.append(
                        {
                            "width": width,
                            "theme": theme,
                            "exact_accessible_names": [label for label, _ in LENSES],
                            "keyboard_lens_selection": True,
                            "one_selected_lens": True,
                            "minimum_control_height": 44 if width == 390 else 32,
                            "source_seek_callback": True,
                            "no_overflow": True,
                        }
                    )
                page.close()
        finally:
            browser.close()
    assert not failures, failures
    assert not external, external
    assert not api_reads, api_reads
    receipt = {
        "origin": BASE,
        "proof": proof,
        "page_errors": failures,
        "external_requests": external,
        "api_reads": api_reads,
    }
    (OUT / "report-map-access-receipt.json").write_text(json.dumps(receipt, indent=2) + "\n")
    print(json.dumps(receipt))


if __name__ == "__main__":
    main()
