"""Settings/notification local fixture QA. Never imports private browser state."""

from __future__ import annotations

import argparse
import json
from datetime import UTC, datetime
from pathlib import Path
from urllib.parse import urlparse

import qa_alpha_surfaces as qa
from playwright.sync_api import expect, sync_playwright

BASE_FIXTURE = qa.fixture


def fixture(path: str) -> dict | None:
    if path == "/v1/onboarding":
        return {
            "person_id": "alpha-fixture-person",
            "experience_context": "sales",
            "learning_goal": "Build more confident conversations",
            "practice_situation": "A first discovery conversation",
            "weekly_minutes": 30,
            "status": "completed",
            "current_step": 4,
            "revision": 1,
            "updated_at": "2026-09-07T00:00:00Z",
            "next_action_href": "/home",
            "next_action_reason": "profile_complete",
        }
    return BASE_FIXTURE(path)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-url", required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--after", action="store_true")
    parser.add_argument("--width", action="append", type=int, choices=[320, 390, 768, 1440])
    args = parser.parse_args()
    origin = urlparse(args.base_url)
    if (
        origin.scheme not in {"http", "https"}
        or not (
            origin.hostname in {"localhost", "127.0.0.1"}
            or (origin.hostname or "").endswith(".localhost")
        )
        or origin.username
        or origin.password
        or origin.path not in {"", "/"}
        or origin.query
        or origin.fragment
    ):
        parser.error("Use a local origin without credentials/path")
    args.base_url = args.base_url.rstrip("/")
    qa.fixture = fixture
    run = args.output.resolve() / datetime.now(UTC).strftime("run-%Y%m%dT%H%M%SZ")
    run.mkdir(parents=True, exist_ok=False)
    report = {
        "evidence_class": qa.FIXTURE_LABEL,
        "created_utc": datetime.now(UTC).isoformat(),
        "user_storage_imported": False,
        "server_writes_allowed": False,
        "cases": [],
    }
    with sync_playwright() as runtime:
        browser = runtime.chromium.launch(channel="chrome", headless=True)
        report["browser_version"] = browser.version
        try:
            for width in args.width or [320, 390, 768, 1440]:
                for theme in ["light", "dark"]:
                    case = {
                        "width": width,
                        "height": 900 if width > 390 else 844,
                        "theme": theme,
                        "failures": [],
                        "screenshots": [],
                        "checks": [],
                        "page_errors": [],
                        "network": {
                            "fixture_reads": [],
                            "unknown_api_reads": [],
                            "blocked_writes": [],
                            "blocked_external": [],
                        },
                    }
                    report["cases"].append(case)
                    context = browser.new_context(
                        viewport={"width": width, "height": case["height"]},
                        color_scheme=theme,
                        reduced_motion="reduce",
                        service_workers="block",
                    )
                    context.add_init_script(
                        f"localStorage.setItem('ac-appearance-theme',{json.dumps(theme)});"
                        "localStorage.setItem('ac-appearance-motion','reduced');"
                        "localStorage.setItem('ac.learner.sidebar.collapsed.v1','true');"
                    )

                    def handle_route(route, _request, current_case=case):
                        if (
                            current_case.get("logout_fixture")
                            and route.request.method == "POST"
                            and urlparse(route.request.url).path.endswith("/v1/auth/logout")
                        ):
                            current_case["fixture_logout_requests"] = (
                                current_case.get("fixture_logout_requests", 0) + 1
                            )
                            route.fulfill(status=204)
                            return
                        if current_case.get("onboarding_failure") and urlparse(
                            route.request.url
                        ).path.endswith("/v1/onboarding"):
                            current_case["network"]["fixture_reads"].append(
                                "/v1/onboarding [injected 503]"
                            )
                            route.fulfill(
                                status=503, json={"title": "Synthetic unavailable learning setup"}
                            )
                        else:
                            qa.route_handler(route, current_case["network"], args.base_url)

                    context.route("**/*", handle_route)
                    page = context.new_page()
                    page.set_default_timeout(30000)
                    page.on(
                        "pageerror",
                        lambda error, current_case=case: current_case["page_errors"].append(
                            str(error)
                        ),
                    )

                    def capture(name: str, current_case=case, current_page=page) -> None:
                        filename = (
                            f"fixture-{current_case['width']}-{current_case['theme']}-{name}.png"
                        )
                        # Normalize scroll before full-document capture so fixed app chrome
                        # is not pictured at the native-select/hash scroll offset.
                        current_page.evaluate("window.scrollTo(0, 0)")
                        current_page.mouse.move(0, 0)
                        current_page.evaluate(
                            "() => new Promise(resolve => requestAnimationFrame("
                            "() => requestAnimationFrame(resolve)))"
                        )
                        current_page.screenshot(path=str(run / filename), full_page=True)
                        current_case["screenshots"].append(filename)
                        overflow = current_page.evaluate(
                            "Math.max(0,document.documentElement.scrollWidth-innerWidth)"
                        )
                        assert overflow <= 1, f"{name}: {overflow}px horizontal overflow"
                        for control in current_page.locator(
                            "[data-settings-panel] h2, [data-settings-panel] select, "
                            "[data-settings-panel] label small, "
                            "#learner-notifications-popover p, #learner-notifications-popover a"
                        ).all():
                            if not control.is_visible():
                                continue
                            measurement = qa.text_contrast(control)
                            current_case.setdefault("contrast", []).append(measurement)
                            assert measurement["solidColorMeasurement"], (
                                "Unsupported contrast background"
                            )
                            assert measurement["contrast"] >= 4.5, (
                                f"{name}: insufficient text contrast"
                            )

                    try:
                        page.goto(args.base_url + "/settings", wait_until="networkidle")
                        expect(
                            page.get_by_role("heading", name="Settings", exact=True)
                        ).to_be_visible()
                        # The private API result proves hydration/effects have run. Capturing
                        # server HTML too early can make Playwright's caret hiding race hydration.
                        expect(
                            page.get_by_text("alpha.fixture@example.invalid", exact=True)
                        ).to_be_attached()
                        capture("settings-entry")
                        if args.after:
                            search = page.get_by_role("searchbox", name="Search settings")
                            search.fill("motion")
                            expect(
                                page.locator('nav[aria-label="Settings sections"] a')
                            ).to_have_count(1)
                            page.locator('nav[aria-label="Settings sections"] a').focus()
                            page.locator('nav[aria-label="Settings sections"] a').press("Enter")
                            expect(
                                page.get_by_role("heading", name="Appearance", exact=True)
                            ).to_be_visible()
                            expect(
                                page.locator("[data-settings-panel] > :not([hidden]) > section")
                            ).to_have_count(1)
                            expect(page.locator("#appearance-title")).to_be_focused()
                            capture("appearance")
                            page.get_by_label("Accent color", exact=True).select_option("emerald")
                            expect(page.locator("html")).to_have_attribute("data-accent", "emerald")
                            assert (
                                page.evaluate("localStorage.getItem('ac-appearance-accent')")
                                == "emerald"
                            )
                            page.get_by_label("Accent color", exact=True).select_option("cobalt")
                            page.go_back(wait_until="networkidle")
                            expect(search).to_be_visible()
                            search.fill("zzzznothing")
                            expect(
                                page.get_by_text("No settings found", exact=True)
                            ).to_be_visible()
                            page.get_by_role("button", name="Clear search").click()
                            expect(
                                page.locator('nav[aria-label="Settings sections"] a')
                            ).to_have_count(5)
                            page.locator('a[href="#learning-setup"]').click()
                            expect(
                                page.get_by_text("Build more confident conversations", exact=True)
                            ).to_be_visible()
                            capture("learning-setup")
                            page.goto(
                                args.base_url + "/settings#security-privacy",
                                wait_until="networkidle",
                            )
                            expect(
                                page.get_by_role("heading", name="Security & privacy", exact=True)
                            ).to_be_visible()
                            capture("security")
                            if width < 761:
                                page.get_by_role("button", name="All settings", exact=True).click()
                                expect(search).to_be_focused()
                                expect(page.locator("[data-settings-panel]")).to_be_hidden()
                                page.locator('a[href="#security-privacy"]').click()
                            case["checks"].extend(
                                [
                                    "search filters control keywords",
                                    "single active panel",
                                    "heading focus",
                                    "local preference save",
                                    "back navigation",
                                    "no results recovery",
                                    "deep link",
                                ]
                            )
                        page.get_by_role("button", name="Notifications", exact=True).click()
                        expect(
                            page.get_by_role("dialog", name="Notifications", exact=True)
                        ).to_be_visible()
                        capture("notification-popover")
                        page.keyboard.press("Escape")
                        expect(
                            page.get_by_role("button", name="Notifications", exact=True)
                        ).to_be_focused()
                        expect(
                            page.get_by_role("dialog", name="Notifications", exact=True)
                        ).to_have_count(0)
                        case["checks"].append("notification Escape and focus restoration")
                        page.goto(args.base_url + "/notifications", wait_until="networkidle")
                        expect(
                            page.get_by_role("heading", name="Notifications", exact=True)
                        ).to_be_visible()
                        capture("notifications-route")
                        if args.after and width in [320, 1440] and theme == "light":
                            case["onboarding_failure"] = True
                            page.goto(
                                args.base_url + "/settings#learning-setup", wait_until="networkidle"
                            )
                            expect(
                                page.get_by_role("button", name="Retry learning setup", exact=True)
                            ).to_be_visible()
                            capture("learning-setup-failure")
                            case["onboarding_failure"] = False
                            page.get_by_role(
                                "button", name="Retry learning setup", exact=True
                            ).click()
                            expect(
                                page.get_by_text("Build more confident conversations", exact=True)
                            ).to_be_visible()
                            expect(page.locator("#learning-setup-title")).to_be_focused()
                            capture("learning-setup-recovered")
                            page.goto(
                                args.base_url + "/settings#appearance", wait_until="networkidle"
                            )
                            expect(page.get_by_label("Theme", exact=True)).to_be_visible()
                            page.evaluate(
                                "() => { Storage.prototype.setItem = function() {"
                                " throw new DOMException('Storage fixture', 'SecurityError'); }; }"
                            )
                            page.get_by_label("Theme", exact=True).select_option("dark")
                            page.get_by_label("Theme", exact=True).select_option("light")
                            expect(page.locator('#appearance [role="alert"]')).to_contain_text(
                                "session only"
                            )
                            capture("appearance-storage-unavailable")

                            def choose_category(section, current_page=page, current_width=width):
                                if current_width < 761:
                                    current_page.get_by_role(
                                        "button", name="All settings", exact=True
                                    ).click()
                                current_page.locator(f'a[href="#{section}"]').click()

                            choose_category("security-privacy")
                            choose_category("appearance")
                            expect(page.locator('#appearance [role="alert"]')).to_contain_text(
                                "session only"
                            )
                            expect(page.locator("#appearance")).not_to_contain_text(
                                "Saved on this browser"
                            )
                            capture("appearance-recovery-retained")
                            choose_category("session")
                            case["logout_fixture"] = True
                            page.evaluate("""() => { Object.defineProperty(window, 'localStorage', {
                              configurable: true, get() {
                                throw new DOMException('Fixture', 'SecurityError'); }
                            }); }""")
                            page.locator("#session").get_by_role(
                                "button", name="Sign out", exact=True
                            ).click()
                            expect(
                                page.locator("#session").get_by_role(
                                    "button", name="Retry local cleanup", exact=True
                                )
                            ).to_be_visible()
                            expect(
                                page.locator("#session").get_by_role(
                                    "button", name="Signed out", exact=True
                                )
                            ).to_be_disabled()
                            choose_category("appearance")
                            choose_category("session")
                            expect(
                                page.locator("#session").get_by_role(
                                    "button", name="Retry local cleanup", exact=True
                                )
                            ).to_be_visible()
                            page.locator("#session").get_by_role(
                                "button", name="Retry local cleanup", exact=True
                            ).click()
                            expect(page.locator('#session [role="alert"]')).to_contain_text(
                                "Clear this site's storage"
                            )
                            assert case["fixture_logout_requests"] == 1, (
                                "Cleanup retried server logout"
                            )
                            capture("session-cleanup-recovery-retained")
                            case["checks"].extend(
                                [
                                    "learning setup failure",
                                    "retry recovery and focus",
                                    "browser storage failure remains explicit",
                                    "appearance failure survives category navigation",
                                    "logout cleanup survives navigation; no second logout",
                                ]
                            )
                        assert not case["page_errors"], case["page_errors"]
                        assert not case["network"]["blocked_writes"], case["network"]
                        assert not case["network"]["unknown_api_reads"], case["network"]
                    except Exception as error:
                        case["failures"].append(str(error))
                    finally:
                        context.close()
        finally:
            browser.close()
    (run / "results.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(
        json.dumps(
            {
                "run": str(run),
                "cases": len(report["cases"]),
                "failures": [case["failures"] for case in report["cases"] if case["failures"]],
            }
        )
    )
    return int(any(case["failures"] for case in report["cases"]))


if __name__ == "__main__":
    raise SystemExit(main())
