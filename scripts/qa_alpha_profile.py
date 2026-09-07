"""Profile route evidence from isolated synthetic reads, never real account writes."""

from __future__ import annotations

import argparse
import json
import re
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
                        viewport={"width": width, "height": 844 if width < 768 else 900},
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
                        path = urlparse(route.request.url).path
                        if (
                            current_case.get("upload_fixture")
                            and route.request.method == "POST"
                            and path.endswith("/v1/profile/avatar")
                        ):
                            current_case["synthetic_upload_attempts"] = (
                                current_case.get("synthetic_upload_attempts", 0) + 1
                            )
                            route.fulfill(
                                status=503, json={"title": "Synthetic avatar provider unavailable"}
                            )
                        elif current_case.get("long_content") and path.endswith("/v1/me"):
                            body = fixture("/v1/me")
                            body.update(
                                {
                                    "display_name": "Alexandria Learner With A Longer Display Name",
                                    "email": (
                                        "longbutvalidaddressusedonlyforthissyntheticfixture"
                                        "@example.invalid"
                                    ),
                                }
                            )
                            current_case["network"]["fixture_reads"].append(
                                "/v1/me [long content fixture]"
                            )
                            route.fulfill(status=200, json=body)
                        elif current_case.get("secondary_failure") and (
                            path.endswith("/v1/onboarding") or path.endswith("/v1/profile/avatar")
                        ):
                            current_case["network"]["fixture_reads"].append(path + " [fixture 503]")
                            route.fulfill(status=503, json={"title": "Synthetic unavailable read"})
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

                    def shot(
                        name,
                        current_case=case,
                        current_page=page,
                        current_width=width,
                        current_theme=theme,
                    ):
                        current_page.evaluate("window.scrollTo(0,0)")
                        current_page.mouse.move(0, 0)
                        current_page.evaluate(
                            "() => new Promise(r => requestAnimationFrame("
                            "() => requestAnimationFrame(r)))"
                        )
                        current_case["screenshots"].append(
                            qa.capture(
                                current_page,
                                run,
                                f"{current_width}-{current_theme}-{name}",
                                full_page=True,
                            )
                        )

                    try:
                        page.goto(args.base_url + "/profile", wait_until="networkidle")
                        expect(
                            page.get_by_role("heading", name="Learner QA", exact=True)
                        ).to_be_visible()
                        expect(
                            page.get_by_text("alpha.fixture@example.invalid", exact=True)
                        ).to_be_visible()
                        shot("profile")
                        case["layout"] = qa.layout_metrics(page)
                        assert case["layout"]["horizontalOverflow"] <= 1
                        assert case["layout"]["theme"] == theme
                        if args.after:
                            identity = page.get_by_role("region", name="Learner QA", exact=True)
                            box = identity.bounding_box()
                            assert box and box["height"] < 330, f"Identity remains oversized: {box}"
                            case["identity_box"] = box
                            expect(page.get_by_text("Email verified", exact=True)).to_have_count(1)
                            expect(
                                page.get_by_role("heading", name="Your learning focus", exact=True)
                            ).to_be_visible()
                            expect(
                                page.get_by_text("Build more confident conversations", exact=True)
                            ).to_be_visible()
                            expect(
                                page.get_by_role("link", name="Edit learning setup", exact=True)
                            ).to_have_attribute("href", "/onboarding?return=profile")
                            expect(
                                page.get_by_role(
                                    "link",
                                    name="Continue learning Pick up your next activity",
                                    exact=True,
                                )
                            ).to_have_attribute("href", "/learning")
                            case["text_contrast"] = []
                            for text in [
                                "Learner QA",
                                "alpha.fixture@example.invalid",
                                "Email verified",
                                "Choose a photo, then crop to fit.",
                                "Your saved goals and learning routine.",
                                "What you’re working toward",
                                "Build more confident conversations",
                                "30 minutes / week",
                            ]:
                                measure = qa.text_contrast(
                                    page.locator("main").get_by_text(text, exact=True)
                                )
                                assert (
                                    measure["solidColorMeasurement"] and measure["contrast"] >= 4.5
                                ), f"Contrast: {text}: {measure}"
                                case["text_contrast"].append({"text": text, **measure})
                            case["motion"] = page.get_by_role(
                                "link",
                                name="Continue learning Pick up your next activity",
                                exact=True,
                            ).evaluate(
                                "e => ({transition:getComputedStyle(e).transitionDuration,"
                                "animation:getComputedStyle(e).animationDuration})"
                            )
                            for duration in case["motion"].values():
                                assert all(
                                    float(part.strip().removesuffix("s")) <= 0.01
                                    for part in duration.split(",")
                                ), case["motion"]
                            change_photo = page.get_by_role(
                                "button", name="Change photo", exact=True
                            )
                            target = change_photo.bounding_box()
                            assert target and target["width"] >= 44 and target["height"] >= 44
                            change_photo.focus()
                            page.keyboard.press("Tab")
                            page.keyboard.press("Shift+Tab")
                            case["keyboard_focus"] = qa.focus_visible(page)
                            expect(change_photo).to_be_focused()
                            page.keyboard.press("Enter")
                            dialog = page.get_by_role("dialog")
                            expect(dialog).to_be_visible()
                            shot("avatar-dialog")
                            for _ in range(8):
                                page.keyboard.press("Tab")
                                assert dialog.evaluate("e => e.contains(document.activeElement)"), (
                                    "Focus escaped photo editor"
                                )
                            dialog.locator('input[type="file"]').set_input_files(
                                str(
                                    qa.ROOT
                                    / "apps/learner-web/public/brand/closers-academy-v0.1"
                                    / "icon-512.png"
                                )
                            )
                            expect(
                                dialog.get_by_text(
                                    "Local preview only. Nothing has been uploaded.", exact=True
                                )
                            ).to_be_visible()
                            preview = dialog.get_by_role(
                                "group", name="Circular avatar crop preview", exact=True
                            )
                            preview.focus()
                            page.keyboard.press("+")
                            expect(preview.locator("img")).to_have_attribute(
                                "style", re.compile(r"scale\(1\.06\)")
                            )
                            page.keyboard.press("ArrowRight")
                            page.keyboard.press("Home")
                            expect(preview.locator("img")).to_have_attribute(
                                "style", re.compile(r"scale\(1\)")
                            )
                            shot("avatar-local-preview")
                            case["checks"].append(
                                "Real local PNG preview, keyboard crop/zoom/reset, "
                                "focus containment; no upload on selection"
                            )
                            if width in [320, 1440]:
                                case["upload_fixture"] = True
                                dialog.get_by_role(
                                    "button", name="Upload avatar", exact=True
                                ).click()
                                expect(dialog.get_by_role("alert")).to_contain_text(
                                    "temporarily unavailable"
                                )
                                expect(
                                    dialog.get_by_role(
                                        "img", name="Local avatar preview", exact=True
                                    )
                                ).to_be_visible()
                                expect(
                                    dialog.get_by_role("button", name="Upload avatar", exact=True)
                                ).to_be_enabled()
                                expect(
                                    page.get_by_text("Profile photo updated.", exact=True)
                                ).to_have_count(0)
                                assert case["synthetic_upload_attempts"] == 1
                                shot("avatar-fixture-unavailable")
                                case["checks"].append(
                                    "Locally intercepted upload 503 retains crop and retry, "
                                    "never shows saved; no server/provider write"
                                )
                            page.keyboard.press("Escape")
                            expect(dialog).to_have_count(0)
                            expect(change_photo).to_be_focused()
                            case["checks"].append(
                                "Keyboard opens/closes photo editor and restores focus"
                            )
                            case["secondary_failure"] = True
                            page.reload(wait_until="networkidle")
                            expect(
                                page.get_by_role("heading", name="Learner QA", exact=True)
                            ).to_be_visible()
                            expect(
                                page.get_by_role("button", name="Retry learning setup", exact=True)
                            ).to_be_visible()
                            expect(
                                page.get_by_role("button", name="Retry photo", exact=True)
                            ).to_be_visible()
                            shot("secondary-unavailable")
                            case["secondary_failure"] = False
                            page.get_by_role(
                                "button", name="Retry learning setup", exact=True
                            ).click()
                            expect(
                                page.get_by_text("Build more confident conversations", exact=True)
                            ).to_be_visible()
                            case["checks"].append(
                                "Secondary outages preserve identity; "
                                "recovery reloads source-backed setup"
                            )
                            if width == 320 and theme == "dark":
                                case["long_content"] = True
                                page.reload(wait_until="networkidle")
                                expect(
                                    page.get_by_role(
                                        "heading",
                                        name="Alexandria Learner With A Longer Display Name",
                                        exact=True,
                                    )
                                ).to_be_visible()
                                assert qa.layout_metrics(page)["horizontalOverflow"] <= 1
                                shot("long-identity")
                                case["checks"].append(
                                    "Long synthetic display name/email wrap at 320px"
                                )
                        assert not case["page_errors"], case["page_errors"]
                        assert not case["network"]["blocked_writes"], case["network"][
                            "blocked_writes"
                        ]
                        assert not case["network"]["unknown_api_reads"], case["network"][
                            "unknown_api_reads"
                        ]
                    except Exception as error:
                        case["failures"].append(str(error))
                        shot("failure")
                    finally:
                        context.close()
                        (run / "report.json").write_text(
                            json.dumps(report, indent=2), encoding="utf-8"
                        )
        finally:
            browser.close()
    report["passed"] = all(not case["failures"] for case in report["cases"])
    (run / "report.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(json.dumps({"report": str(run / "report.json"), "passed": report["passed"]}))
    return 0 if report["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
