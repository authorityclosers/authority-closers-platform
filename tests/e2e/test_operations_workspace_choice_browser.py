"""Compiled /login presentation with explicitly synthetic API responses.

This checks real Chromium rendering and interaction, not hosted authentication.
Run with AC_OPERATIONS_LOGIN_BROWSER_ORIGIN pointing to a local `next start`
and AC_OPERATIONS_LOGIN_BROWSER_EVIDENCE_DIR outside the repository.
"""

import json
import os
from pathlib import Path
from urllib.parse import urlsplit

import pytest
from playwright.sync_api import Route, expect, sync_playwright

PERSON = "11111111-1111-4111-8111-111111111111"
SESSION = "22222222-2222-4222-8222-222222222222"
TENANT = "33333333-3333-4333-8333-333333333333"


@pytest.mark.e2e
def test_compiled_operations_login_exposes_both_authorized_destinations() -> None:
    origin = os.environ.get("AC_OPERATIONS_LOGIN_BROWSER_ORIGIN")
    evidence = os.environ.get("AC_OPERATIONS_LOGIN_BROWSER_EVIDENCE_DIR")
    if not origin or not evidence:
        pytest.skip("Explicit loopback compiled Admin origin and evidence directory required")
    parsed = urlsplit(origin)
    assert parsed.scheme == "http" and parsed.hostname in {"127.0.0.1", "localhost"}
    assert parsed.path in {"", "/"} and not parsed.query and not parsed.fragment
    destination = Path(evidence)
    destination.mkdir(parents=True, exist_ok=True)
    requests: list[dict[str, str]] = []
    errors: list[str] = []
    responses = {
        "/v1/me/workspaces": {
            "person_id": PERSON,
            "session_id": SESSION,
            "selected_tenant_id": TENANT,
            "workspaces": [{"tenant_id": TENANT, "name": "Synthetic Academy"}],
        },
        "/v1/me": {
            "person_id": PERSON,
            "email": "fixture@example.test",
            "display_name": "Synthetic administrator",
            "email_verified_at": "2026-09-14T00:00:00Z",
            "selected_tenant_id": TENANT,
            "membership_role": "admin",
            "permissions": ["admin_surface"],
        },
        "/v1/context": {
            "person_id": PERSON,
            "session_id": SESSION,
            "tenant_id": TENANT,
            "membership_role": "admin",
            "permissions": ["admin_surface"],
        },
        "/v1/me/platform-access": {
            "person_id": PERSON,
            "session_id": SESSION,
            "selected_tenant_id": TENANT,
            "platform_permissions": ["platform_tenants_read"],
        },
    }

    def fixture_api(route: Route) -> None:
        path = urlsplit(route.request.url).path
        requests.append({"method": route.request.method, "path": path})
        assert route.request.method == "GET", "No implicit context write is allowed"
        assert path in responses, f"Unexpected API route: {path}"
        route.fulfill(json=responses[path], headers={"cache-control": "no-store"})

    with sync_playwright() as playwright:
        browser = playwright.chromium.launch()
        try:
            page = browser.new_page(viewport={"width": 1280, "height": 900})
            page.on("pageerror", lambda error: errors.append(str(error)))
            page.route("**/v1/**", fixture_api)
            page.goto(origin.rstrip("/") + "/login", wait_until="domcontentloaded")
            expect(page.get_by_role("heading", name="Choose your workspace.")).to_be_visible()
            expect(page.get_by_role("button", name="Open Platform Admin")).to_be_enabled()
            expect(page.get_by_role("button", name="Open workspace", exact=True)).to_be_disabled()
            expect(page.get_by_label("Workspace", exact=True)).to_have_value("")
            assert urlsplit(page.url).path == "/login"
            assert requests and all(item["method"] == "GET" for item in requests)
            page.screenshot(path=str(destination / "choice-desktop.png"), full_page=True)
            page.get_by_label("Workspace", exact=True).focus()
            page.keyboard.press("ArrowDown")
            expect(page.get_by_label("Workspace", exact=True)).to_have_value(TENANT)
            expect(page.get_by_role("button", name="Open workspace", exact=True)).to_be_enabled()
            page.keyboard.press("Tab")
            expect(page.get_by_role("button", name="Open workspace", exact=True)).to_be_focused()
            page.keyboard.press("Tab")
            expect(page.get_by_role("button", name="Open Platform Admin")).to_be_focused()
            page.set_viewport_size({"width": 390, "height": 844})
            expect(page.get_by_role("button", name="Open Platform Admin")).to_be_visible()
            assert page.evaluate("document.documentElement.scrollWidth <= innerWidth")
            page.screenshot(path=str(destination / "choice-mobile.png"), full_page=True)
            assert errors == []
            (destination / "browser-receipt.json").write_text(
                json.dumps(
                    {
                        "environment": "compiled local Next /login; synthetic API interception",
                        "checks": [
                            "dual-access account remains on login selector",
                            "no implicit context mutation",
                            "only server-listed academy is selectable",
                            "explicit platform navigation is available",
                            "keyboard selection and button focus order",
                            "390px document reflow",
                            "zero browser runtime errors",
                        ],
                        "requests": requests,
                        "browser_errors": errors,
                        "hosted_authentication_tested": False,
                        "provider_calls": 0,
                    },
                    indent=2,
                )
                + "\n",
                encoding="utf-8",
            )
        finally:
            browser.close()
