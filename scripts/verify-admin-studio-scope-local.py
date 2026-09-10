"""Fixture-only mounted admin UI proof. Never forwards an API request or external URL."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from urllib.parse import urlsplit

from playwright.sync_api import Route, expect, sync_playwright

PERSON = "11111111-1111-4111-8111-111111111111"
SESSION = "22222222-2222-4222-8222-222222222222"
TENANT = "33333333-3333-4333-8333-333333333333"
PROGRAM = "44444444-4444-4444-8444-444444444444"
READ_ONLY_PROGRAM = "55555555-5555-4555-8555-555555555555"
VERSION = "66666666-6666-4666-8666-666666666666"
READ_ONLY_VERSION = "77777777-7777-4777-8777-777777777777"
NOW = "2026-09-07T00:00:00Z"
ETAG = '"program-version-' + "a" * 64 + '"'


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--url", default="http://127.0.0.1:3101")
    parser.add_argument("--output", required=True)
    parser.add_argument("--channel", default="chrome")
    arguments = parser.parse_args()
    origin = urlsplit(arguments.url)
    if (
        origin.hostname not in {"localhost", "127.0.0.1", "admin.localhost"}
        or origin.scheme != "http"
    ):
        raise ValueError("Only an HTTP loopback UI is permitted")
    output = Path(arguments.output).resolve()
    output.mkdir(parents=True, exist_ok=True)
    capabilities = [
        {
            "permission": permission,
            "scope_kind": "program",
            "tenant_id": TENANT,
            "program_id": program,
        }
        for permission, program in (
            ("catalog_read", PROGRAM),
            ("catalog_publish", PROGRAM),
            ("catalog_read", READ_ONLY_PROGRAM),
        )
    ]
    projection = {
        "person_id": PERSON,
        "session_id": SESSION,
        "tenant_id": TENANT,
        "studio_capabilities": capabilities,
    }
    requests: list[str] = []
    external_requests: list[str] = []
    publications: list[dict[str, object]] = []
    held: list[Route] = []
    hold_projection = True
    published = False

    def version(program_id: str) -> dict[str, object]:
        immutable = published and program_id == PROGRAM
        return {
            "id": VERSION if program_id == PROGRAM else READ_ONLY_VERSION,
            "version_number": 1,
            "status": "published" if immutable else "draft",
            "created_at": NOW,
            "published_at": NOW if immutable else None,
        }

    def program(program_id: str) -> dict[str, object]:
        return {
            "id": program_id,
            "slug": "assigned-program" if program_id == PROGRAM else "read-only-program",
            "title": "Assigned course fixture"
            if program_id == PROGRAM
            else "Read-only course fixture",
            "scope": "tenant",
            "access": "selected_tenant",
        }

    def respond(route: Route, payload: object, *, status: int = 200) -> None:
        route.fulfill(status=status, content_type="application/json", body=json.dumps(payload))

    def intercept(route: Route) -> None:
        nonlocal published
        url = urlsplit(route.request.url)
        if url.hostname not in {"localhost", "127.0.0.1", "admin.localhost"}:
            external_requests.append(url.hostname or "unknown")
            route.abort()
            return
        path = url.path
        if not path.startswith("/v1/"):
            route.continue_()
            return
        requests.append(path)
        if path == "/v1/me":
            respond(
                route,
                {
                    "person_id": PERSON,
                    "email": "coach-fixture@example.test",
                    "display_name": "Coach fixture",
                    "email_verified_at": NOW,
                    "selected_tenant_id": TENANT,
                    "membership_role": "learner",
                    "permissions": [],
                },
            )
        elif path == "/v1/context":
            respond(
                route,
                {
                    "person_id": PERSON,
                    "session_id": SESSION,
                    "tenant_id": TENANT,
                    "membership_role": "learner",
                    "permissions": [],
                },
            )
        elif path == "/v1/me/studio-access":
            if hold_projection:
                held.append(route)
            else:
                respond(route, projection)
        elif path == "/v1/admin/studio/programs":
            respond(
                route,
                {
                    "tenant_id": TENANT,
                    "truncated": False,
                    "programs": [
                        {
                            **program(identifier),
                            "version_count": 1,
                            "draft_count": 0 if published and identifier == PROGRAM else 1,
                            "current_published_version_id": VERSION
                            if published and identifier == PROGRAM
                            else None,
                            "latest_version": version(identifier),
                        }
                        for identifier in (PROGRAM, READ_ONLY_PROGRAM)
                    ],
                },
            )
        elif path in {
            f"/v1/admin/studio/programs/{PROGRAM}",
            f"/v1/admin/studio/programs/{READ_ONLY_PROGRAM}",
        }:
            identifier = path.rsplit("/", 1)[-1]
            immutable = published and identifier == PROGRAM
            respond(
                route,
                {
                    "tenant_id": TENANT,
                    **program(identifier),
                    "versions_truncated": False,
                    "versions": [
                        {
                            **version(identifier),
                            "supersedes_version_id": None,
                            "content_source_ref": "Local presentation fixture",
                            "content_reviewed_by": "Fixture reviewer",
                            "content_reviewed_at": NOW,
                            "release_id": "fixture",
                            "content_seed_kind": "reviewed",
                            "content_digest": "a" * 64,
                            "etag": None if immutable else ETAG,
                            "readiness": "immutable" if immutable else "ready",
                            "blockers": [],
                            "modules": [],
                        }
                    ],
                },
            )
        elif (
            path == f"/v1/admin/program-versions/{VERSION}/publish"
            and route.request.method == "POST"
        ):
            assert route.request.headers.get("if-match") == ETAG
            assert route.request.headers.get("idempotency-key")
            publications.append(route.request.post_data_json)
            published = True
            respond(
                route,
                {
                    "id": VERSION,
                    "program_id": PROGRAM,
                    "version_number": 1,
                    "status": "published",
                    "supersedes_version_id": None,
                    "published_at": NOW,
                    "replayed": False,
                },
            )
        else:
            respond(
                route,
                {"code": "fixture_denied", "title": "Denied", "detail": "No fixture authority"},
                status=403,
            )

    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True, channel=arguments.channel)
        context = browser.new_context(
            viewport={"width": 1440, "height": 1000}, reduced_motion="reduce"
        )
        context.route("**/*", intercept)
        page = context.new_page()
        page.goto(arguments.url + "/studio/programs", wait_until="domcontentloaded")
        expect(page.get_by_role("heading", name="Checking workspace access")).to_be_visible()
        assert page.locator(".studio-program-list").count() == 0
        page.screenshot(path=str(output / "01-loading-desktop.png"), full_page=True)
        page.wait_for_function(
            "performance.getEntriesByType('resource').some(e => e.name.includes('/v1/context'))"
        )
        page.wait_for_timeout(200)
        assert held, "self-access read must be pending"
        hold_projection = False
        for route in held:
            respond(route, projection)
        page.wait_for_load_state("networkidle")
        expect(page.get_by_role("heading", name="Assigned course fixture")).to_be_visible()
        navigation = page.get_by_role("navigation", name="Operations", exact=True)
        expect(navigation.get_by_role("link", name="Academy Studio")).to_be_visible()
        assert navigation.get_by_role("link", name="People", exact=True).count() == 0
        assert navigation.get_by_role("link", name="Learning operations").count() == 0
        page.screenshot(path=str(output / "02-scoped-programs-desktop.png"), full_page=True)
        page.get_by_role("link", name="Open program").first.click()
        page.wait_for_load_state("networkidle")
        expect(page.get_by_label("Publication reason")).to_be_enabled()
        page.get_by_label("Publication reason").fill("Reviewed local browser fixture")
        page.locator(".studio-confirmation input").check()
        page.get_by_role("button", name="Publish version 1", exact=True).click()
        expect(page.locator(".studio-publish-form")).to_have_count(0)
        assert len(publications) == 1
        page.screenshot(path=str(output / "03-publication-fixture-desktop.png"), full_page=True)
        page.goto(arguments.url + f"/studio/programs/{READ_ONLY_PROGRAM}", wait_until="networkidle")
        expect(page.get_by_label("Publication reason")).to_be_disabled()
        expect(page.get_by_role("button", name="Publish version 1", exact=True)).to_be_disabled()
        page.screenshot(path=str(output / "04-read-only-course-desktop.png"), full_page=True)
        for path in ("/people", "/learning-operations"):
            page.goto(arguments.url + path, wait_until="networkidle")
            expect(
                page.get_by_role("heading", name="Access unavailable", exact=True)
            ).to_be_visible()
            assert page.locator("form").count() == 0
        page.screenshot(path=str(output / "05-operations-denied-desktop.png"), full_page=True)
        page.set_viewport_size({"width": 390, "height": 844})
        page.goto(arguments.url + "/studio/programs", wait_until="networkidle")
        expect(page.get_by_role("heading", name="Assigned course fixture")).to_be_visible()
        assert page.evaluate("document.documentElement.scrollWidth <= window.innerWidth")
        page.screenshot(path=str(output / "06-scoped-programs-mobile.png"), full_page=True)
        assert not external_requests, f"External requests were blocked: {external_requests}"
        assert not any(path.startswith("/v1/admin/learners") for path in requests)
        browser.close()
    print(
        json.dumps(
            {
                "status": "passed",
                "evidence": str(output),
                "fixture_publications": len(publications),
                "external_requests": 0,
                "screenshots": 6,
            }
        )
    )


if __name__ == "__main__":
    main()
