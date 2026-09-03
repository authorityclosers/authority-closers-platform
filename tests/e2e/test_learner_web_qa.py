"""Browser-level visual and accessibility checks for the learner web surface.

The route/state cases are intentionally driven by the non-production ``state``
query supported by the app. This keeps the harness honest: it verifies the
presentation and recovery contract without fabricating identity, enrollment,
progress, media, or certificate data.

Run with a local learner server and ``AC_LEARNER_E2E_BASE_URL`` set. The test
is skipped when Playwright or the base URL is unavailable, matching the
repository's existing browser regression convention.
"""

from __future__ import annotations

import json
import os
from collections.abc import Iterator
from contextlib import suppress
from dataclasses import dataclass
from pathlib import Path
from typing import Final
from urllib.parse import unquote, urlparse

import pytest

pytest.importorskip("playwright.sync_api")
from playwright.sync_api import (  # noqa: E402
    Browser,
    BrowserContext,
    Page,
    Route,
    sync_playwright,
)
from playwright.sync_api import (
    TimeoutError as PlaywrightTimeoutError,
)


@dataclass(frozen=True, slots=True)
class Viewport:
    name: str
    width: int
    height: int


@dataclass(frozen=True, slots=True)
class RouteSpec:
    flow_id: str
    screen_id: str
    path: str
    shell: str
    state_simulation: bool = True
    activity_kind: str | None = None


@dataclass(frozen=True, slots=True)
class ActivityFixture:
    """Read-only API data used to render one activity kind in browser QA.

    This is deliberately a presentation fixture. It contains no completion,
    evidence, playback, or draft mutation result and is never sent to the
    application as if it were a canonical server write.
    """

    screen_id: str
    activity_id: str
    kind: str
    position: int
    title: str
    prompt: str
    allowed_actions: tuple[str, ...]


CANONICAL_FREE_COURSE_SLUG: Final = "authority-closers-free-course"
CANONICAL_PROGRAM_ID: Final = "e2e-canonical-free-course"
CANONICAL_PROGRAM_VERSION_ID: Final = "e2e-canonical-free-course-v1"
CANONICAL_MODULE_ID: Final = "e2e-canonical-free-course-module-1"
CANONICAL_ENROLLMENT_ID: Final = "e2e-canonical-free-course-enrollment"
FIXTURE_PERSON_ID: Final = "e2e-learner"
FIXTURE_TENANT_ID: Final = "e2e-tenant"

# These are the distinct activity route IDs recorded by the exact staging
# journey evidence. The browser fixture below serves deterministic read data
# for them so local QA does not require an external learner or a write.
ACTIVITY_FIXTURES: Final[tuple[ActivityFixture, ...]] = (
    ActivityFixture(
        "ACT-01",
        "73dfbbf7-5f2c-5e88-ad27-e5c84c65690f",
        "VIDEO",
        1,
        "Watch the Module 1 shift",
        "Watch the approved Module 1 content: Why High-Ticket Sales Is A "
        "Completely Different Game.",
        ("complete_video",),
    ),
    ActivityFixture(
        "ACT-02",
        "a6d22402-b606-5987-a9d2-f5d96c8cccba",
        "REFLECTION",
        2,
        "Reflect on the shift",
        "Record your reflection after watching the Module 1 content. Your "
        "draft is saved so you can leave and resume.",
        ("save_draft", "submit_evidence"),
    ),
    ActivityFixture(
        "ACT-03",
        "00f23259-a74b-5d36-96df-e57ab9584b32",
        "IMPLEMENTATION_CHALLENGE",
        3,
        "Implement in a real situation",
        "Complete the configured offline or real-world task, then record the "
        "evidence or reflection you can support.",
        ("save_draft", "submit_evidence"),
    ),
    ActivityFixture(
        "ACT-04",
        "2c14f1cc-712c-5c71-9273-c2a68bb1b906",
        "REVIEW",
        4,
        "Review the observed pattern",
        "Capture the observed pattern after the challenge without claiming "
        "certainty beyond the evidence you recorded.",
        ("save_draft", "submit_evidence"),
    ),
    ActivityFixture(
        "ACT-05",
        "e5de3ba2-52a6-572b-8aad-9b0183035e76",
        "IMPROVE",
        5,
        "Choose the next improvement",
        "Capture one explicit behavior, correction, or next action to carry "
        "into your next attempt.",
        ("save_draft", "submit_evidence"),
    ),
)
ACTIVITY_FIXTURE_BY_ID: Final[dict[str, ActivityFixture]] = {
    fixture.activity_id: fixture for fixture in ACTIVITY_FIXTURES
}

ACTIVITY_KIND_LABELS: Final[dict[str, str]] = {
    "VIDEO": "Watch",
    "REFLECTION": "Reflect",
    "IMPLEMENTATION_CHALLENGE": "Implement",
    "REVIEW": "Review",
    "IMPROVE": "Improve",
}


REFERENCE_VIEWPORTS: Final[tuple[Viewport, ...]] = (
    Viewport("320", 320, 568),
    Viewport("390", 390, 844),
    Viewport("430", 430, 932),
    Viewport("768", 768, 1024),
    Viewport("1024", 1024, 1024),
    Viewport("1440", 1440, 1024),
)

SURFACE_STATES: Final[tuple[str, ...]] = (
    "LOADING",
    "EMPTY",
    "ERROR_RETRYABLE",
    "ERROR_TERMINAL",
    "OFFLINE",
    "PERMISSION_DENIED",
    "LOCKED",
    "PARTIAL",
    "SUCCESS_FEEDBACK",
)

STATE_TITLES: Final[dict[str, str]] = {
    "EMPTY": "This surface has no content to show",
    "ERROR_RETRYABLE": "This view did not finish loading",
    "ERROR_TERMINAL": "This view cannot be opened right now",
    "OFFLINE": "You are offline",
    "PERMISSION_DENIED": "This area is private",
    "LOCKED": "Complete the previous step first",
    "PARTIAL": "Some information is unavailable",
    "SUCCESS_FEEDBACK": "Your next step is clear",
}

ROUTE_SPECS: Final[tuple[RouteSpec, ...]] = (
    RouteSpec("FLOW-AUTH-ONB-01", "AUTH-01", "/login", "auth"),
    RouteSpec("FLOW-AUTH-ONB-01", "AUTH-02", "/register", "auth", False),
    RouteSpec("FLOW-AUTH-ONB-01", "AUTH-03", "/verify-email", "auth", False),
    RouteSpec("FLOW-AUTH-ONB-01", "AUTH-04", "/forgot-password", "auth", False),
    RouteSpec("FLOW-AUTH-ONB-01", "AUTH-05", "/reset-password", "auth", False),
    RouteSpec(
        "FLOW-AUTH-ONB-01",
        "AUTH-06",
        "/auth/callback?result=registration_required",
        "auth",
    ),
    RouteSpec("FLOW-AUTH-ONB-01", "AUTH-07", "/session-expired", "auth", False),
    RouteSpec("FLOW-AUTH-ONB-01", "ONB-01", "/onboarding", "auth"),
    RouteSpec("FLOW-SHELL-PLAN-01", "HOME-01", "/home", "learner"),
    RouteSpec("FLOW-LEARNING-01", "LEARN-01", "/learning", "learner"),
    RouteSpec("FLOW-DISCOVER-01", "DISC-01", "/discover", "learner"),
    RouteSpec(
        "FLOW-DISCOVER-01",
        "COURSE-01",
        f"/programs/{CANONICAL_FREE_COURSE_SLUG}",
        "public",
    ),
    RouteSpec(
        "FLOW-LEARNING-01",
        "COURSE-02",
        f"/learn/{CANONICAL_FREE_COURSE_SLUG}",
        "learner",
    ),
    RouteSpec(
        "FLOW-LEARNING-01",
        "MOD-01",
        f"/learn/{CANONICAL_FREE_COURSE_SLUG}/module/module-1",
        "learner",
    ),
    *tuple(
        RouteSpec(
            "FLOW-ACTIVITY-01",
            fixture.screen_id,
            f"/activity/{fixture.activity_id}",
            "learner",
            state_simulation=False,
            activity_kind=fixture.kind,
        )
        for fixture in ACTIVITY_FIXTURES
    ),
    RouteSpec("FLOW-PROGRESS-01", "PROG-01", "/progress", "learner"),
    RouteSpec("FLOW-NOTIFY-01", "NOTIF-01", "/notifications", "learner"),
    RouteSpec("FLOW-PROFILE-01", "PROF-01", "/profile", "learner"),
    RouteSpec("FLOW-SETTINGS-01", "SET-01..05", "/settings", "learner"),
    RouteSpec("FLOW-CERT-01", "CERT-01", "/certificates/certificate-1", "learner"),
    RouteSpec("FLOW-RESILIENCE-01", "SYS-03", "/offline", "public", False),
)

SCREENSHOT_CASES: Final[tuple[tuple[str, str, str], ...]] = (
    ("AUTH-01", "/login", "default"),
    ("HOME-01", "/home?state=loading", "loading"),
    ("DISC-01", "/discover?state=empty", "empty"),
    ("SYS-03", "/offline", "offline"),
)


@pytest.fixture(scope="session")
def learner_base_url() -> str:
    value = os.getenv("AC_LEARNER_E2E_BASE_URL")
    if not value:
        pytest.skip("set AC_LEARNER_E2E_BASE_URL to run learner browser QA")
    return value.rstrip("/")


@pytest.fixture(scope="session")
def browser(learner_base_url: str) -> Iterator[Browser]:
    # Resolve the configured target before Playwright starts. This lets an
    # ordinary repository-wide pytest run skip the browser suite cleanly on
    # hosts where no learner server was requested (notably Windows).
    assert learner_base_url
    with sync_playwright() as playwright:
        instance = playwright.chromium.launch(headless=True)
        yield instance
        instance.close()


def _new_context(
    browser: Browser,
    viewport: Viewport,
    *,
    reduced_motion: str = "no-preference",
) -> BrowserContext:
    return browser.new_context(
        viewport={"width": viewport.width, "height": viewport.height},
        reduced_motion=reduced_motion,
        color_scheme="light",
        service_workers="block",
    )


def _activity_explanation(fixture: ActivityFixture) -> dict[str, object]:
    return {
        "activity_id": fixture.activity_id,
        "state": "available",
        "required": True,
        "reason": "Ready in the deterministic browser fixture; no completion is asserted.",
        "missing_activity_ids": [],
        "missing_module_ids": [],
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
        # AVAILABLE is the server-shaped ready-to-work state. No fixture
        # activity is COMPLETED, so browser QA cannot imply progress.
        "state": "available",
        "revision": 1,
        "required": True,
        "explanation": _activity_explanation(fixture),
        "allowed_actions": list(fixture.allowed_actions),
        "draft_revision": 0,
        "draft_payload": None,
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
            # Keep every kind independently openable for renderer coverage;
            # the projection remains explicitly at zero completions.
            "state": "available",
            "revision": 1,
            "required": True,
            "explanation": _activity_explanation(fixture),
            "allowed_actions": list(fixture.allowed_actions),
        }
        for fixture in ACTIVITY_FIXTURES
    ]
    activity_reasons = [_activity_explanation(fixture) for fixture in ACTIVITY_FIXTURES]
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
            "projection_version": "e2e-activity-ready-v1",
            "denominator": len(ACTIVITY_FIXTURES),
            "completed_count": 0,
            "percentage": 0,
            "predicate": "fixture-read-only-no-completions",
            "missing_module_ids": [],
            "activity_reasons": activity_reasons,
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


def _fulfill_json(route: Route, payload: object, *, status: int = 200) -> None:
    route.fulfill(
        status=status,
        content_type="application/json",
        body=json.dumps(payload),
    )


def _install_activity_fixture(context: BrowserContext) -> tuple[list[str], list[str]]:
    """Serve deterministic activity reads and record any attempted writes.

    The fixture is scoped to the browser context and handles only the learner
    read endpoints needed by the activity route. Unknown requests continue to
    the configured server, preserving the distinction between a local test
    fixture and canonical API state.
    """

    served_activity_ids: list[str] = []
    mutation_paths: list[str] = []

    def handle_api(route: Route) -> None:
        request = route.request
        parsed = urlparse(request.url)
        path = parsed.path

        if path == "/v1/me" and request.method == "GET":
            _fulfill_json(route, _fixture_me_response())
            return

        if path.startswith("/v1/activities/") and request.method == "GET":
            activity_id = unquote(path.removeprefix("/v1/activities/"))
            fixture = ACTIVITY_FIXTURE_BY_ID.get(activity_id)
            if fixture is not None:
                served_activity_ids.append(activity_id)
                _fulfill_json(route, _activity_response(fixture))
                return

        if path == f"/v1/learning/{CANONICAL_PROGRAM_ID}" and request.method == "GET":
            _fulfill_json(route, _learning_response())
            return

        if path.startswith("/v1/") and request.method != "GET":
            mutation_paths.append(f"{request.method} {path}")
            _fulfill_json(
                route,
                {
                    "title": "Deterministic browser fixture blocks writes",
                    "detail": "Activity QA only serves read data.",
                },
                status=405,
            )
            return
        route.continue_()

    context.route("**/v1/**", handle_api)
    return served_activity_ids, mutation_paths


def _load(page: Page, base_url: str, path: str) -> None:
    response = page.goto(
        f"{base_url}{path}",
        wait_until="domcontentloaded",
        timeout=30_000,
    )
    assert response is not None, f"no response for {path}"
    assert response.status < 400, f"{path} returned HTTP {response.status}"
    with suppress(PlaywrightTimeoutError):
        page.wait_for_load_state("networkidle", timeout=3_000)


def _attach_diagnostics(page: Page) -> list[str]:
    issues: list[str] = []

    def on_console(message: object) -> None:
        message_text = str(getattr(message, "text", message))
        if getattr(message, "type", "") == "error" and "/_next/webpack-hmr" not in message_text:
            issues.append(f"console.error: {message_text}")

    def on_page_error(error: Exception) -> None:
        issues.append(f"pageerror: {error}")

    page.on("console", on_console)
    page.on("pageerror", on_page_error)
    return issues


def _assert_no_browser_errors(issues: list[str], context: str) -> None:
    assert not issues, f"{context} emitted browser errors: {issues}"


def _visible(locator: object) -> bool:
    return bool(locator.is_visible())


def _accessible_name(locator: object) -> str:
    return str(
        locator.evaluate(
            """
            element => {
              const labelledBy = element.getAttribute('aria-labelledby');
              const labelledText = labelledBy
                ? labelledBy.split(/\\s+/)
                    .map(id => document.getElementById(id)?.innerText ?? '')
                    .join(' ')
                : '';
              const inputLabel = element.id
                ? document.querySelector(`label[for="${CSS.escape(element.id)}"]`)?.innerText ?? ''
                : '';
              const wrappingLabel = [...(element.labels ?? [])]
                .map(label => label.innerText ?? '')
                .join(' ');
              return (
                element.getAttribute('aria-label') || labelledText ||
                inputLabel || wrappingLabel || element.getAttribute('title') ||
                element.innerText || element.getAttribute('placeholder') || ''
              ).replace(/\\s+/g, ' ').trim();
            }
            """
        )
    )


def _assert_accessible_interactives(page: Page) -> None:
    interactives = page.locator(
        'a[href], button, input:not([type="hidden"]), textarea, select, [role="button"]'
    )
    unnamed: list[str] = []
    for index in range(interactives.count()):
        element = interactives.nth(index)
        if not _visible(element):
            continue
        if element.get_attribute("aria-hidden") == "true":
            continue
        if not _accessible_name(element):
            unnamed.append(element.evaluate("element => element.outerHTML.slice(0, 180)"))
    assert not unnamed, f"visible interactive controls without names: {unnamed}"


def _assert_touch_targets(page: Page) -> None:
    """Check the comfortable target contract without penalising text links."""

    controls = page.locator(
        ".button, button:not([data-nextjs-dev-tools-button]), "
        ".learner-nav__link, .mobile-drawer-link, "
        ".mobile-header-icon-button, .header-icon-button, "
        ".learner-profile-button, .theme-control__option"
    )
    undersized: list[str] = []
    for index in range(controls.count()):
        element = controls.nth(index)
        if not _visible(element):
            continue
        box = element.bounding_box()
        if not box:
            continue
        if box["width"] < 40 or box["height"] < 40:
            undersized.append(
                f"{_accessible_name(element)!r}={box['width']:.1f}x{box['height']:.1f}"
            )
    assert not undersized, f"comfortable targets below 40 CSS px: {undersized}"


def _geometry(page: Page) -> dict[str, object]:
    return page.evaluate(
        """
        () => {
          const viewportWidth = document.documentElement.clientWidth;
          const offenders = [];
          for (const element of document.querySelectorAll('body *')) {
            const style = getComputedStyle(element);
            if (style.display === 'none' || style.visibility === 'hidden') continue;
            const rect = element.getBoundingClientRect();
            if (rect.width === 0 && rect.height === 0) continue;
            if (rect.left < -1 || rect.right > viewportWidth + 1) {
              offenders.push({
                tag: element.tagName.toLowerCase(),
                className: typeof element.className === 'string' ? element.className : '',
                left: Math.round(rect.left * 10) / 10,
                right: Math.round(rect.right * 10) / 10,
              });
            }
          }
          const main = document.querySelector('main');
          const bottomNav = document.querySelector('.learner-bottom-nav');
          const mainStyle = main ? getComputedStyle(main) : null;
          const bottomNavStyle = bottomNav ? getComputedStyle(bottomNav) : null;
          return {
            viewportWidth,
            documentWidth: Math.max(
              document.documentElement.scrollWidth,
              document.body.scrollWidth,
            ),
            offenders: offenders.slice(0, 12),
            mainPaddingBottom: mainStyle ? parseFloat(mainStyle.paddingBottom) : 0,
            bottomNavHeight: bottomNav ? bottomNav.getBoundingClientRect().height : 0,
            bottomNavPosition: bottomNavStyle?.position ?? '',
            bottomNavVisible: bottomNav ? bottomNavStyle?.display !== 'none' : false,
          };
        }
        """
    )


def _assert_geometry(page: Page, viewport: Viewport) -> None:
    geometry = _geometry(page)
    assert geometry["documentWidth"] <= geometry["viewportWidth"] + 1, (
        f"{viewport.name}px document overflow: {geometry}"
    )
    assert not geometry["offenders"], f"{viewport.name}px off-canvas elements: {geometry}"
    if viewport.width <= 900 and page.locator(".site-frame--learner").count():
        assert geometry["bottomNavVisible"], f"mobile nav hidden at {viewport.name}px"
        assert geometry["bottomNavPosition"] == "fixed"
        assert geometry["mainPaddingBottom"] >= geometry["bottomNavHeight"] - 1, (
            f"main content may be hidden by mobile nav at {viewport.name}px: {geometry}"
        )
    if viewport.width >= 1024 and page.locator(".site-frame--learner").count():
        assert not geometry["bottomNavVisible"], f"mobile nav shown at {viewport.name}px"


def _assert_route_contract(page: Page, spec: RouteSpec, viewport: Viewport) -> None:
    assert page.locator("html").get_attribute("lang") == "en"
    assert page.locator("main#main-content").count() == 1
    assert page.locator("h1").count() == 1, (
        f"{spec.screen_id} at {viewport.name}px must expose one page heading"
    )
    assert page.locator(".skip-link").count() >= 1
    assert page.locator(".skip-link").first.get_attribute("href") == "#main-content"
    _assert_accessible_interactives(page)
    _assert_touch_targets(page)
    _assert_geometry(page, viewport)


def _state_path(path: str, state: str) -> str:
    separator = "&" if "?" in path else "?"
    return f"{path}{separator}state={state.lower()}"


def _activity_fixture_for_spec(spec: RouteSpec) -> ActivityFixture:
    assert spec.activity_kind is not None, f"{spec.screen_id} is not an activity route"
    fixture = next(
        (item for item in ACTIVITY_FIXTURES if item.kind == spec.activity_kind),
        None,
    )
    assert fixture is not None, f"no deterministic fixture for {spec.activity_kind}"
    return fixture


def _assert_activity_ready(
    page: Page,
    spec: RouteSpec,
    fixture: ActivityFixture,
) -> None:
    assert spec.activity_kind == fixture.kind
    workspace = page.locator(".activity-workspace")
    workspace.wait_for(state="visible")
    workspace_class = workspace.get_attribute("class") or ""
    expected_class = f"activity-workspace--{fixture.kind.lower().replace('_', '-')}"
    assert expected_class in workspace_class
    assert page.locator(".activity-shell__header h1").inner_text() == fixture.title
    kind_text = page.locator(".activity-shell__type").inner_text().upper()
    assert ACTIVITY_KIND_LABELS[fixture.kind].upper() in kind_text
    assert page.locator(".activity-shell__header .status-pill").inner_text() == "Available"
    assert fixture.prompt in page.locator(".activity-prompt").inner_text()

    if fixture.kind == "VIDEO":
        media_stage = page.get_by_role(
            "status",
            name="Approved lesson media is unavailable",
        )
        assert media_stage.is_visible()
        body_text = page.locator("body").inner_text()
        assert "Lesson complete." not in body_text
        assert "Completion is recorded by the server" not in body_text
        return

    response = page.locator("#activity-response")
    assert response.is_visible()
    assert not response.is_disabled()
    assert page.get_by_role("button", name="Submit evidence").is_enabled()
    save_label = "Save reflection" if fixture.kind == "REFLECTION" else "Save draft"
    assert page.get_by_role("button", name=save_label).is_enabled()


@pytest.mark.e2e
def test_route_specs_use_canonical_slug_and_distinct_activity_ids() -> None:
    learning_specs = {
        "COURSE-01": next(spec for spec in ROUTE_SPECS if spec.screen_id == "COURSE-01"),
        "COURSE-02": next(spec for spec in ROUTE_SPECS if spec.screen_id == "COURSE-02"),
        "MOD-01": next(spec for spec in ROUTE_SPECS if spec.screen_id == "MOD-01"),
    }
    assert all(CANONICAL_FREE_COURSE_SLUG in spec.path for spec in learning_specs.values())
    assert all("free-course-foundation" not in spec.path for spec in ROUTE_SPECS)

    activity_specs = [spec for spec in ROUTE_SPECS if spec.flow_id == "FLOW-ACTIVITY-01"]
    assert len(activity_specs) == len(ACTIVITY_FIXTURES) == 5
    assert {spec.screen_id for spec in activity_specs} == {
        fixture.screen_id for fixture in ACTIVITY_FIXTURES
    }
    assert {spec.activity_kind for spec in activity_specs} == {
        fixture.kind for fixture in ACTIVITY_FIXTURES
    }
    assert len({spec.path for spec in activity_specs}) == len(activity_specs)
    assert all(spec.path != "/activity/activity-1" for spec in activity_specs)

    learning_fixture = _learning_response()
    projection = learning_fixture["projection"]
    assert isinstance(projection, dict)
    assert projection["denominator"] == 5
    assert projection["completed_count"] == 0
    assert projection["percentage"] == 0


@pytest.mark.e2e
def test_learner_routes_reflow_at_reference_viewports(
    browser: Browser,
    learner_base_url: str,
) -> None:
    """Exercise every implementation-facing learner route at all six widths."""

    for viewport in REFERENCE_VIEWPORTS:
        context = _new_context(browser, viewport)
        served_activity_ids, mutation_paths = _install_activity_fixture(context)
        page = context.new_page()
        issues = _attach_diagnostics(page)
        try:
            for spec in ROUTE_SPECS:
                route = _state_path(spec.path, "LOADING") if spec.state_simulation else spec.path
                issue_start = len(issues)
                _load(page, learner_base_url, route)
                _assert_route_contract(page, spec, viewport)
                if spec.activity_kind is not None:
                    _assert_activity_ready(
                        page,
                        spec,
                        _activity_fixture_for_spec(spec),
                    )
                _assert_no_browser_errors(issues[issue_start:], f"{spec.screen_id} {route}")
            assert set(served_activity_ids) == {
                fixture.activity_id for fixture in ACTIVITY_FIXTURES
            }
            assert mutation_paths == []
        finally:
            context.close()


@pytest.mark.e2e
def test_named_surface_states_are_distinct(
    browser: Browser,
    learner_base_url: str,
) -> None:
    """Verify the shared state panel stays semantic and action-oriented."""

    viewport = Viewport("390", 390, 844)
    context = _new_context(browser, viewport)
    page = context.new_page()
    issues = _attach_diagnostics(page)
    try:
        for state in SURFACE_STATES:
            issue_start = len(issues)
            _load(page, learner_base_url, _state_path("/home", state))
            _assert_route_contract(page, ROUTE_SPECS[8], viewport)
            if state == "LOADING":
                skeleton = page.locator('[aria-label="Loading dashboard"]')
                assert skeleton.count() == 1
                assert skeleton.get_attribute("aria-busy") == "true"
                assert page.locator('[data-state="LOADING"]').count() == 0
            else:
                panel = page.locator(f'[data-state="{state}"]')
                assert panel.count() == 1
                expected_role = "alert" if state.startswith("ERROR_") else "status"
                assert panel.get_attribute("role") == expected_role
                assert STATE_TITLES[state] in panel.inner_text()
                if state == "PERMISSION_DENIED":
                    assert "Go to sign in" in panel.inner_text()
                if state == "LOCKED":
                    assert "View the course path" in panel.inner_text()
            _assert_no_browser_errors(issues[issue_start:], f"HOME-01 state={state}")
    finally:
        context.close()


@pytest.mark.e2e
def test_keyboard_focus_and_mobile_more_drawer_recovery(
    browser: Browser,
    learner_base_url: str,
) -> None:
    viewport = Viewport("390", 390, 844)
    context = _new_context(browser, viewport)
    page = context.new_page()
    issues = _attach_diagnostics(page)
    try:
        _load(page, learner_base_url, "/home?state=empty")
        page.keyboard.press("Tab")
        assert page.locator(":focus").evaluate("element => element.classList.contains('skip-link')")
        focus_box = page.locator(":focus").bounding_box()
        assert focus_box and focus_box["width"] > 0 and focus_box["height"] > 0

        more = page.get_by_role("button", name="More navigation options")
        more.click()
        drawer = page.get_by_role("dialog")
        drawer.wait_for(state="visible")
        assert page.locator(":focus").evaluate(
            "element => Boolean(element.closest('[role=dialog]'))"
        )

        focusables = drawer.locator("a[href], button:not([disabled])")
        assert focusables.count() >= 2
        first_label = _accessible_name(focusables.first)
        last_label = _accessible_name(focusables.last)
        focusables.first.focus()
        page.keyboard.press("Shift+Tab")
        assert _accessible_name(page.locator(":focus")) == last_label
        assert first_label != last_label

        page.keyboard.press("Escape")
        assert not drawer.is_visible()
        assert _accessible_name(page.locator(":focus")) == "More navigation options"
        _assert_no_browser_errors(issues, "mobile learner shell focus")
    finally:
        context.close()


@pytest.mark.e2e
def test_reduced_motion_and_safe_area_contracts(
    browser: Browser,
    learner_base_url: str,
) -> None:
    viewport = Viewport("390", 390, 844)
    context = _new_context(browser, viewport, reduced_motion="reduce")
    page = context.new_page()
    issues = _attach_diagnostics(page)
    try:
        _load(page, learner_base_url, "/home?state=loading")
        contract = page.evaluate(
            """
            () => {
              let cssText = '';
              for (const sheet of document.styleSheets) {
                try {
                  cssText += Array.from(sheet.cssRules, rule => rule.cssText).join('\\n');
                } catch (_) {
                  // Cross-origin stylesheets are outside this same-origin app.
                }
              }
              const skeleton = document.querySelector('.skeleton-shimmer');
              const main = document.querySelector('main');
              const nav = document.querySelector('.learner-bottom-nav');
              return {
                reducedMotion: window.matchMedia('(prefers-reduced-motion: reduce)').matches,
                scrollBehavior: getComputedStyle(document.documentElement).scrollBehavior,
                animationName: skeleton ? getComputedStyle(skeleton).animationName : '',
                viewportMeta: document
                  .querySelector('meta[name="viewport"]')
                  ?.getAttribute('content') ?? '',
                hasSafeTop: cssText.includes('safe-area-inset-top'),
                hasSafeBottom: cssText.includes('safe-area-inset-bottom'),
                mainPaddingBottom: main ? parseFloat(getComputedStyle(main).paddingBottom) : 0,
                bottomNavHeight: nav ? nav.getBoundingClientRect().height : 0,
              };
            }
            """
        )
        assert contract["reducedMotion"] is True
        assert contract["scrollBehavior"] == "auto"
        assert contract["animationName"] in ("none", "")
        assert "viewport-fit=cover" in contract["viewportMeta"]
        assert contract["hasSafeTop"] and contract["hasSafeBottom"]
        assert contract["mainPaddingBottom"] >= contract["bottomNavHeight"] - 1
        _assert_no_browser_errors(issues, "reduced-motion/safe-area contract")
    finally:
        context.close()


@pytest.mark.e2e
def test_registration_consent_keeps_google_action_explicit(
    browser: Browser,
    learner_base_url: str,
) -> None:
    viewport = Viewport("390", 390, 844)
    context = _new_context(browser, viewport)
    page = context.new_page()
    issues = _attach_diagnostics(page)
    try:
        _load(page, learner_base_url, "/register")
        consent = page.get_by_role("checkbox", name="I confirm")
        google = page.get_by_role("button", name="Continue with Google")
        assert consent.is_visible()
        assert google.is_disabled()
        consent.check()
        page.wait_for_timeout(50)
        assert not google.is_disabled()
        _assert_route_contract(
            page,
            RouteSpec("FLOW-AUTH-ONB-01", "AUTH-02", "/register", "auth", False),
            viewport,
        )
        _assert_no_browser_errors(issues, "AUTH-02 registration")
    finally:
        context.close()


@pytest.mark.e2e
def test_optional_reference_screenshots(
    browser: Browser,
    learner_base_url: str,
) -> None:
    """Capture deterministic, ignored evidence when explicitly requested.

    Repository policy ignores ``.artifacts`` and does not treat screenshots as
    release approval. Set ``AC_LEARNER_QA_SCREENSHOT_DIR`` to opt in; files
    are named with stable screen/state/viewport IDs for later same-viewport
    comparison against an approved visual direction.
    """

    screenshot_dir = os.getenv("AC_LEARNER_QA_SCREENSHOT_DIR")
    if not screenshot_dir:
        pytest.skip("set AC_LEARNER_QA_SCREENSHOT_DIR to capture screenshot evidence")

    output_dir = Path(screenshot_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    for screen_id, path, state in SCREENSHOT_CASES:
        for viewport in REFERENCE_VIEWPORTS:
            context = _new_context(browser, viewport)
            page = context.new_page()
            issues = _attach_diagnostics(page)
            try:
                _load(page, learner_base_url, path)
                page.screenshot(
                    path=str(output_dir / f"{screen_id}-{state}-{viewport.name}.png"),
                    full_page=True,
                    animations="disabled",
                )
                _assert_no_browser_errors(issues, f"screenshot {screen_id} {viewport.name}")
            finally:
                context.close()
