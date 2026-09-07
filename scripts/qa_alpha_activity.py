"""Interim synthetic browser QA for the mounted learner activity runtime.

This harness exercises the existing /activity/{fixture} route with deterministic
read fixtures. It never starts a server, imports a browser profile, loads
cookies/storage state, streams media, or submits a write. The media cases are
the current unavailable VIDEO path and a blocked VIDEO policy path; the other
fixtures cover the mounted activity kinds. Screenshots are explicitly interim
evidence until a release owner requests a final matrix.
"""

from __future__ import annotations

import argparse
import json
from contextlib import suppress
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from urllib.parse import unquote, urlparse

from playwright.sync_api import (
    Browser,
    BrowserContext,
    Page,
    Route,
    expect,
    sync_playwright,
)
from playwright.sync_api import (
    TimeoutError as PlaywrightTimeoutError,
)

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_OUTPUT = ROOT / "docs/evidence/screenshots/alpha-activity-interim-2026-09-07"
FIXTURE_LABEL = (
    "Synthetic API fixtures against local development UI; "
    "interim presentation evidence only; not live, streaming, or performance proof"
)

CANONICAL_FREE_COURSE_SLUG = "authority-closers-free-course"
CANONICAL_PROGRAM_ID = "e2e-canonical-free-course"
CANONICAL_PROGRAM_VERSION_ID = "e2e-canonical-free-course-v1"
CANONICAL_MODULE_ID = "e2e-canonical-free-course-module-1"
CANONICAL_ENROLLMENT_ID = "e2e-canonical-free-course-enrollment"
FIXTURE_PERSON_ID = "e2e-learner"
FIXTURE_TENANT_ID = "e2e-tenant"


@dataclass(frozen=True, slots=True)
class ActivityFixture:
    screen_id: str
    activity_id: str
    kind: str
    position: int
    title: str
    prompt: str
    allowed_actions: tuple[str, ...]
    media_state: str | None = None
    media_reason: str | None = None


VIDEO_UNAVAILABLE = ActivityFixture(
    "ACT-01",
    "73dfbbf7-5f2c-5e88-ad27-e5c84c65690f",
    "VIDEO",
    1,
    "Watch the Module 1 shift",
    "Watch the approved Module 1 content: Why High-Ticket Sales Is A Completely Different Game.",
    ("complete_video",),
    "unavailable",
    "approved_activity_media_binding_unavailable",
)

VIDEO_BLOCKED = ActivityFixture(
    "ACT-01-BLOCKED",
    "alpha-fixture-video-blocked",
    "VIDEO",
    2,
    "Watch the Module 1 shift",
    "Watch the approved Module 1 content: Why High-Ticket Sales Is A Completely Different Game.",
    ("complete_video",),
    "blocked",
    "approved_media_rendition_unavailable",
)

ACTIVITY_FIXTURES = (
    VIDEO_UNAVAILABLE,
    VIDEO_BLOCKED,
    ActivityFixture(
        "ACT-02",
        "a6d22402-b606-5987-a9d2-f5d96c8cccba",
        "REFLECTION",
        3,
        "Reflect on the shift",
        "Record your reflection after watching the Module 1 content. "
        "Your draft is saved so you can leave and resume.",
        ("save_draft", "submit_evidence"),
    ),
    ActivityFixture(
        "ACT-03",
        "00f23259-a74b-5d36-96df-e57ab9584b32",
        "IMPLEMENTATION_CHALLENGE",
        4,
        "Implement in a real situation",
        "Complete the configured offline or real-world task, "
        "then record the evidence or reflection you can support.",
        ("save_draft", "submit_evidence"),
    ),
    ActivityFixture(
        "ACT-04",
        "2c14f1cc-712c-5c71-9273-c2a68bb1b906",
        "REVIEW",
        5,
        "Review the observed pattern",
        "Capture the observed pattern after the challenge "
        "without claiming certainty beyond the evidence you recorded.",
        ("save_draft", "submit_evidence"),
    ),
    ActivityFixture(
        "ACT-05",
        "e5de3ba2-52a6-572b-8aad-9b0183035e76",
        "IMPROVE",
        6,
        "Choose the next improvement",
        "Capture one explicit behavior, correction, or next action "
        "to carry into your next attempt.",
        ("save_draft", "submit_evidence"),
    ),
)

ACTIVITY_FIXTURE_BY_ID = {fixture.activity_id: fixture for fixture in ACTIVITY_FIXTURES}

ACTIVITY_KIND_LABELS = {
    "VIDEO": "Watch",
    "REFLECTION": "Reflect",
    "IMPLEMENTATION_CHALLENGE": "Implement",
    "REVIEW": "Review",
    "IMPROVE": "Improve",
}

VIEWPORTS = {
    320: 844,
    390: 844,
    768: 900,
    1440: 900,
}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--base-url",
        required=True,
        help="Existing local learner origin, including port; no path or credentials",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=DEFAULT_OUTPUT,
        help="Parent directory for a new interim timestamped matrix",
    )
    parser.add_argument(
        "--width",
        action="append",
        type=int,
        choices=tuple(VIEWPORTS),
        help="Limit to one or more matrix widths; repeatable",
    )
    parser.add_argument(
        "--theme",
        action="append",
        choices=("light", "dark"),
        help="Limit to one or both color schemes; repeatable",
    )
    parser.add_argument(
        "--fixture",
        action="append",
        choices=tuple(ACTIVITY_FIXTURE_BY_ID),
        help="Limit to one or more activity fixture IDs; repeatable",
    )
    parser.add_argument(
        "--no-screenshots",
        action="store_true",
        help="Run checks without writing interim PNGs",
    )
    parser.add_argument("--timeout-ms", type=int, default=30_000)
    args = parser.parse_args()

    parsed = urlparse(args.base_url)
    host = parsed.hostname or ""
    if (
        parsed.scheme not in {"http", "https"}
        or not (host in {"localhost", "127.0.0.1", "::1"} or host.endswith(".localhost"))
        or parsed.username
        or parsed.password
        or parsed.path not in {"", "/"}
        or parsed.query
        or parsed.fragment
    ):
        parser.error(
            "--base-url must be a local origin without credentials, path, query, or fragment"
        )
    if args.timeout_ms < 1:
        parser.error("--timeout-ms must be positive")
    args.base_url = args.base_url.rstrip("/")
    return args


def _origin(base_url: str) -> str:
    parsed = urlparse(base_url)
    return f"{parsed.scheme}://{parsed.netloc}"


def _activity_reason(fixture: ActivityFixture) -> dict[str, object]:
    return {
        "activity_id": fixture.activity_id,
        "state": "available",
        "required": True,
        "reason": "Ready in a deterministic read-only browser fixture.",
        "missing_activity_ids": [],
        "missing_module_ids": [],
    }


def _media_descriptor(fixture: ActivityFixture) -> dict[str, object]:
    if fixture.media_state is None:
        state = "unavailable"
        reason = "activity_media_not_available"
    else:
        state = fixture.media_state
        reason = fixture.media_reason or "media_unavailable"
    return {
        "state": state,
        "reason": reason,
        "binding_id": None,
        "media_id": None,
        "media_version_id": None,
        "activity_version": "1",
        "content_type": "video/mp4",
        "duration_seconds": None,
        "width": None,
        "height": None,
        "renditions": [],
        "captions": [],
        "delivery": None,
        "playback_available": False,
    }


def _activity_response(fixture: ActivityFixture) -> dict[str, object]:
    return {
        "id": fixture.activity_id,
        "module_id": CANONICAL_MODULE_ID,
        "program_id": CANONICAL_PROGRAM_ID,
        "program_version_id": CANONICAL_PROGRAM_VERSION_ID,
        "enrollment_id": CANONICAL_ENROLLMENT_ID,
        "position": fixture.position,
        "kind": fixture.kind,
        "title": fixture.title,
        "prompt": fixture.prompt,
        "state": "available",
        "revision": 1,
        "required": True,
        "explanation": _activity_reason(fixture),
        "allowed_actions": list(fixture.allowed_actions),
        "draft_revision": 0,
        "draft_payload": None,
        "media": _media_descriptor(fixture),
    }


def _learning_response() -> dict[str, object]:
    activities = [
        {
            "id": fixture.activity_id,
            "module_id": CANONICAL_MODULE_ID,
            "program_version_id": CANONICAL_PROGRAM_VERSION_ID,
            "position": fixture.position,
            "kind": fixture.kind,
            "title": fixture.title,
            "prompt": fixture.prompt,
            "state": "available",
            "revision": 1,
            "required": True,
            "explanation": _activity_reason(fixture),
            "allowed_actions": list(fixture.allowed_actions),
        }
        for fixture in ACTIVITY_FIXTURES
    ]
    return {
        "program_id": CANONICAL_PROGRAM_ID,
        "program_version_id": CANONICAL_PROGRAM_VERSION_ID,
        "program_slug": CANONICAL_FREE_COURSE_SLUG,
        "program_title": "Authority Closers Free Course",
        "version_number": 1,
        "enrollment_id": CANONICAL_ENROLLMENT_ID,
        "modules": [
            {
                "id": CANONICAL_MODULE_ID,
                "position": 1,
                "title": "SHIFT 1 — Why High-Ticket Sales Is A Completely Different Game.",
                "activities": activities,
            }
        ],
        "projection": {
            "scope_type": "enrollment",
            "scope_id": CANONICAL_ENROLLMENT_ID,
            "program_version": CANONICAL_PROGRAM_VERSION_ID,
            "projection_version": "e2e-activity-read-only-v1",
            "denominator": len(ACTIVITY_FIXTURES),
            "completed_count": 0,
            "percentage": 0,
            "predicate": "fixture-read-only-no-completions",
            "missing_module_ids": [],
            "activity_reasons": [_activity_reason(fixture) for fixture in ACTIVITY_FIXTURES],
        },
    }


def _fixture_me_response() -> dict[str, object]:
    return {
        "person_id": FIXTURE_PERSON_ID,
        "email": "learner.e2e@example.test",
        "display_name": "E2E Learner",
        "email_verified_at": "2026-09-01T00:00:00Z",
        "selected_tenant_id": FIXTURE_TENANT_ID,
        "membership_role": "learner",
        "permissions": [],
    }


def _profile_avatar_response() -> dict[str, object]:
    return {"avatar": None, "pending": None}


def _json_response(route: Route, payload: object, *, status: int = 200) -> None:
    route.fulfill(
        status=status,
        content_type="application/json",
        body=json.dumps(payload),
    )


def _install_fixture_routes(
    context: BrowserContext,
    case: dict[str, object],
    base_url: str,
    fixture: ActivityFixture,
) -> None:
    origin = _origin(base_url)

    def handle_route(route: Route) -> None:
        request = route.request
        parsed = urlparse(request.url)
        path = parsed.path
        method = request.method.upper()

        if method not in {"GET", "HEAD", "OPTIONS"}:
            case["network"]["blocked_writes"].append(f"{method} {path}")
            _json_response(
                route,
                {
                    "title": "Synthetic activity QA blocks server writes",
                    "detail": "No activity mutation is allowed in this harness.",
                },
                status=405,
            )
            return

        if path.startswith("/v1/"):
            api_path = path[path.index("/v1/") :]
            payload: dict[str, object] | None = None
            if method == "GET" and api_path == "/v1/me":
                payload = _fixture_me_response()
            elif method == "GET" and api_path == "/v1/profile/avatar":
                payload = _profile_avatar_response()
            elif method == "GET" and api_path.startswith("/v1/activities/"):
                activity_id = unquote(api_path.removeprefix("/v1/activities/"))
                if activity_id == fixture.activity_id:
                    payload = _activity_response(fixture)
            elif method == "GET" and api_path == f"/v1/learning/{CANONICAL_PROGRAM_ID}":
                payload = _learning_response()

            if payload is None:
                case["network"]["unknown_api_blocked"].append(f"{method} {api_path}")
                _json_response(
                    route,
                    {
                        "title": "Synthetic activity QA blocks unknown API reads",
                        "detail": "No fixture exists for this API request.",
                    },
                    status=404,
                )
                return

            case["network"]["fixture_reads"].append(f"{method} {api_path}")
            _json_response(route, payload)
            return

        if f"{parsed.scheme}://{parsed.netloc}" != origin:
            case["network"]["blocked_external"].append(
                f"{method} {parsed.scheme}://{parsed.netloc}{path}"
            )
            route.abort("blockedbyclient")
            return

        route.continue_()

    context.route("**/*", handle_route)


def _attach_diagnostics(page: Page, case: dict[str, object]) -> None:
    page.on(
        "pageerror",
        lambda error: case["page_errors"].append(str(error)[:600]),
    )
    page.on(
        "console",
        lambda message: (
            case["console_errors"].append(str(message.text)[:600])
            if message.type == "error" and "/_next/webpack-hmr" not in message.text
            else None
        ),
    )


def _wait_for_render(page: Page, timeout_ms: int) -> None:
    with suppress(PlaywrightTimeoutError):
        page.wait_for_load_state("networkidle", timeout=timeout_ms)
    with suppress(Exception):
        page.evaluate(
            "document.fonts && document.fonts.ready ? document.fonts.ready : Promise.resolve()"
        )
    with suppress(PlaywrightTimeoutError):
        page.wait_for_function(
            "() => Array.from(document.images).every((img) => img.complete)",
            timeout=timeout_ms,
        )
    page.wait_for_timeout(150)


def _assert_one_canonical_title(page: Page, fixture: ActivityFixture) -> dict[str, object]:
    headings = page.locator("main h1:visible")
    expect(headings).to_have_count(1)
    actual = headings.inner_text().strip()
    assert actual == fixture.title, (
        f"Expected one canonical title {fixture.title!r}; got {actual!r}"
    )
    return {"count": headings.count(), "text": actual}


def _assert_no_leaky_copy(page: Page) -> dict[str, object]:
    body = page.locator("body").inner_text()
    forbidden = {
        "approved_activity_media_binding_unavailable": "raw unavailable reason",
        "approved_media_rendition_unavailable": "raw blocked reason",
        "Server-resolved": "completed-state implementation copy",
    }
    present = [label for value, label in forbidden.items() if value in body]
    assert not present, f"Internal/provider copy leaked into activity UI: {present}"
    floating = page.locator(
        '[data-floating-help], [class*="floating-help"], [aria-label="Floating help"]'
    )
    assert floating.count() == 0, "Unexpected floating help control is mounted"
    return {"forbidden_copy_absent": True, "floating_help_count": floating.count()}


def _assert_media_case(page: Page, fixture: ActivityFixture) -> dict[str, object]:
    assert fixture.kind == "VIDEO"
    stage = page.locator(".lesson-media-notice")
    expect(stage).to_have_count(1)
    expect(stage).to_be_visible()
    if fixture.media_state == "blocked":
        expect(
            stage.get_by_text("This video can’t be played right now", exact=True)
        ).to_be_visible()
        expected_label = f"Video for {fixture.title} unavailable"
    else:
        expect(stage.get_by_text("This video isn’t available yet", exact=True)).to_be_visible()
        expected_label = "Lesson video unavailable"
    expect(stage).to_have_attribute("aria-label", expected_label)
    assert page.locator("video").count() == 0, "Unavailable/blocked fixture mounted a video element"
    return {
        "stage": fixture.media_state,
        "accessibleLabel": expected_label,
        "videoElements": 0,
    }


def _assert_video_context(page: Page, fixture: ActivityFixture) -> dict[str, object]:
    contexts = page.locator("details.lesson-context")
    matches = []
    for index in range(contexts.count()):
        candidate = contexts.nth(index)
        if candidate.locator("summary").inner_text().strip() == "About this lesson":
            matches.append(index)
    assert len(matches) == 1, (
        "Expected exactly one About this lesson disclosure; "
        f"found {len(matches)} among {contexts.count()} lesson-context disclosures"
    )
    context = contexts.nth(matches[0])
    summary = context.locator("summary")
    assert summary.inner_text().strip() == "About this lesson"
    summary.click()
    assert context.locator("p").inner_text().strip() == fixture.prompt
    summary.click()
    return {"aboutThisLesson": True, "promptMovedOutOfTopLevelPrompt": True}


def _assert_non_video_response(page: Page, fixture: ActivityFixture) -> dict[str, object]:
    response = page.locator("#activity-response")
    expect(response).to_be_visible()
    assert not response.is_disabled(), f"{fixture.kind} response unexpectedly disabled"
    save_label = "Save reflection" if fixture.kind == "REFLECTION" else "Save draft"
    expect(page.get_by_role("button", name=save_label, exact=True)).to_be_enabled()
    expect(page.get_by_role("button", name="Submit evidence", exact=True)).to_be_enabled()
    return {"responseEnabled": True, "saveLabel": save_label}


def _focus_state(page: Page) -> dict[str, object]:
    return page.evaluate(
        """() => {
          const element = document.activeElement;
          const style = getComputedStyle(element);
          const rect = element.getBoundingClientRect();
          return {
            tag: element.tagName,
            text: (element.innerText || '').trim().slice(0, 100),
            visible: rect.width > 0 && rect.height > 0
              && rect.left >= -1 && rect.right <= innerWidth + 1,
            focusVisible: element.matches(':focus-visible'),
            outline: style.outlineStyle,
            outlineWidth: style.outlineWidth,
            boxShadow: style.boxShadow,
          };
        }"""
    )


def _assert_module_path_keyboard(page: Page, fixture: ActivityFixture) -> dict[str, object]:
    details = page.locator("details.activity-mobile-path")
    expect(details).to_have_count(1)
    if details.is_visible():
        summary = details.locator("summary").first
        summary.focus()
        assert page.locator(":focus").evaluate(
            "(element) => element.matches('details.activity-mobile-path > summary')"
        ), "Module path summary did not receive keyboard focus"
        summary.press("Enter")
        assert details.evaluate("(element) => element.open"), (
            "Module path did not open from keyboard"
        )
        path = details.locator("ol.activity-loop")
        expect(path).to_be_visible()
        path_variant = "mobile-disclosure"
    else:
        # At desktop breakpoints the same learning path is exposed as the
        # visible side panel, while the mobile disclosure is intentionally
        # display:none. Exercise its links and focus affordance directly.
        panel = page.locator(".activity-module-panel")
        expect(panel).to_be_visible()
        path = panel.locator("ol.activity-loop")
        expect(path).to_be_visible()
        path_variant = "desktop-panel"
    current = path.locator("[aria-current='step']")
    expect(current).to_have_count(1)
    links = path.locator("a[href^='/activity/']")
    assert links.count() == len(ACTIVITY_FIXTURES) - 1, (
        f"Expected every non-current activity as a link, got {links.count()}"
    )
    hrefs = []
    names = []
    for index in range(links.count()):
        link = links.nth(index)
        expect(link).to_be_visible()
        hrefs.append(link.get_attribute("href"))
        names.append(link.inner_text().strip())
    assert all(href and href.startswith("/activity/") for href in hrefs)
    assert all(names), f"Activity path link missing visible name: {names}"

    if path_variant == "mobile-disclosure":
        summary.focus()
        summary.press("Enter")
        assert not details.evaluate("(element) => element.open"), "Module path did not close"
        summary.focus()
        summary.press("Enter")
        assert details.evaluate("(element) => element.open"), "Module path did not reopen"
        page.keyboard.press("Tab")
    else:
        links.first.focus()
        assert page.locator(":focus").evaluate(
            "(element) => element.matches('a[href^=\"/activity/\"]')"
        ), "Desktop module path link did not receive keyboard focus"
        page.keyboard.press("Tab")
    focus = _focus_state(page)
    assert focus["visible"], f"Module path keyboard focus is not visible: {focus}"
    assert focus["focusVisible"], f"Module path focus lacks :focus-visible treatment: {focus}"
    assert path.evaluate("(element) => element.contains(document.activeElement)")
    if path_variant == "mobile-disclosure":
        summary.focus()
        summary.press("Enter")
    return {
        "links": links.count(),
        "currentStepCount": current.count(),
        "focus": focus,
        "variant": path_variant,
    }


def _layout_metrics(page: Page) -> dict[str, object]:
    return page.evaluate(
        """() => {
          const root = document.documentElement;
          const body = document.body;
          const offenders = [];
          for (const element of document.querySelectorAll('body *')) {
            const style = getComputedStyle(element);
            if (style.display === 'none' || style.visibility === 'hidden') continue;
            const rect = element.getBoundingClientRect();
            if (rect.width === 0 && rect.height === 0) continue;
            if (rect.left < -1 || rect.right > innerWidth + 1) {
              offenders.push({
                tag: element.tagName.toLowerCase(),
                className: typeof element.className === 'string' ? element.className : '',
                left: Math.round(rect.left * 10) / 10,
                right: Math.round(rect.right * 10) / 10,
              });
            }
          }
          return {
            viewport: {width: innerWidth, height: innerHeight},
            documentWidth: Math.max(root.scrollWidth, body.scrollWidth),
            horizontalOverflow: Math.max(
              0, Math.max(root.scrollWidth, body.scrollWidth) - innerWidth
            ),
            offenders: offenders.slice(0, 12),
          };
        }"""
    )


def _assert_layout(page: Page) -> dict[str, object]:
    metrics = _layout_metrics(page)
    assert metrics["horizontalOverflow"] <= 1, f"Horizontal overflow: {metrics}"
    assert not metrics["offenders"], f"Off-canvas visible elements: {metrics['offenders']}"
    return metrics


def _assert_touch_targets(page: Page) -> dict[str, object]:
    controls = page.locator(
        ".activity-workspace .button, .activity-workspace button, "
        ".activity-workspace .activity-shell__breadcrumb a, "
        ".activity-workspace .activity-loop a, "
        ".activity-workspace .activity-module-panel__back, "
        ".activity-workspace summary"
    )
    undersized = []
    for index in range(controls.count()):
        control = controls.nth(index)
        if not control.is_visible():
            continue
        box = control.bounding_box()
        if not box:
            continue
        if box["width"] < 40 or box["height"] < 40:
            undersized.append(
                f"{control.inner_text().strip()!r}={box['width']:.1f}x{box['height']:.1f}"
            )
    assert not undersized, f"Touch targets below 40 CSS px: {undersized}"
    return {"checked": controls.count(), "undersized": undersized}


def _assert_reduced_motion(page: Page) -> dict[str, object]:
    state = page.evaluate(
        """() => ({
          mediaQuery: window.matchMedia('(prefers-reduced-motion: reduce)').matches,
          dataMotion: document.documentElement.getAttribute('data-motion'),
          dataReducedMotion: document.documentElement.getAttribute('data-reduced-motion')
        })"""
    )
    assert state["mediaQuery"], "Playwright reduced-motion media emulation is not active"
    assert state["dataReducedMotion"] == "true", f"App did not expose reduced-motion state: {state}"
    return state


def _assert_requested_theme(page: Page, theme: str) -> dict[str, object]:
    state = page.evaluate(
        """() => ({
          dataTheme: document.documentElement.getAttribute('data-theme'),
          preference: document.documentElement.getAttribute('data-theme-preference'),
          bodyBackground: getComputedStyle(document.body).backgroundColor,
          bodyText: getComputedStyle(document.body).color,
        })"""
    )
    assert state["dataTheme"] == theme, f"Requested {theme} theme did not apply: {state}"
    assert state["preference"] == theme, f"Requested {theme} preference did not persist: {state}"
    return state


def _capture(
    page: Page, run_dir: Path, fixture: ActivityFixture, theme: str, width: int, height: int
) -> str:
    name = (
        f"interim-activity-{fixture.screen_id.lower()}-"
        f"{fixture.media_state or 'form'}-{theme}-{width}x{height}.png"
    )
    path = run_dir / name
    page.evaluate("window.scrollTo(0, 0)")
    page.screenshot(path=str(path), full_page=True)
    return str(path.relative_to(ROOT))


def _new_case(
    browser: Browser,
    args: argparse.Namespace,
    run_dir: Path,
    fixture: ActivityFixture,
    theme: str,
    width: int,
    height: int,
) -> dict[str, object]:
    case: dict[str, object] = {
        "fixture": fixture.activity_id,
        "screenId": fixture.screen_id,
        "kind": fixture.kind,
        "mediaState": fixture.media_state,
        "theme": theme,
        "viewport": {"width": width, "height": height},
        "evidenceClass": FIXTURE_LABEL,
        "checks": {},
        "screenshots": [],
        "network": {
            "fixture_reads": [],
            "unknown_api_blocked": [],
            "blocked_writes": [],
            "blocked_external": [],
        },
        "page_errors": [],
        "console_errors": [],
        "failures": [],
    }
    context = browser.new_context(
        viewport={"width": width, "height": height},
        color_scheme=theme,
        reduced_motion="reduce",
        service_workers="block",
    )
    # Keep theme/motion initialization identical to the existing local QA
    # harnesses. color_scheme alone is insufficient because the app preference
    # can override the OS/browser color scheme during its pre-paint init.
    context.add_init_script(
        f"localStorage.setItem('ac-appearance-theme',{json.dumps(theme)});"
        "localStorage.setItem('ac-appearance-motion','reduced');"
        "localStorage.setItem('ac.learner.sidebar.collapsed.v1','true');"
    )
    _install_fixture_routes(context, case, args.base_url, fixture)
    page = context.new_page()
    page.set_default_timeout(args.timeout_ms)
    _attach_diagnostics(page, case)
    try:
        response = page.goto(
            f"{args.base_url}/activity/{fixture.activity_id}",
            wait_until="domcontentloaded",
            timeout=args.timeout_ms,
        )
        assert response is not None, "Activity navigation returned no response"
        assert response.status < 400, f"Activity navigation returned HTTP {response.status}"
        _wait_for_render(page, args.timeout_ms)
        expect(page.locator("main#main-content")).to_be_visible()
        expect(page.locator(".activity-workspace")).to_be_visible()
        case["checks"]["title"] = _assert_one_canonical_title(page, fixture)
        case["checks"]["leakyCopy"] = _assert_no_leaky_copy(page)
        assert (
            page.locator(".activity-shell__header .status-pill").inner_text().strip() == "Available"
        )
        kind_label = ACTIVITY_KIND_LABELS[fixture.kind]
        rendered_kind = page.locator(".activity-shell__type").inner_text().strip()
        assert kind_label.casefold() in rendered_kind.casefold(), (
            f"Expected activity kind {kind_label!r}; got {rendered_kind!r}"
        )
        if fixture.kind == "VIDEO":
            case["checks"]["media"] = _assert_media_case(page, fixture)
            case["checks"]["videoContext"] = _assert_video_context(page, fixture)
        else:
            expect(page.locator(".activity-prompt")).to_be_visible()
            expect(page.locator(".activity-prompt")).to_contain_text(fixture.prompt)
            case["checks"]["response"] = _assert_non_video_response(page, fixture)
        case["checks"]["modulePathKeyboard"] = _assert_module_path_keyboard(page, fixture)
        case["checks"]["layout"] = _assert_layout(page)
        case["checks"]["touchTargets"] = _assert_touch_targets(page)
        case["checks"]["reducedMotion"] = _assert_reduced_motion(page)
        case["checks"]["requestedTheme"] = _assert_requested_theme(page, theme)
        assert not case["page_errors"], f"Page errors: {case['page_errors']}"
        assert not case["console_errors"], f"Console errors: {case['console_errors']}"
        assert not case["network"]["unknown_api_blocked"], (
            f"Unknown API reads were blocked: {case['network']['unknown_api_blocked']}"
        )
        assert not case["network"]["blocked_writes"], (
            f"Server writes were blocked: {case['network']['blocked_writes']}"
        )
        assert not case["network"]["blocked_external"], (
            f"External requests were blocked: {case['network']['blocked_external']}"
        )
        if not args.no_screenshots:
            case["screenshots"].append(_capture(page, run_dir, fixture, theme, width, height))
    except Exception as error:
        case["failures"].append(f"{type(error).__name__}: {str(error)[:700]}")
        if not args.no_screenshots:
            with suppress(Exception):
                case["screenshots"].append(_capture(page, run_dir, fixture, theme, width, height))
    finally:
        context.close()
    return case


def main() -> int:
    args = parse_args()
    run_dir = args.output.resolve() / datetime.now(UTC).strftime("run-%Y%m%dT%H%M%S%fZ")
    run_dir.mkdir(parents=True, exist_ok=False)
    report: dict[str, object] = {
        "evidenceClass": FIXTURE_LABEL,
        "interimOnly": True,
        "baseUrl": args.base_url,
        "createdUtc": datetime.now(UTC).isoformat(),
        "freshBrowserContext": True,
        "userProfileLoaded": False,
        "cookiesLoaded": False,
        "storageStateLoaded": False,
        "serverWritesAllowed": False,
        "unknownApiReadsAllowed": False,
        "screenshotMode": "interim" if not args.no_screenshots else "disabled",
        "browserVersion": None,
        "cases": [],
    }
    fixtures = [
        fixture
        for fixture in ACTIVITY_FIXTURES
        if not args.fixture or fixture.activity_id in args.fixture
    ]
    if not fixtures:
        raise SystemExit("No fixtures selected")
    widths = args.width or list(VIEWPORTS)
    themes = args.theme or ["light", "dark"]

    with sync_playwright() as runtime:
        browser = runtime.chromium.launch(channel="chrome", headless=True)
        report["browserVersion"] = browser.version
        try:
            for fixture in fixtures:
                for theme in themes:
                    for width in widths:
                        case = _new_case(
                            browser,
                            args,
                            run_dir,
                            fixture,
                            theme,
                            width,
                            VIEWPORTS[width],
                        )
                        report["cases"].append(case)
                        print(
                            json.dumps(
                                {
                                    "fixture": fixture.activity_id,
                                    "theme": theme,
                                    "width": width,
                                    "failures": case["failures"],
                                }
                            ),
                            flush=True,
                        )
                        (run_dir / "results.json").write_text(
                            json.dumps(report, indent=2),
                            encoding="utf-8",
                        )
        finally:
            browser.close()

    cases = report["cases"]
    assert isinstance(cases, list)
    report["failureCount"] = sum(len(case["failures"]) for case in cases)
    report["blockedWriteCount"] = sum(len(case["network"]["blocked_writes"]) for case in cases)
    report["unknownApiBlockedCount"] = sum(
        len(case["network"]["unknown_api_blocked"]) for case in cases
    )
    report["blockedExternalCount"] = sum(len(case["network"]["blocked_external"]) for case in cases)
    report["fixtureReadPaths"] = sorted(
        {path for case in cases for path in case["network"]["fixture_reads"]}
    )
    (run_dir / "results.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(
        json.dumps(
            {
                "output": str(run_dir),
                "cases": len(cases),
                "failureCount": report["failureCount"],
                "blockedWriteCount": report["blockedWriteCount"],
                "unknownApiBlockedCount": report["unknownApiBlockedCount"],
                "blockedExternalCount": report["blockedExternalCount"],
            }
        ),
        flush=True,
    )
    return 1 if report["failureCount"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
