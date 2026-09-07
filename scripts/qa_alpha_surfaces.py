"""Isolated Chrome QA for alpha Discover/Learning surfaces using synthetic reads.

This creates local fixture evidence, never live-state or performance proof.
No existing browser profile, cookies, storage state, or server process is used.
All API reads are fulfilled locally; unknown API reads and all writes are blocked.
"""

from __future__ import annotations

import argparse
import json
import re
from datetime import UTC, datetime
from pathlib import Path
from urllib.parse import urlparse

from playwright.sync_api import Locator, Page, Route, expect, sync_playwright

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_OUTPUT = ROOT / "docs/evidence/screenshots/alpha-foundation-2026-09-07"
FIXTURE_LABEL = "Synthetic API fixtures against local development UI; not live or performance proof"
PROGRAM = {
    "id": "alpha-fixture-program",
    "slug": "authority-closers-free-course",
    "title": "Authority Closers Free Course",
    "program_version_id": "alpha-fixture-version",
    "version_number": 1,
    "published_at": "2026-09-01T00:00:00Z",
}
PROJECTION = {
    "scope_type": "program_version",
    "scope_id": PROGRAM["program_version_id"],
    "program_version": "1.0.0",
    "projection_version": "alpha-fixture-v1",
    "denominator": 5,
    "completed_count": 1,
    "percentage": 0.2,
    "predicate": "required activities completed",
    "missing_module_ids": [],
    "activity_reasons": [],
}
COURSE = {
    "program_id": PROGRAM["id"],
    "program_version_id": PROGRAM["program_version_id"],
    "program_slug": PROGRAM["slug"],
    "program_title": PROGRAM["title"],
    "version_number": 1,
    "enrollment_id": "alpha-fixture-enrollment",
    "enrolled_at": "2026-09-01T00:00:00Z",
    "updated_at": "2026-09-07T00:00:00Z",
    "state": "in_progress",
    "saved_state": "unavailable",
    "projection": PROJECTION,
}
ROUTES = (("/discover", "Discover Programs"), ("/learning", "My Learning"))


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--base-url", required=True, help="Existing local learner origin, including port"
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=DEFAULT_OUTPUT,
        help="Parent directory for a new timestamped evidence run",
    )
    parser.add_argument("--timeout-ms", type=int, default=60_000)
    parser.add_argument(
        "--probe",
        action="store_true",
        help="Capture one route and bounded visible-control metadata only",
    )
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
            "--base-url must be a loopback/local .localhost origin without credentials or a path"
        )
    if args.timeout_ms < 1:
        parser.error("--timeout-ms must be positive")
    args.base_url = args.base_url.rstrip("/")
    return args


def fixture(path: str) -> dict | None:
    if path == "/v1/me":
        return {
            "person_id": "alpha-fixture-person",
            "email": "alpha.fixture@example.invalid",
            "display_name": "Learner QA",
            "email_verified_at": "2026-09-01T00:00:00Z",
            "selected_tenant_id": "alpha-fixture-tenant",
            "membership_role": "learner",
            "permissions": ["learner:read"],
        }
    if path == "/v1/profile/avatar":
        return {"avatar": None}
    if path == "/v1/programs":
        return {"items": [PROGRAM], "next_cursor": None}
    if path == "/v1/learning":
        return {"items": [COURSE], "next_cursor": None, "saved_filter_available": False}
    if path == f"/v1/learning/{PROGRAM['id']}":
        return {**COURSE, "modules": []}
    return None


def route_handler(route: Route, network: dict, origin: str) -> None:
    request = route.request
    parsed = urlparse(request.url)
    path = parsed.path
    if request.method not in {"GET", "HEAD", "OPTIONS"}:
        network["blocked_writes"].append(f"{request.method} {path}")
        route.abort("blockedbyclient")
        return
    if "/v1/" in path:
        api_path = path[path.index("/v1/") :]
        body = fixture(api_path)
        if body is None:
            network["unknown_api_reads"].append(api_path)
            route.fulfill(status=404, json={"title": "No synthetic fixture for this read"})
        else:
            network["fixture_reads"].append(api_path)
            route.fulfill(status=200, json=body)
        return
    if f"{parsed.scheme}://{parsed.netloc}" != origin:
        network["blocked_external"].append(f"{parsed.scheme}://{parsed.netloc}{path}")
        route.abort("blockedbyclient")
        return
    route.continue_()


def layout_metrics(page: Page) -> dict:
    return page.evaluate("""() => {
      const root = document.documentElement;
      const box = element => {
        if (!element) return null;
        const r = element.getBoundingClientRect();
        const style = getComputedStyle(element);
        return {x:r.x,y:r.y,width:r.width,height:r.height,
          visible: style.display !== "none" && style.visibility !== "hidden"
            && r.width > 0 && r.height > 0};
      };
      const colors = element => element ? {
        color:getComputedStyle(element).color,
        background:getComputedStyle(element).backgroundColor
      } : null;
      return {
        viewport: {width:innerWidth,height:innerHeight},
        scrollWidth:root.scrollWidth, clientWidth:root.clientWidth,
        horizontalOverflow:root.scrollWidth-root.clientWidth,
        theme:root.dataset.theme,
        sidebar:box(document.querySelector(".learner-sidebar")),
        mobileIdentity:box(document.querySelector(".mobile-brand-link")),
        mobileMark:box(document.querySelector(".mobile-brand-link svg")),
        headerActions:box(document.querySelector(".learner-header__actions")),
        headerActionTargets:[...document.querySelectorAll(
          ".learner-header__actions > a,.learner-header__actions > div > button")]
          .filter(e=>box(e).visible).map(e=>({label:e.getAttribute("aria-label"),box:box(e)})),
        profileNameColors:colors(document.querySelector(".learner-profile__name")),
        headerColors:colors(document.querySelector(".learner-header")),
        bodyColors:colors(document.body),
        mobileIdentityText:[...document.querySelectorAll(".mobile-brand-link span")]
          .map(e=>({text:e.textContent,box:box(e),clientWidth:e.clientWidth,
            scrollWidth:e.scrollWidth})),
        visibleImages:[...document.images].filter(e=>box(e).visible).map(e=>({
          path:new URL(e.currentSrc || e.src,location.href).pathname,box:box(e),
          naturalWidth:e.naturalWidth,naturalHeight:e.naturalHeight})),
        mobileNavigation:box(document.querySelector(".learner-bottom-nav")),
        main:box(document.querySelector("main")),
        heading:box(document.querySelector("main h1")),
        overflowingElements:[...document.querySelectorAll("main *")]
          .filter(e => {const r=e.getBoundingClientRect();
            return r.width > 0 && (r.right > innerWidth+1 || r.left < -1)})
          .slice(0,8).map(e => ({tag:e.tagName,className:String(e.className),
            width:e.getBoundingClientRect().width}))
      };
    }""")


def check_layout(page: Page, route: str, theme: str) -> dict:
    metrics = layout_metrics(page)
    assert metrics["horizontalOverflow"] <= 1, (
        f"{route}: {metrics['horizontalOverflow']}px horizontal overflow"
    )
    assert metrics["theme"] == theme, f"Theme is {metrics['theme']}, expected {theme}"
    breadcrumb = page.get_by_role("navigation", name="Breadcrumb", exact=True)
    expect(breadcrumb).to_have_count(1)
    expect(breadcrumb.locator("[aria-current='page']")).to_be_visible()
    expect(breadcrumb.get_by_role("link", name="Dashboard", exact=True)).to_be_visible()
    mobile_nav = page.get_by_role("navigation", name="Learner mobile navigation", exact=True)
    if mobile_nav.is_visible():
        identity = page.locator(".mobile-brand-link")
        expect(identity).to_be_visible()
        expect(identity).to_have_accessible_name("Closers Academy — by Authority Closers")
        expect(identity.locator("svg")).to_have_count(1)
        expect(identity.locator(".mobile-brand-name")).to_have_text("Closers Academy")
        expect(identity.locator(".mobile-brand-tenant")).to_have_text("by Authority Closers")
        identity_box = identity.bounding_box()
        assert identity_box and identity_box["x"] >= 0
        assert identity_box["x"] + identity_box["width"] <= metrics["viewport"]["width"] + 1
        assert identity_box["x"] + identity_box["width"] <= metrics["headerActions"]["x"] + 1, (
            "Mobile identity overlaps header actions"
        )
        for target in metrics["headerActionTargets"]:
            assert target["box"]["width"] >= 44 and target["box"]["height"] >= 44, (
                f"Mobile header target smaller than44px: {target}"
            )
        for line in metrics["mobileIdentityText"]:
            assert line["scrollWidth"] <= line["clientWidth"] + 1, (
                f"Mobile identity text is clipped: {line['text']}"
            )
    return metrics


def capture(page: Page, run_dir: Path, name: str, *, full_page: bool = False) -> str:
    path = run_dir / f"{name}.png"
    page.screenshot(path=str(path), full_page=full_page, animations="disabled")
    return str(path.relative_to(ROOT)) if path.is_relative_to(ROOT) else str(path)


def focus_visible(page: Page) -> dict:
    state = page.evaluate("""() => {
      const e=document.activeElement, s=getComputedStyle(e), r=e.getBoundingClientRect();
      return {tag:e.tagName,label:e.getAttribute("aria-label"),outlineStyle:s.outlineStyle,
        outlineWidth:s.outlineWidth,boxShadow:s.boxShadow,focusVisible:e.matches(":focus-visible"),
        visible:r.width>0&&r.height>0&&r.right<=innerWidth+1&&r.left>=-1};
    }""")
    assert state["visible"], f"Focused control is not visible: {state}"
    assert state["focusVisible"], f"Keyboard focus-visible is absent: {state}"
    assert (
        state["outlineStyle"] != "none" and float(state["outlineWidth"].removesuffix("px")) > 0
    ) or state["boxShadow"] != "none", f"No visible keyboard focus treatment: {state}"
    return state


def text_contrast(locator: Locator) -> dict:
    """Measure solid-color text; record opacity and avoid claiming gradient coverage."""
    expect(locator).to_be_visible()
    return locator.evaluate("""element => {
      const rgba = value => {
        const channels=value.match(/[\\d.]+/g).map(Number);
        return [...channels.slice(0,3), channels[3] ?? 1];
      };
      const over=(fg,bg,alpha=fg[3])=>fg.slice(0,3).map((n,i)=>n*alpha+bg[i]*(1-alpha));
      const ancestors=[];
      for(let e=element;e;e=e.parentElement) ancestors.push(e);
      const layers=ancestors.map(e=>({tag:e.tagName,
        background:getComputedStyle(e).backgroundColor,
        backgroundImage:getComputedStyle(e).backgroundImage,
        opacity:Number(getComputedStyle(e).opacity)}));
      let background=[255,255,255];
      for(const layer of [...layers].reverse()) background=over(rgba(layer.background),background);
      const style=getComputedStyle(element),foreground=rgba(style.color);
      const opacityProduct=layers.reduce((product,layer)=>product*layer.opacity,1);
      const effectiveForeground=over(foreground,background,foreground[3]*opacityProduct);
      const luminance=rgb=>rgb.map(n=>{const x=n/255;
        return x<=0.04045?x/12.92:((x+0.055)/1.055)**2.4})
        .reduce((sum,n,i)=>sum+n*[0.2126,0.7152,0.0722][i],0);
      const a=luminance(effectiveForeground),b=luminance(background);
      return {color:style.color,fontSize:style.fontSize,opacityProduct,layers,
        background,effectiveForeground,contrast:(Math.max(a,b)+0.05)/(Math.min(a,b)+0.05),
        solidColorMeasurement:layers.every(l=>l.backgroundImage==='none'
          &&(l.opacity===1||rgba(l.background)[3]===0))};
    }""")


def search_check(page: Page, run_dir: Path, prefix: str) -> dict:
    trigger = page.locator("[aria-label^='Search courses, lessons, and more']:visible").first
    expect(trigger).to_be_visible()
    trigger.focus()
    trigger.press("Enter")
    dialog = page.get_by_role(
        "dialog", name="Search and navigate the learner workspace", exact=True
    )
    expect(dialog).to_be_visible()
    field = dialog.get_by_role("combobox", name="Navigation search", exact=True)
    expect(field).to_be_focused()
    field.fill("settings")
    expect(dialog.get_by_text("Settings & Appearance", exact=True)).to_be_visible()
    screenshot = capture(page, run_dir, f"{prefix}-search")
    for _ in range(8):
        page.keyboard.press("Tab")
        assert dialog.evaluate("(e) => e.contains(document.activeElement)"), (
            "Search focus escaped its dialog"
        )
    page.keyboard.press("Escape")
    expect(dialog).not_to_be_visible()
    expect(trigger).to_be_focused()
    focus = focus_visible(page)
    return {"screenshot": screenshot, "focus_restored": True, "focus": focus}


def more_check(page: Page, run_dir: Path, prefix: str) -> dict:
    trigger = page.get_by_role("button", name="More navigation options", exact=True)
    trigger.focus()
    trigger.press("Enter")
    dialog = page.get_by_role("dialog", name="Learner QA", exact=True)
    expect(dialog).to_be_visible()
    expect(dialog.get_by_role("navigation", name="Account and support navigation")).to_be_visible()
    expect(dialog.get_by_role("link", name="Profile & Identity", exact=True)).to_be_visible()
    profile_contrast = text_contrast(
        dialog.get_by_role("link", name="Profile & Identity", exact=True)
    )
    signout_contrast = text_contrast(dialog.get_by_role("button", name="Sign out", exact=True))
    assert (
        profile_contrast["solidColorMeasurement"] and signout_contrast["solidColorMeasurement"]
    ), "More text contrast requires unsupported background/opacity compositing"
    assert profile_contrast["contrast"] >= 4.5, "More navigation text has insufficient contrast"
    assert signout_contrast["contrast"] >= 4.5, "More sign-out text has insufficient contrast"
    assert signout_contrast["color"] != profile_contrast["color"], (
        "More sign-out lost its distinct semantic danger color"
    )
    screenshot = capture(page, run_dir, f"{prefix}-more")
    for _ in range(12):
        page.keyboard.press("Tab")
        assert dialog.evaluate("(e) => e.contains(document.activeElement)"), (
            "More focus escaped its dialog"
        )
    page.keyboard.press("Escape")
    expect(dialog).not_to_be_visible()
    expect(trigger).to_be_focused()
    assert page.locator("[inert]").count() == 0, "More left background controls inert"
    return {
        "screenshot": screenshot,
        "focus_restored": True,
        "focus": focus_visible(page),
        "profile_contrast": profile_contrast,
        "signout_contrast": signout_contrast,
    }


def reduced_motion_check(page: Page, route: str) -> list[dict]:
    selector = ".ac-program-card" if route == "/discover" else ".learning-course-card"
    card = page.locator(selector).first
    expect(card).to_be_visible()
    original = page.evaluate("""() => ({
      motion:document.documentElement.getAttribute('data-motion'),
      reduced:document.documentElement.getAttribute('data-reduced-motion')
    })""")
    results = []
    try:
        for name, os_motion, mode, explicit in (
            ("os-reduce-system", "reduce", "system", "false"),
            ("explicit-reduced", "no-preference", "reduced", "false"),
            ("effective-reduced-flag", "no-preference", "full", "true"),
        ):
            page.emulate_media(reduced_motion=os_motion)
            page.evaluate(
                """({mode,explicit}) => {
              document.documentElement.dataset.motion=mode;
              document.documentElement.dataset.reducedMotion=explicit;
            }""",
                {"mode": mode, "explicit": explicit},
            )
            page.mouse.move(1, 1)
            card.hover()
            transform = card.evaluate("e => getComputedStyle(e).transform")
            results.append({"case": name, "selector": selector, "transform": transform})
            assert transform == "none", f"{name}: {selector} hover transforms with {transform}"
    finally:
        page.emulate_media(reduced_motion="reduce")
        page.evaluate(
            """original => {
          const root=document.documentElement;
          for (const [name,value] of [['data-motion',original.motion],
            ['data-reduced-motion',original.reduced]]) {
            if(value===null) root.removeAttribute(name); else root.setAttribute(name,value);
          }
        }""",
            original,
        )
    return results


def run_case(
    browser,
    args,
    run_dir: Path,
    route: str,
    heading: str,
    theme: str,
    width: int,
    height: int,
    visual: bool,
) -> dict:
    case = {
        "route": route,
        "theme": theme,
        "viewport": {"width": width, "height": height},
        "evidence_class": FIXTURE_LABEL,
        "checks": {},
        "screenshots": [],
        "network": {
            "fixture_reads": [],
            "unknown_api_reads": [],
            "blocked_writes": [],
            "blocked_external": [],
        },
        "page_errors": [],
        "console_errors": [],
        "failures": [],
    }
    prefix = f"fixture-{route.strip('/')}-{theme}-{width}x{height}"
    context = browser.new_context(
        viewport={"width": width, "height": height},
        color_scheme=theme,
        reduced_motion="reduce",
        service_workers="block",
    )
    context.add_init_script(
        f"localStorage.setItem('ac-appearance-theme', {json.dumps(theme)});"
        "localStorage.setItem('ac-appearance-motion', 'reduced');"
        "localStorage.setItem('ac.learner.sidebar.collapsed.v1', 'false');"
    )
    context.route("**/*", lambda request: route_handler(request, case["network"], args.base_url))
    page = context.new_page()
    page.set_default_timeout(args.timeout_ms)
    page.on("pageerror", lambda error: case["page_errors"].append(str(error)[:500]))
    page.on(
        "console",
        lambda message: (
            case["console_errors"].append(message.text[:500]) if message.type == "error" else None
        ),
    )
    try:
        response = page.goto(
            f"{args.base_url}{route}", wait_until="domcontentloaded", timeout=args.timeout_ms
        )
        assert response and response.status < 400, (
            f"Navigation status: {response.status if response else 'none'}"
        )
        page.wait_for_load_state("networkidle", timeout=args.timeout_ms)
        expect(page.get_by_role("heading", name=heading, exact=True)).to_be_visible()
        expect(page.get_by_role("heading", name=PROGRAM["title"], exact=True)).to_be_visible()
        case["checks"]["layout"] = check_layout(page, route, theme)
        if args.probe:
            case["controls"] = page.locator("button:visible,a:visible,input:visible").evaluate_all(
                """es => es.slice(0,55).map(e=>({tag:e.tagName,
                  role:e.getAttribute('role'),label:e.getAttribute('aria-label'),
                  text:e.textContent.trim().slice(0,80)}))"""
            )
            case["screenshots"].append(capture(page, run_dir, f"{prefix}-probe"))
            return case
        if visual:
            collapsed = page.get_by_role("button", name="Collapse sidebar", exact=True)
            desktop = collapsed.is_visible()
            case["screenshots"].append(
                capture(page, run_dir, f"{prefix}-{'expanded' if desktop else 'mobile'}")
            )
            if desktop:
                case["checks"]["profile_name_contrast"] = text_contrast(
                    page.locator(".learner-profile__name")
                )
                assert case["checks"]["profile_name_contrast"]["solidColorMeasurement"], (
                    "Profile-name contrast requires unsupported background/opacity compositing"
                )
                assert case["checks"]["profile_name_contrast"]["contrast"] >= 4.5, (
                    "Desktop profile name has insufficient contrast"
                )
                case["checks"]["reduced_motion_hover"] = reduced_motion_check(page, route)
                expanded_width = page.locator(".learner-sidebar").bounding_box()["width"]
                # The control intentionally appears after pointer entry into the rail.
                # This is a normal hover then real click, never a force click or CSS edit.
                page.locator(".learner-sidebar").hover(position={"x": 12, "y": 160})
                expect(collapsed).to_have_css("opacity", "1")
                expect(collapsed).to_have_css("pointer-events", "auto")
                collapsed.click()
                expect(
                    page.get_by_role("button", name="Expand sidebar", exact=True)
                ).to_be_visible()
                expect(page.locator(".site-frame")).to_have_class(
                    re.compile("site-frame--collapsed")
                )
                case["checks"]["collapsed_layout"] = check_layout(page, route, theme)
                collapsed_width = page.locator(".learner-sidebar").bounding_box()["width"]
                assert collapsed_width < expanded_width, "Collapse did not reduce sidebar width"
                case["checks"]["sidebar_toggle"] = {
                    "expanded_width": expanded_width,
                    "collapsed_width": collapsed_width,
                }
                page.get_by_role("heading", name=heading, exact=True).click()
                case["screenshots"].append(capture(page, run_dir, f"{prefix}-collapsed"))
            else:
                case["screenshots"].append(
                    capture(page, run_dir, f"{prefix}-mobile-full", full_page=True)
                )
            for name, action in (
                ("search", search_check),
                *((("more", more_check),) if not desktop else ()),
            ):
                try:
                    case["checks"][name] = action(page, run_dir, prefix)
                    case["screenshots"].append(case["checks"][name]["screenshot"])
                except Exception as error:
                    case["failures"].append(f"{name}: {type(error).__name__}: {str(error)[:600]}")
                    case["screenshots"].append(capture(page, run_dir, f"{prefix}-{name}-failure"))
                    page.keyboard.press("Escape")
            case["checks"]["final_layout"] = check_layout(page, route, theme)
        elif width == 320:
            case["screenshots"].append(capture(page, run_dir, f"{prefix}-layout"))
    except Exception as error:
        case["failures"].append(f"{type(error).__name__}: {str(error)[:600]}")
        case["screenshots"].append(capture(page, run_dir, f"{prefix}-failure", full_page=True))
    finally:
        context.close()
    return case


def main() -> int:
    args = parse_args()
    run_dir = args.output.resolve() / datetime.now(UTC).strftime("run-%Y%m%dT%H%M%SZ")
    run_dir.mkdir(parents=True, exist_ok=False)
    report = {
        "evidence_class": FIXTURE_LABEL,
        "base_url": args.base_url,
        "created_utc": datetime.now(UTC).isoformat(),
        "fresh_browser_context": True,
        "user_cookies_or_storage_loaded": False,
        "server_writes_allowed": False,
        "cases": [],
    }
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(channel="chrome", headless=True)
        report["browser_version"] = browser.version
        try:
            cases = (
                [("/discover", "Discover Programs", "light", 1440, 900, True)]
                if args.probe
                else [
                    (route, heading, theme, width, height, visual)
                    for route, heading in ROUTES
                    for theme in ("light", "dark")
                    for width, height, visual in (
                        (1440, 900, True),
                        (390, 844, True),
                        (320, 844, False),
                        (768, 900, False),
                        (1024, 900, False),
                        (1920, 1080, False),
                    )
                ]
            )
            for route, heading, theme, width, height, visual in cases:
                case = run_case(
                    browser, args, run_dir, route, heading, theme, width, height, visual
                )
                report["cases"].append(case)
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
                (run_dir / "results.json").write_text(
                    json.dumps(report, indent=2), encoding="utf-8"
                )
        finally:
            browser.close()
    report["failure_count"] = sum(len(case["failures"]) for case in report["cases"])
    report["blocked_write_count"] = sum(
        len(case["network"]["blocked_writes"]) for case in report["cases"]
    )
    report["unknown_api_reads"] = sorted(
        {path for case in report["cases"] for path in case["network"]["unknown_api_reads"]}
    )
    (run_dir / "results.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(
        json.dumps(
            {
                "output": str(run_dir),
                "cases": len(report["cases"]),
                "failure_count": report["failure_count"],
                "blocked_write_count": report["blocked_write_count"],
                "unknown_api_reads": report["unknown_api_reads"],
            }
        ),
        flush=True,
    )
    return 1 if report["failure_count"] or report["blocked_write_count"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
