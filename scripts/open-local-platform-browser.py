"""Sign in to local test accounts in a separately launched disposable Chrome profile."""

from __future__ import annotations

import json
import os
from pathlib import Path
from urllib.parse import urlsplit

from playwright.sync_api import Route, expect, sync_playwright

ROOT = Path(__file__).resolve().parents[1]
SURFACES = (
    ("learner", "http://learner.localhost:3100", "learner@ac.localhost", None, "/home"),
    (
        "admin",
        "http://admin.localhost:3101",
        "admin@ac.localhost",
        "operations_tenant_id",
        "/",
    ),
    (
        "coach",
        "http://coach.localhost:3102",
        "coach@ac.localhost",
        "academy_tenant_id",
        "/studio/programs",
    ),
)
LOCAL_ORIGINS = {origin for _, origin, *_ in SURFACES}


def allowed_origin(url: str) -> bool:
    parsed = urlsplit(url)
    return f"{parsed.scheme}://{parsed.netloc}" in LOCAL_ORIGINS


def main() -> None:
    sandbox = json.loads((ROOT / ".tmp/local-platform/sandbox.json").read_text())
    password = os.environ["AC_LOCAL_BROWSER_TEST_PASSWORD"]

    def local_only(route: Route) -> None:
        if not allowed_origin(route.request.url):
            route.abort()
        else:
            route.continue_()

    with sync_playwright() as playwright:
        browser = playwright.chromium.connect_over_cdp("http://127.0.0.1:9327")
        context = browser.contexts[0]
        opened = {}
        pages = []
        for name, origin, email, tenant_key, destination in SURFACES:
            page = (
                next(
                    (
                        existing
                        for existing in context.pages
                        if existing.url.startswith(origin + "/")
                    ),
                    None,
                )
                or context.new_page()
            )
            pages.append(page)
            # Only the app tab being opened is guarded; unrelated user tabs are untouched.
            page.route("**/*", local_only)
            try:
                page.goto(origin + "/login", wait_until="domcontentloaded")
                expect(page.get_by_label("Email address")).to_be_enabled(timeout=30000)
                page.get_by_label("Email address").fill(email)
                page.get_by_label("Password", exact=True).fill(password)
                if tenant_key:
                    page.get_by_label("Local tenant ID", exact=True).fill(sandbox[tenant_key])
                page.get_by_role("button", name="Sign in", exact=True).click()
                page.wait_for_url(
                    lambda url, base=origin: (
                        url.startswith(base + "/") and urlsplit(url).path != "/login"
                    ),
                    timeout=30000,
                )
                assert context.request.get(origin + "/v1/me", max_redirects=0).status == 200
                page.goto(origin + destination, wait_until="domcontentloaded")
                page.bring_to_front()
                opened[name] = origin + destination
            finally:
                # Always detach interception, including when an individual signin fails.
                page.unroute("**/*", local_only)
        pages[0].bring_to_front()
        # Disconnecting from separately launched Chrome keeps all three tabs and
        # their genuine local sessions available. Never close the user's browser.
        print(
            json.dumps(
                {
                    "status": "open",
                    "apps": opened,
                    "persistent_profile": "disposable-local-platform",
                }
            )
        )


if __name__ == "__main__":
    try:
        main()
    except Exception:
        raise SystemExit(
            "Local browser flow incomplete; inspect the page without copying "
            "credential fields or URLs."
        ) from None
