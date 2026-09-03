"""Playwright smoke capture for the bounded learner shell and analytics slice.

The route fixtures are intentionally descriptive and local-only. They keep the
visual check independent of a real learner account while exercising the same
browser API paths as the app. No network call leaves the local test server.
"""

from __future__ import annotations

import json
from pathlib import Path
from urllib.parse import urlparse

from playwright.sync_api import Page, Route, expect, sync_playwright


ROOT = Path(__file__).resolve().parents[1]
SCREENSHOTS = ROOT / "docs" / "evidence" / "screenshots"
BASE_URL = "http://127.0.0.1:3000"


ME = {
    "person_id": "person-1",
    "email": "learner@example.com",
    "display_name": "Alex Mercer",
    "email_verified_at": "2026-09-01T00:00:00Z",
    "selected_tenant_id": "tenant-1",
    "membership_role": "learner",
    "permissions": ["learner:read"],
}

PROGRAM = {
    "id": "program-1",
    "slug": "authority-closers-free-course",
    "title": "Authority Closers Free Course",
    "program_version_id": "version-1",
    "version_number": 1,
    "published_at": "2026-09-01T00:00:00Z",
}

LEARNING = {
    **PROGRAM,
    "program_id": "program-1",
    "program_title": "Authority Closers Free Course",
    "enrollment_id": "enrollment-1",
    "modules": [
        {
            "id": "module-1",
            "position": 1,
            "title": "Conversation foundations",
            "activities": [
                {
                    "id": "activity-1",
                    "module_id": "module-1",
                    "program_version_id": "version-1",
                    "position": 1,
                    "kind": "REFLECTION",
                    "title": "Name the next useful move",
                    "prompt": "Reflect on the next useful move.",
                    "state": "available",
                    "revision": 1,
                    "required": True,
                    "explanation": {
                        "activity_id": "activity-1",
                        "state": "available",
                        "required": True,
                        "reason": "Ready.",
                        "missing_activity_ids": [],
                        "missing_module_ids": [],
                    },
                    "allowed_actions": ["save_draft"],
                }
            ],
        }
    ],
    "projection": {
        "scope_type": "course",
        "scope_id": "program-1",
        "program_version": "1",
        "projection_version": "1",
        "denominator": 1,
        "completed_count": 0,
        "percentage": 0,
        "predicate": "required activities",
        "missing_module_ids": [],
        "activity_reasons": [],
    },
}

ANALYTICS = {
    "status": "available",
    "source": "descriptive_analytics_projection",
    "period": "week",
    "freshness_as_of": "2026-09-03T09:00:00Z",
    "retained_event_count": 4,
    "insights": [
        {
            "id": "descriptive:planning-interaction",
            "kind": "descriptive_signal",
            "title": "Planning activity is present",
            "detail": "A consented planning interaction was observed.",
            "observed_event_count": 4,
            "source_event_names": ["analytics.progress_viewed"],
        }
    ],
    "disclaimer": (
        "Descriptive product analytics only; never canonical progress, mastery, "
        "payment, entitlement, or access state."
    ),
}


def fixture_for(path: str):
    if path == "/v1/me":
        return ME
    if path.startswith("/v1/programs"):
        return {"items": [PROGRAM], "next_cursor": None}
    if path.startswith("/v1/learning/insights"):
        return ANALYTICS
    if path.startswith("/v1/learning/"):
        return LEARNING
    return None


def mock_learner_api(route: Route) -> None:
    parsed = urlparse(route.request.url)
    body = fixture_for(parsed.path)
    if body is None:
        route.continue_()
        return
    route.fulfill(
        status=200,
        content_type="application/json",
        body=json.dumps(body),
    )


def wait_for_progress(page: Page) -> None:
    # Turbopack can keep the document-load milestone open while it compiles
    # client chunks. Commit is sufficient here; the role assertions below wait
    # for the hydrated learner surface.
    page.goto(f"{BASE_URL}/progress", wait_until="commit", timeout=120_000)
    page.get_by_role("heading", name="Authority Closers Free Course").wait_for()
    page.get_by_role("heading", name="Learning rhythm").wait_for()
    page.get_by_text("Signals observed").wait_for()


def assert_active_label(page: Page, label: str) -> None:
    assert page.evaluate("document.activeElement?.getAttribute('aria-label')") == label


def main() -> None:
    SCREENSHOTS.mkdir(parents=True, exist_ok=True)
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)

        desktop = browser.new_page(viewport={"width": 1440, "height": 1000})
        desktop.route("**/v1/**", mock_learner_api)
        wait_for_progress(desktop)

        sidebar_toggle = desktop.locator(".learner-sidebar-toggle")
        expect(sidebar_toggle).to_be_visible()
        expect(sidebar_toggle).to_have_attribute("aria-expanded", "true")
        sidebar_toggle.click()
        expect(sidebar_toggle).to_have_attribute("aria-expanded", "false")
        expect(sidebar_toggle).to_have_attribute("aria-label", "Expand sidebar")
        sidebar_toggle.click()
        expect(sidebar_toggle).to_have_attribute("aria-expanded", "true")

        desktop.get_by_role("button", name="Notifications").click()
        desktop.get_by_role("dialog", name="Notifications").wait_for()
        desktop.locator(".learner-main").dispatch_event("pointerdown")
        expect(desktop.get_by_role("dialog", name="Notifications")).not_to_be_visible()
        assert_active_label(desktop, "Notifications")

        help_trigger = desktop.get_by_role("button", name="Open help chatbox")
        help_trigger.click()
        help_dialog = desktop.get_by_role("dialog", name="How can we help?")
        help_dialog.wait_for()

        # Keyboard activation of the profile trigger must close the non-modal
        # help surface instead of leaving two overlays open at once.
        account_trigger = desktop.get_by_role("button", name="Account menu for Learner")
        account_trigger.focus()
        account_trigger.press("Enter")
        desktop.locator("#learner-account-menu").wait_for()
        expect(help_dialog).not_to_be_visible()
        desktop.keyboard.press("Escape")
        expect(desktop.locator("#learner-account-menu")).not_to_be_visible()
        assert_active_label(desktop, "Account menu for Learner")

        # Dismissing a help popover from a non-focusable surface keeps focus on
        # the invoking trigger rather than dropping it on document.body.
        help_trigger.click()
        help_dialog.wait_for()
        desktop.locator(".learner-main").dispatch_event("pointerdown")
        expect(help_dialog).not_to_be_visible()
        assert_active_label(desktop, "Open help chatbox")

        desktop.screenshot(
            path=str(SCREENSHOTS / "learner-next-slice-progress-desktop.png"),
            full_page=True,
        )

        mobile = browser.new_page(viewport={"width": 390, "height": 844})
        mobile.route("**/v1/**", mock_learner_api)
        wait_for_progress(mobile)
        mobile.get_by_role("button", name="Open help chatbox").click()
        mobile.get_by_role("dialog", name="How can we help?").wait_for()
        mobile.screenshot(
            path=str(SCREENSHOTS / "learner-next-slice-progress-mobile-help.png"),
            full_page=True,
        )

        mobile.keyboard.press("Escape")
        expect(mobile.get_by_role("dialog", name="How can we help?")).not_to_be_visible()
        assert_active_label(mobile, "Open help chatbox")

        more_trigger = mobile.get_by_role("button", name="More navigation options")
        more_trigger.click()
        drawer = mobile.get_by_role("dialog", name="Alex Mercer")
        drawer.wait_for()
        close_menu = mobile.get_by_role("button", name="Close menu")
        close_menu.focus()
        mobile.keyboard.press("Shift+Tab")
        assert mobile.evaluate("document.activeElement?.closest('#learner-more-drawer') !== null")
        mobile.keyboard.press("Tab")
        assert_active_label(mobile, "Close menu")
        mobile.keyboard.press("Escape")
        expect(drawer).not_to_be_visible()
        assert_active_label(mobile, "More navigation options")

        desktop.close()
        mobile.close()
        browser.close()


if __name__ == "__main__":
    main()
