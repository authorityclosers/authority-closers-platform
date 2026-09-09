"""Actual local coach login and scoped Studio reads; no publication or remote requests."""

from __future__ import annotations

import json
import os
from pathlib import Path
from urllib.parse import urlsplit

from playwright.sync_api import Route, expect, sync_playwright

ROOT = Path(__file__).resolve().parents[1]
ORIGIN = "http://admin.localhost:3101"


def main() -> None:
    sandbox = json.loads((ROOT / ".tmp/local-platform/sandbox.json").read_text())
    password = os.environ["AC_LOCAL_BROWSER_TEST_PASSWORD"]
    output = ROOT / "docs/evidence/screenshots/local-admin-session-20260907"
    output.mkdir(parents=True, exist_ok=True)
    external_requests: list[str] = []

    def local_only(route: Route) -> None:
        if urlsplit(route.request.url).hostname not in {"admin.localhost", "127.0.0.1"}:
            external_requests.append("blocked")
            route.abort()
        else:
            route.continue_()

    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(channel="chrome", headless=True)
        context = browser.new_context(viewport={"width": 1440, "height": 1000})
        context.route("**/*", local_only)
        page = context.new_page()
        page.goto(ORIGIN + "/login", wait_until="networkidle")
        expect(page.get_by_text("Local sandbox session", exact=True)).to_be_visible()
        expect(page.get_by_label("Email address")).to_be_enabled(timeout=30000)
        page.get_by_label("Email address").fill("coach@ac.localhost")
        page.get_by_label("Password", exact=True).fill(password)
        page.get_by_label("Local tenant ID", exact=True).fill(sandbox["academy_tenant_id"])
        page.get_by_role("button", name="Sign in", exact=True).click()
        page.wait_for_url("**/studio/programs", timeout=30000)
        expect(page.get_by_role("heading", name="Programs and versions")).to_be_visible()
        expect(page.get_by_role("link", name="Open program")).to_have_count(1, timeout=30000)
        navigation = page.get_by_role("navigation", name="Operations", exact=True)
        expect(navigation.get_by_role("link", name="Academy Studio")).to_be_visible()
        expect(navigation.get_by_role("link", name="People", exact=True)).to_have_count(0)
        page.screenshot(path=str(output / "01-real-coach-studio.png"), full_page=True)
        me = await_json(context.request.get(ORIGIN + "/v1/me"))
        assert me["membership_role"] == "learner" and me["permissions"] == []
        projection = await_json(context.request.get(ORIGIN + "/v1/me/studio-access"))
        assert projection["tenant_id"] == sandbox["academy_tenant_id"]
        assert projection["studio_capabilities"]
        assert all(
            item["scope_kind"] == "program" and item["program_id"] == sandbox["studio_program_id"]
            for item in projection["studio_capabilities"]
        )
        page.get_by_role("link", name="Open program").click()
        page.wait_for_load_state("networkidle")
        expect(page.get_by_role("heading", name="Program readiness")).to_be_visible()
        page.screenshot(path=str(output / "02-real-coach-program.png"), full_page=True)
        for path in ("/people", "/learning-operations"):
            page.goto(ORIGIN + path, wait_until="networkidle")
            expect(
                page.get_by_role("heading", name="Access unavailable", exact=True)
            ).to_be_visible()
            expect(page.locator("form")).to_have_count(0)
        page.screenshot(path=str(output / "03-real-coach-operations-denied.png"), full_page=True)
        denied = context.request.post(
            ORIGIN + "/v1/admin/enrollment-grants",
            headers={"origin": ORIGIN, "idempotency-key": "local-coach-denial-check"},
            data={
                "person_id": me["person_id"],
                "program_version_id": "11111111-1111-4111-8111-111111111111",
                "reason": "Local scoped coach denial check",
            },
        )
        assert denied.status == 403
        logout = context.request.post(ORIGIN + "/v1/auth/logout", headers={"origin": ORIGIN})
        assert logout.status == 204
        assert context.request.get(ORIGIN + "/v1/me").status == 401
        assert not external_requests
        browser.close()
    print(
        json.dumps(
            {
                "status": "passed",
                "real_local_session": True,
                "external_requests": 0,
                "scoped_programs": 1,
                "screenshots": 3,
                "logged_out": True,
            }
        )
    )


def await_json(response):
    assert response.status == 200
    return response.json()


if __name__ == "__main__":
    try:
        main()
    except Exception:
        raise SystemExit(
            "Local admin proof incomplete; no credential or request diagnostics are emitted."
        ) from None
