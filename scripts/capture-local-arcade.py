"""Current local Arcade screenshots for the owner's visual review; no credentials."""

import json
from pathlib import Path

from playwright.sync_api import sync_playwright

output = Path(__file__).resolve().parents[1] / "docs/evidence/screenshots/arcade-review-20260908"
output.mkdir(parents=True, exist_ok=True)

with sync_playwright() as playwright:
    browser = playwright.chromium.connect_over_cdp("http://127.0.0.1:9327")
    page = browser.contexts[0].new_page()
    page.set_default_timeout(15000)
    page.set_default_navigation_timeout(30000)
    for label, width, height in (("desktop", 1440, 1000), ("mobile", 390, 844)):
        page.set_viewport_size({"width": width, "height": height})
        for surface, path in (("hub", "/practice"), ("drill", "/practice?set=next-move")):
            page.goto("http://learner.localhost:3100" + path, wait_until="domcontentloaded")
            page.wait_for_timeout(3000)
            page.screenshot(path=str(output / f"{surface}-{label}.png"), full_page=True)
    page.set_viewport_size({"width": 1440, "height": 1000})
    page.goto("http://learner.localhost:3100/practice", wait_until="networkidle")
    print(json.dumps({"screenshots": 4, "directory": str(output)}))
