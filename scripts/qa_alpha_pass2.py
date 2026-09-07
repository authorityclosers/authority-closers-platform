"""Before/after local presentation captures; synthetic fixtures, never live proof.

Reuses the isolated-origin/write-blocking harness. No server is started or changed.
Use --output to select the before or after evidence parent. Every run is unique.
"""

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
ACTIVITY = {
    "id": "alpha-fixture-reflection",
    "module_id": "alpha-fixture-module",
    "program_version_id": qa.PROGRAM["program_version_id"],
    "position": 2,
    "kind": "REFLECTION",
    "title": "Reflect on your next conversation",
    "prompt": None,
    "state": "available",
    "revision": 1,
    "required": True,
    "allowed_actions": ["save_draft"],
    "explanation": {
        "activity_id": "alpha-fixture-reflection",
        "state": "available",
        "required": True,
        "reason": "Synthetic available activity",
        "missing_activity_ids": [],
        "missing_module_ids": [],
    },
}


def presentation_fixture(path: str) -> dict | None:
    if path == "/v1/onboarding":
        return {
            "person_id": "alpha-fixture-person",
            "experience_context": None,
            "learning_goal": None,
            "practice_situation": None,
            "weekly_minutes": None,
            "status": "completed",
            "current_step": 4,
            "revision": 1,
            "updated_at": "2026-09-07T00:00:00Z",
            "next_action_href": "/home",
            "next_action_reason": "profile_complete",
        }
    if path == "/v1/learning/calendar":
        return {
            "source": "explicit_learning_plan",
            "disclaimer": "Synthetic presentation fixture only.",
            "periods": {
                period: {
                    "period": period,
                    "status": "not_configured",
                    "source": "explicit_learning_plan",
                    "message": None,
                    "items": [],
                }
                for period in ("today", "week", "month")
            },
        }
    if path == f"/v1/learning/{qa.PROGRAM['id']}":
        return {
            **qa.COURSE,
            "modules": [
                {
                    "id": "alpha-fixture-module",
                    "position": 1,
                    "title": "Building a thoughtful conversation",
                    "activities": [ACTIVITY],
                }
            ],
        }
    return BASE_FIXTURE(path)


def fixture_route_handler(network: dict, origin: str):
    return lambda route: qa.route_handler(route, network, origin)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-url", required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--timeout-ms", type=int, default=30000)
    parser.add_argument(
        "--route", action="append", choices=["/", "/home", "/discover", "/learning"]
    )
    parser.add_argument("--width", type=int, action="append", choices=[1440, 390, 320])
    parser.add_argument("--theme", action="append", choices=["light", "dark"])
    args = parser.parse_args()
    origin = urlparse(args.base_url)
    host = origin.hostname or ""
    if (
        origin.scheme not in {"http", "https"}
        or not (host in {"localhost", "127.0.0.1", "::1"} or host.endswith(".localhost"))
        or origin.username
        or origin.password
        or origin.path not in {"", "/"}
        or origin.query
        or origin.fragment
        or args.timeout_ms < 1
    ):
        parser.error("Expected a local origin without credentials/path and a positive timeout")
    args.base_url = args.base_url.rstrip("/")
    qa.fixture = presentation_fixture
    run_dir = args.output.resolve() / datetime.now(UTC).strftime("run-%Y%m%dT%H%M%SZ")
    run_dir.mkdir(parents=True, exist_ok=False)
    report = {
        "evidence_class": qa.FIXTURE_LABEL,
        "base_url": args.base_url,
        "created_utc": datetime.now(UTC).isoformat(),
        "user_cookies_or_storage_loaded": False,
        "server_writes_allowed": False,
        "cases": [],
    }
    with sync_playwright() as runtime:
        browser = runtime.chromium.launch(channel="chrome", headless=True)
        report["browser_version"] = browser.version
        try:
            for route, title in (
                ("/", "Practice what changes your"),
                ("/home", "Welcome back, Learner QA"),
                ("/discover", "Discover Programs"),
                ("/learning", "My Learning"),
            ):
                if args.route and route not in args.route:
                    continue
                for theme in ("light", "dark"):
                    if args.theme and theme not in args.theme:
                        continue
                    for width, height in ((1440, 900), (390, 844), (320, 844)):
                        if args.width and width not in args.width:
                            continue
                        case = {
                            "route": route,
                            "theme": theme,
                            "width": width,
                            "height": height,
                            "failures": [],
                            "screenshots": [],
                            "page_errors": [],
                            "network": {
                                "fixture_reads": [],
                                "unknown_api_reads": [],
                                "blocked_writes": [],
                                "blocked_external": [],
                            },
                        }
                        context = browser.new_context(
                            viewport={"width": width, "height": height},
                            color_scheme=theme,
                            reduced_motion="reduce",
                            service_workers="block",
                        )
                        context.add_init_script(
                            f"localStorage.setItem('ac-appearance-theme', {json.dumps(theme)});"
                            "localStorage.setItem('ac-appearance-motion','reduced');"
                            "localStorage.setItem('ac.learner.sidebar.collapsed.v1','false');"
                        )
                        context.route(
                            "**/*",
                            fixture_route_handler(case["network"], args.base_url),
                        )
                        page = context.new_page()
                        page.set_default_timeout(args.timeout_ms)
                        page.on(
                            "pageerror",
                            lambda error, current_case=case: current_case["page_errors"].append(
                                str(error)[:400]
                            ),
                        )
                        prefix = f"fixture-{route.strip('/') or 'public'}-{theme}-{width}x{height}"
                        try:
                            page.goto(f"{args.base_url}{route}", wait_until="networkidle")
                            expect(
                                page.get_by_role("heading", name=re.compile(re.escape(title)))
                            ).to_be_visible()
                            if route == "/home":
                                expect(page.locator(".continue-learning-card")).to_be_visible()
                            else:
                                expect(
                                    page.get_by_role(
                                        "heading", name=qa.PROGRAM["title"], exact=True
                                    )
                                ).to_be_visible()
                            page.locator("main img").evaluate_all("""async images => {
                              const visible=images.filter(e=>{const r=e.getBoundingClientRect();
                                return r.width>0&&r.height>0&&r.top<innerHeight&&r.bottom>0});
                              await Promise.race([
                                Promise.all(visible.map(image=>image.decode().catch(()=>{}))),
                                new Promise(resolve=>setTimeout(resolve,10000))]);
                            }""")
                            case["layout"] = qa.layout_metrics(page)
                            assert case["layout"]["horizontalOverflow"] <= 1, "Horizontal overflow"
                            case["artwork"] = page.locator(
                                "main img"
                            ).evaluate_all("""images=>images.map(e=>({
                              alt:e.alt,width:e.width,height:e.height,naturalWidth:e.naturalWidth,
                              naturalHeight:e.naturalHeight,complete:e.complete,
                              visible:e.getBoundingClientRect().width>0
                                &&e.getBoundingClientRect().height>0
                                &&e.getBoundingClientRect().top<innerHeight
                                &&e.getBoundingClientRect().bottom>0}))""")
                            assert all(
                                not image["visible"]
                                or (image["complete"] and image["naturalWidth"] > 0)
                                for image in case["artwork"]
                            ), "Missing artwork"
                            if route in {"/discover", "/learning"}:
                                card = page.locator(".ac-program-card").first
                                expect(card.get_by_role("heading")).to_have_count(1)
                                assert card.locator(".ac-program-card__media").inner_text() == "", (
                                    "Decorative cover duplicates server text"
                                )
                            if route == "/home" and width < 620:
                                cta = page.locator(".continue-mobile-cta .button")
                                case["primary_cta_contrast"] = qa.text_contrast(cta)
                                assert case["primary_cta_contrast"]["contrast"] >= 4.5, (
                                    "Mobile primary CTA contrast below 4.5:1"
                                )
                            if route == "/":
                                for area, selector in (
                                    (
                                        "header",
                                        ".site-header .brand > span, "
                                        ".site-header .public-nav a:visible",
                                    ),
                                    (
                                        "footer",
                                        ".site-footer .brand > span, .site-footer__inner > p, "
                                        ".site-footer__links a:visible",
                                    ),
                                ):
                                    case[f"public_{area}_contrast"] = []
                                    for label in page.locator(selector).all():
                                        measurement = qa.text_contrast(label)
                                        case[f"public_{area}_contrast"].append(
                                            {"label": label.inner_text(), **measurement}
                                        )
                                        assert measurement["solidColorMeasurement"], (
                                            f"Public {area} requires a solid-color measurement"
                                        )
                                        assert measurement["contrast"] >= 4.5, (
                                            f"Public {area} contrast below 4.5:1: "
                                            f"{label.inner_text()}"
                                        )
                            assert not case["page_errors"], "Browser page errors"
                            assert not case["network"]["unknown_api_reads"], (
                                "Unmatched fixture read"
                            )
                            case["screenshots"].append(qa.capture(page, run_dir, prefix))
                            if width != 320:
                                # Scroll naturally to load below-fold artwork before full-page QA.
                                for picture in page.locator("main img").all():
                                    if picture.is_visible():
                                        picture.scroll_into_view_if_needed()
                                        picture.evaluate("image=>image.decode().catch(()=>{})")
                                page.evaluate("window.scrollTo(0,0)")
                                case["screenshots"].append(
                                    qa.capture(page, run_dir, prefix + "-full", full_page=True)
                                )
                        except Exception as error:
                            case["failures"].append(f"{type(error).__name__}: {str(error)[:600]}")
                            case["screenshots"].append(
                                qa.capture(page, run_dir, prefix + "-failure")
                            )
                        finally:
                            context.close()
                        report["cases"].append(case)
                        (run_dir / "results.json").write_text(
                            json.dumps(report, indent=2), encoding="utf-8"
                        )
                        print(
                            json.dumps(
                                {
                                    "route": route,
                                    "theme": theme,
                                    "width": width,
                                    "failures": case["failures"],
                                }
                            ),
                            flush=True,
                        )
        finally:
            browser.close()
    report["failure_count"] = sum(len(case["failures"]) for case in report["cases"])
    report["blocked_write_count"] = sum(
        len(case["network"]["blocked_writes"]) for case in report["cases"]
    )
    (run_dir / "results.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(
        json.dumps({"output": str(run_dir), "failure_count": report["failure_count"]}), flush=True
    )
    return 1 if report["failure_count"] or report["blocked_write_count"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
