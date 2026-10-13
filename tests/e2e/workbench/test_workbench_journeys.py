"""Opt-in browser acceptance on an existing dev/staging server; never starts one."""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
from collections.abc import Iterator
from contextlib import contextmanager, suppress
from dataclasses import dataclass, field
from datetime import UTC, datetime
from html import unescape
from http.cookiejar import HTTPONLY_ATTR, LoadError, MozillaCookieJar
from pathlib import Path
from urllib.parse import parse_qs, urlsplit
from zipfile import ZipFile

import pytest
from playwright.sync_api import (
    Browser,
    BrowserContext,
    ConsoleMessage,
    Frame,
    Locator,
    Page,
    Route,
    expect,
    sync_playwright,
)

pytestmark = pytest.mark.e2e

REPORT_SECTIONS = (
    ("overview", "The Big Picture"),
    ("coaching", "How the Call Played Out"),
    ("moments", "What Worked — & What Didn't"),
    ("missed", "Moments That Mattered"),
    ("skills", "Your Skills on This Call"),
    ("facts", "Where the Deal Stands"),
)
COACHING_SECTIONS = (
    "What You Should Work On Now",
    "Why This Keeps Happening",
    "Here’s What Better Looks Like",
    "Try This on Your Next Call",
    "See How You’re Improving",
    "Where We Go From Here",
)
REP_COACHING_SECTIONS = (
    "What They Should Work On Now",
    "Why This Keeps Happening",
    "Here’s What Better Looks Like",
    "Try This on Their Next Call",
    "See How They’re Improving",
    "Where We Go From Here",
)
SKILL_ROWS = (
    "Human Connection & Trust",
    "Discovery",
    "Qualification",
    "Problem / Impact / Desire",
    "Presentation & Value",
    "Objection Intelligence",
    "Closing",
    "Communication",
)
DEEPER_GROUPS = (
    "Discovery & Qualification",
    "Presentation & Value",
    "Objection / Price / Decision",
    "Communication",
)
REPORT_BLOCKS = {
    "overview": ("What most affected this call", "Strongest part", "Biggest concern", "Next step"),
    "coaching": ("Talk share", "Questions asked", "Talk-overs", "Before", "The switch", "After"),
    "moments": ("What worked", "What didn't"),
    "facts": (
        "Prospect's position",
        re.compile(r"(?:Current|Possible) blocker"),
        re.compile(r"(?:Prospect|Amit) agreed to"),
        "You agreed to",
        "Next event",
        re.compile(r"(?:Recommended next move|Next move on this deal)"),
    ),
}


def _path(name: str, default: str) -> str:
    path = os.environ.get(name, default)
    parsed = urlsplit(path)
    if parsed.scheme or parsed.netloc or not path.startswith("/"):
        pytest.fail(f"{name} must be a path on WB_BASE_URL")
    return path


def _heading(page: Page, label: str) -> Locator:
    # Panel headings include a desktop-only count/subtitle in their accessible name.
    return page.get_by_role("heading", name=re.compile(r"^" + re.escape(label) + r"(?:\s|$)"))


def _call_title_links(
    call_list: Locator, calls: list[dict[str, object]], *, include_hidden: bool = False
) -> Locator:
    """Count source call titles independently of their separate Report actions."""
    names = re.compile(
        r"^(?:" + "|".join(re.escape(str(call["call_label"])) for call in calls) + r")$"
    )
    return call_list.get_by_role("link", name=names, include_hidden=include_hidden)


def _fictional_api_reply(method: str, pathname: str, query: str) -> dict[str, object]:
    """Reuse the builders' existing read-only bootstrap replies, without a shell."""
    node_binary = shutil.which("node")
    assert node_binary, "The existing fictional harness requires Node"
    return json.loads(
        subprocess.check_output(  # noqa: S603 -- fixture arguments, never shell code
            [
                node_binary,
                str(Path(__file__).with_name("fictional-api-reply.mjs")),
                method,
                pathname,
                "?" + query if query else "",
            ],
            text=True,
            timeout=10,
        )
    )


def _document_preview(page: Page) -> Locator:
    return page.get_by_role(
        "region", name=re.compile(r"^(?:Sales Xray document preview|Report document)$")
    )


def _document_download(page: Page) -> Locator:
    name = re.compile(r"^(?:Download\s+)?(?:Word\b|\.docx\b)", re.IGNORECASE)
    return page.get_by_role("link", name=name).or_(page.get_by_role("button", name=name))


def _switch_report_view(page: Page, label: str) -> None:
    action = page.get_by_role("button", name=label, exact=True)
    if not action.count():
        page.locator('summary[aria-label="More views"]').click()
    action.click()


def _cookie_jar_path() -> Path | None:
    reference = os.environ.get("WB_STORAGE_STATE")
    if not reference:
        return None
    path = Path(reference)
    try:
        if path.read_bytes().startswith(b"# Netscape HTTP Cookie File"):
            return path
    except OSError:
        pytest.fail("The approved session reference cannot be read", pytrace=False)
    return None


def _restore_cookie_jar(context: BrowserContext, path: Path) -> None:
    jar = MozillaCookieJar(str(path))
    try:
        jar.load(ignore_discard=True)
    except (OSError, LoadError):
        pytest.fail("The approved cookie jar cannot be loaded", pytrace=False)
    origin = urlsplit(os.environ["WB_BASE_URL"])
    cookies = list(jar)
    if not cookies:
        pytest.fail("The approved cookie jar has no unexpired cookies", pytrace=False)
    if any(cookie.domain.lstrip(".") != origin.hostname for cookie in cookies):
        pytest.fail("The approved cookie jar belongs to a different host", pytrace=False)
    if origin.scheme != "https" and any(cookie.secure for cookie in cookies):
        pytest.fail("The approved secure cookie requires HTTPS", pytrace=False)
    # Reuse the existing cookie and its metadata in memory; never issue a
    # session, change its host or persist a second credential-bearing file.
    context.add_cookies(
        [
            {
                "name": cookie.name,
                "value": cookie.value or "",
                "domain": cookie.domain,
                "path": cookie.path,
                "expires": cookie.expires if cookie.expires is not None else -1,
                "secure": cookie.secure,
                "httpOnly": cookie.has_nonstandard_attr(HTTPONLY_ATTR),
            }
            for cookie in cookies
        ]
    )


def _local_transport(origin: str) -> str | None:
    transport = os.environ.get("WB_LOCAL_TRANSPORT")
    if not transport:
        return None
    allowed = {
        "https://salesxray-staging.authorityclosers.com",
        "https://salesxray.authorityclosers.com",
    }
    if (
        os.environ.get("WB_MODE") != "live"
        or origin.rstrip("/") not in allowed
        or transport.rstrip("/") != "http://127.0.0.1:8080"
    ):
        pytest.fail(
            "Local transport requires an approved hosted HTTPS origin and :8080", pytrace=False
        )
    return transport.rstrip("/")


@pytest.fixture(scope="session")
def browser() -> Iterator[Browser]:
    origin = os.environ.get("WB_BASE_URL")
    if not origin:
        pytest.skip("Set WB_BASE_URL explicitly to run shared-server browser acceptance")
    parsed = urlsplit(origin)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc or parsed.username:
        pytest.fail("WB_BASE_URL must be an HTTP(S) origin without credentials")
    mode = os.environ.get("WB_MODE", "fixture")
    if mode not in {"fixture", "live"}:
        pytest.fail("WB_MODE must be fixture or live")
    if mode == "live" and not all(
        os.environ.get(key) for key in ("WB_STORAGE_STATE", "WB_REPORT_PATH")
    ):
        pytest.fail("Live acceptance requires WB_STORAGE_STATE and WB_REPORT_PATH")
    _local_transport(origin)
    with sync_playwright() as playwright:
        instance = playwright.chromium.launch()
        try:
            yield instance
        finally:
            instance.close()


@pytest.fixture(params=[(1440, "light"), (1440, "dark"), (390, "light"), (390, "dark")])
def viewport(request: pytest.FixtureRequest) -> tuple[int, str]:
    return request.param  # type: ignore[no-any-return]


@dataclass
class Journey:
    page: Page
    context: BrowserContext
    name: str
    width: int
    theme: str
    directory: Path
    runtime_errors: list[str] = field(default_factory=list)
    server_errors: list[str] = field(default_factory=list)
    visual_errors: list[str] = field(default_factory=list)
    fixture_outcome_requests: list[str] = field(default_factory=list)
    outcome_persistence: dict[str, object] | None = None
    coaching_switch: dict[str, object] | None = None
    observations: list[dict[str, object]] = field(default_factory=list)
    main_navigations: int = 0
    live_refreshes: int = 0
    refresh_events: list[dict[str, object]] = field(default_factory=list)
    local_transport: str | None = None
    blocked_mutations: list[str] = field(default_factory=list)

    @property
    def fixture(self) -> bool:
        return os.environ.get("WB_MODE", "fixture") == "fixture"

    def open(self, path: str) -> None:
        response = self.page.goto(path, wait_until="domcontentloaded", timeout=60_000)
        assert response is not None and response.status < 400, (
            f"{self.name}: page returned {response.status if response else 'no response'}"
        )
        self.page.locator("h1,h2").first.wait_for(timeout=30_000)
        expect(self.page.locator("html")).to_have_attribute("data-theme", self.theme)

    def snapshot(self, step: str) -> None:
        """Save viewport evidence, including panels in nested scroll containers."""
        path = self.directory / f"{self.name}-{step}-{self.width}-{self.theme}.png"
        self.page.screenshot(path=str(path), animations="disabled", timeout=30_000)
        metrics = self.page.evaluate(
            """() => {
              const root = document.documentElement;
              const undersized = [];
              let checked = 0;
              const scales = new WeakMap();
              function scale(el) {
                if (!el) return 1;
                if (scales.has(el)) return scales.get(el);
                const transform = getComputedStyle(el).transform;
                const matrix = transform === 'none' ? null : new DOMMatrix(transform);
                const own = matrix ? Math.hypot(matrix.c, matrix.d) : 1;
                const result = own * scale(el.parentElement);
                scales.set(el, result);
                return result;
              }
              for (const el of document.querySelectorAll(
                  'main *, [data-report-modes] *, [data-coaching-pillar] *, ' +
                  'section[aria-label] *, section[aria-labelledby] *')) {
                // Decorative initials accompany a separately rendered speaker name.
                if (el.matches('[aria-hidden="true"][class*="avatar"]')) continue;
                // Closed details can retain layout bounds without painting their content.
                if (!el.checkVisibility({checkOpacity: true, checkVisibilityCSS: true})) continue;
                const text = Array.from(el.childNodes).some(n => {
                  if (n.nodeType !== Node.TEXT_NODE || !n.textContent.trim()) return false;
                  const range = document.createRange();
                  range.selectNodeContents(n);
                  const bounds = range.getBoundingClientRect();
                  return bounds.width > 0 && bounds.height > 0;
                });
                if (!text) continue;
                const r = el.getBoundingClientRect();
                const style = getComputedStyle(el);
                if (r.width <= 1 || r.height <= 1 || r.bottom < 0 || r.top > innerHeight ||
                    style.visibility === 'hidden' || parseFloat(style.opacity) === 0) continue;
                checked++;
                const cssSize = parseFloat(style.fontSize);
                const size = cssSize * scale(el);
                if (size < 11.99) undersized.push({tag: el.tagName, size, cssSize,
                  class: typeof el.className === 'string' ? el.className : '',
                  width: r.width, height: r.height});
              }
              return {viewport: innerWidth, document: root.scrollWidth,
                body: document.body.scrollWidth, checked, undersized,
                busy: document.querySelectorAll('[aria-busy="true"]').length};
            }"""
        )
        self.observations.append({"step": step, "screenshot": str(path), **metrics})
        if not metrics["checked"]:
            self.visual_errors.append(f"{step}: no rendered text was audited; screenshot {path}")
        if max(metrics["document"], metrics["body"]) > self.width + 1:
            self.visual_errors.append(f"{step}: sideways overflow; screenshot {path}")
        if metrics["undersized"]:
            self.visual_errors.append(
                f"{step}: text below 12px: {metrics['undersized'][:8]}; {path}"
            )

    def settled(self) -> None:
        expect(self.page.locator('[aria-busy="true"]:visible')).to_have_count(0, timeout=30_000)
        assert not self.runtime_errors, f"Browser exceptions: {self.runtime_errors}"
        assert not self.server_errors, f"HTTP server errors: {self.server_errors}"
        assert not self.visual_errors, f"Visual acceptance: {self.visual_errors}"
        assert not self.fixture_outcome_requests, "Fictional outcome attempted a live API request"
        assert not self.blocked_mutations, "Read-only hosted smoke attempted a mutating request"
        assert (
            not self.page.locator("nextjs-portal").get_by_text("Runtime Error", exact=False).count()
        ), "Next runtime error overlay is present"

    def unclipped_text(self, target: Locator) -> None:
        """Keep totals readable rather than passing on hidden ellipsised text."""
        metrics = target.evaluate(
            """root => {
              const clipped = [];
              let checked = 0;
              for (const el of [root, ...root.querySelectorAll('*')]) {
                if (!el.checkVisibility({checkOpacity: true, checkVisibilityCSS: true})) continue;
                if (![...el.childNodes].some(n =>
                    n.nodeType === Node.TEXT_NODE && n.textContent.trim())) continue;
                const style = getComputedStyle(el);
                // A 1px clipped label is deliberately available to screen readers.
                if (el.clientWidth <= 1 && el.clientHeight <= 1 &&
                    (style.clip === 'rect(0px, 0px, 0px, 0px)' ||
                     style.clipPath === 'inset(50%)')) continue;
                const clips = value => ['hidden', 'clip'].includes(value);
                checked += 1;
                const horizontal = el.clientWidth > 0 && clips(style.overflowX) &&
                  el.scrollWidth > el.clientWidth + 1;
                const vertical = el.clientHeight > 0 && clips(style.overflowY) &&
                  el.scrollHeight > el.clientHeight + 1;
                if (horizontal || vertical) clipped.push({tag: el.tagName,
                  width: el.clientWidth, contentWidth: el.scrollWidth,
                  height: el.clientHeight, contentHeight: el.scrollHeight});
              }
              return {checked, clipped};
            }"""
        )
        # Geometry only: never retain learner names or other page text.
        self.observations[-1]["text_clipping"] = metrics
        assert metrics["checked"] > 0, "No rendered text was checked"
        assert not metrics["clipped"], "Rendered text is clipped"

    def document_controls(self) -> None:
        minimum = 44 if self.width == 390 else 32
        sizes = (
            self.page.locator("[data-document-export]")
            .locator("a[href],button")
            .evaluate_all(
                """els => els.filter(el => el.checkVisibility({checkOpacity: true,
                checkVisibilityCSS: true})).map(el => {
              const r = el.getBoundingClientRect();
              return {tag: el.tagName, width: r.width, height: r.height};
            })"""
            )
        )
        small = [item for item in sizes if min(item["width"], item["height"]) < minimum - 0.01]
        self.observations[-1]["document_controls"] = {
            "checked": len(sizes),
            "minimum": minimum,
            "undersized": small,
        }
        assert sizes, "No rendered Document controls were checked"
        assert not small, f"Document controls are below {minimum}px"

    def control_target(self, control: Locator, label: str) -> None:
        """Check a visible control's size and actual pointer reachability."""
        control.scroll_into_view_if_needed()
        expect(control).to_be_visible()
        metrics = control.evaluate(
            """el => {
              const r = el.getBoundingClientRect();
              const hit = document.elementFromPoint(r.x + r.width / 2, r.y + r.height / 2);
              return {width: r.width, height: r.height,
                reachable: hit === el || el.contains(hit)};
            }"""
        )
        self.observations[-1][f"target_{label}"] = metrics
        minimum = 44 if self.width == 390 else 32
        if min(metrics["width"], metrics["height"]) < minimum - 0.01:
            self.visual_errors.append(f"{label}: target is below {minimum}px")
        if not metrics["reachable"]:
            self.visual_errors.append(f"{label}: target is covered")

    def follow_mission(self, anchor: str, step: str) -> None:
        """Check the primary mission action as a real tap, without saving feedback."""
        link = self.page.get_by_role("link", name="See the mission", exact=True)
        link.scroll_into_view_if_needed()
        expect(link).to_be_visible()
        target = link.evaluate(
            """el => {
              const r = el.getBoundingClientRect();
              const hit = document.elementFromPoint(r.x + r.width / 2, r.y + r.height / 2);
              return {width: r.width, height: r.height,
                reachable: hit === el || el.contains(hit)};
            }"""
        )
        # Keep dimensions in the receipt so a later stylesheet change is reviewable.
        self.observations[-1]["mission_action"] = target
        minimum = 44 if self.width == 390 else 32
        assert min(target["width"], target["height"]) >= minimum - 0.01, (
            f"{step}: mission tap target is below {minimum}px: {target}"
        )
        assert target["reachable"], f"{step}: mission action is covered"
        expect(link).to_have_attribute("href", f"#{anchor}")
        link.click()
        expect(self.page).to_have_url(re.compile(r"#" + re.escape(anchor) + r"$"))
        mission = self.page.locator(f"#{anchor}")
        expect(mission.get_by_role("heading").first).to_be_in_viewport()
        expect(mission).to_contain_text("Done when")
        self.snapshot(step)

    def row_link_target(self, link: Locator, label: str) -> None:
        """Measure a stretched row link using real hits across its claimed area."""
        link.locator("xpath=ancestor::li[1]").scroll_into_view_if_needed()
        expect(link).to_be_visible()
        metrics = link.evaluate(
            """el => {
              const row = el.closest('li').getBoundingClientRect();
              const text = el.getBoundingClientRect();
              const cx = row.x + row.width / 2, cy = row.y + row.height / 2;
              const points = [[cx, cy], [cx, row.y + 2],
                [cx, row.bottom - 2], [row.x + 2, cy], [row.right - 2, cy]];
              return {width: row.width, height: row.height,
                textHeight: text.height, hits: points.map(([x, y]) => {
                  const hit = document.elementFromPoint(x, y);
                  return hit === el || el.contains(hit);
                })};
            }"""
        )
        self.observations[-1][f"target_{label}"] = metrics
        minimum = 44 if self.width == 390 else 32
        if min(metrics["width"], metrics["height"]) < minimum - 0.01:
            self.visual_errors.append(f"{label}: clickable row is below {minimum}px")
        if not all(metrics["hits"]):
            self.visual_errors.append(f"{label}: row link does not cover its claimed hit area")


def _install_local_transport(journey: Journey, origin: str) -> None:
    transport = _local_transport(origin)
    if transport is None:
        return
    journey.local_transport = transport
    host = urlsplit(origin).netloc

    def read(route: Route) -> None:
        request = route.request
        if request.method not in {"GET", "HEAD", "OPTIONS"}:
            journey.blocked_mutations.append(request.method)
            route.abort("blockedbyclient")
            return
        target = urlsplit(request.url)
        suffix = target.path + ("?" + target.query if target.query else "")
        # Preserve the original browser URL, TLS cookie scope and headers in memory.
        # Disable redirects here; Chromium handles them at the original origin.
        try:
            response = route.fetch(
                url=transport + suffix,
                headers={**request.all_headers(), "host": host},
                max_redirects=0,
                timeout=30_000,
            )
        except Exception as error:
            # Fetch exceptions can quote request headers. Never let those into logs.
            journey.runtime_errors.append(type(error).__name__)
            route.fulfill(
                status=502,
                content_type="application/json",
                body='{"detail":"The local hosted read is unavailable."}',
            )
            return
        route.fulfill(response=response)

    journey.page.route(origin.rstrip("/") + "/**", read)


@contextmanager
def _journey(browser: Browser, viewport: tuple[int, str], name: str) -> Iterator[Journey]:
    width, theme = viewport
    default_directory = Path.home() / ".cache" / "ac-workbench-qa"
    directory = Path(os.environ.get("WB_SHOTS_DIR", str(default_directory)))
    directory.mkdir(parents=True, exist_ok=True)
    cookie_jar = _cookie_jar_path()
    context = browser.new_context(
        base_url=os.environ["WB_BASE_URL"].rstrip("/"),
        viewport={"width": width, "height": 844 if width == 390 else 1000},
        is_mobile=width == 390,
        has_touch=width == 390,
        color_scheme=theme,
        reduced_motion="reduce",
        storage_state=None if cookie_jar else os.environ.get("WB_STORAGE_STATE") or None,
        service_workers="block" if os.environ.get("WB_LOCAL_TRANSPORT") else "allow",
        accept_downloads=True,
    )
    context.add_init_script(f"localStorage.setItem('sales-xray:theme', {json.dumps(theme)});")
    page = context.new_page()
    page.set_default_timeout(15_000)
    journey = Journey(page, context, name, width, theme, directory)
    _install_local_transport(journey, os.environ["WB_BASE_URL"])
    if journey.fixture:

        def block_fixture_outcome(route: Route) -> None:
            journey.fixture_outcome_requests.append(route.request.method)
            route.abort()

        page.route("**/v1/conversation/prospects/calls/*/outcome", block_fixture_outcome)
    # No traces, request bodies, cookies or full error messages in receipts.
    page.on("pageerror", lambda error: journey.runtime_errors.append(error.name))

    # Count live-edit interruptions without retaining console/customer text.
    def navigation(frame: Frame) -> None:
        if frame == page.main_frame:
            journey.main_navigations += 1

    def console(message: ConsoleMessage) -> None:
        if message.text.startswith("[Fast Refresh]"):
            journey.live_refreshes += 1
            phase = (
                "rebuilding"
                if "rebuilding" in message.text
                else "done"
                if "done" in message.text
                else "other"
            )
            journey.refresh_events.append(
                {"phase": phase, "at_ms": int(datetime.now(UTC).timestamp() * 1000)}
            )

    page.on("framenavigated", navigation)
    page.on("console", console)
    page.on(
        "response",
        lambda response: (
            journey.server_errors.append(f"{response.status} {urlsplit(response.url).path}")
            if response.status >= 500
            else None
        ),
    )
    passed = False
    failure: dict[str, object] | None = None
    try:
        if cookie_jar:
            _restore_cookie_jar(context, cookie_jar)
        yield journey
        journey.settled()
        passed = True
    except BaseException as error:
        # Retain a safe failure location even if the host stops the batch before
        # pytest's final summary. Exception text may contain customer content.
        failure = {"type": type(error).__name__}
        frame = error.__traceback__
        while frame is not None:
            if frame.tb_frame.f_code.co_filename == __file__:
                failure["check"] = frame.tb_frame.f_code.co_name
                failure["line"] = frame.tb_lineno
            frame = frame.tb_next
        raise
    finally:
        if not passed:
            with suppress(Exception):
                page.screenshot(
                    path=str(directory / f"{name}-failure-{width}-{theme}.png"),
                    animations="disabled",
                    timeout=10_000,
                )
        receipt = {
            "journey": name,
            "width": width,
            "theme": theme,
            "mode": "fixture" if journey.fixture else "live",
            "checked_at": datetime.now(UTC).isoformat(),
            "passed": passed,
            "failure": failure,
            "main_navigations": journey.main_navigations,
            "live_refreshes": journey.live_refreshes,
            "refresh_events": journey.refresh_events,
            "local_transport": journey.local_transport,
            "blocked_mutations": journey.blocked_mutations,
            "runtime_errors": journey.runtime_errors,
            "server_errors": journey.server_errors,
            "visual_errors": journey.visual_errors,
            "fixture_outcome_requests": journey.fixture_outcome_requests,
            "outcome_persistence": journey.outcome_persistence,
            "coaching_switch": journey.coaching_switch,
            "observations": journey.observations,
        }
        (directory / f"{name}-{width}-{theme}.json").write_text(json.dumps(receipt, indent=2))
        context.close()


def _word_paragraphs(document: str) -> list[str]:
    # Generated OOXML text only: no XML parser or entity resolution.
    return [
        "".join(
            unescape(text)
            for text in re.findall(r"<w:t(?:\s[^>]*)?>(.*?)</w:t>", paragraph, re.DOTALL)
        )
        for paragraph in re.findall(r"<w:p(?:\s[^>]*)?>(.*?)</w:p>", document, re.DOTALL)
    ]


def _word_skill_names(document: str) -> None:
    paragraphs = _word_paragraphs(document)
    start = next(
        index
        for index, text in enumerate(paragraphs)
        if re.fullmatch(r"5\.\s+Your Skills on This Call", text, flags=re.IGNORECASE)
    )
    end = next(
        index
        for index in range(start + 1, len(paragraphs))
        if re.fullmatch(r"6\.\s+Where the Deal Stands", paragraphs[index], flags=re.IGNORECASE)
    )
    cursor = start + 1
    for name in SKILL_ROWS:
        cursor = next(index for index in range(cursor, end) if paragraphs[index] == name) + 1


def _outcome_validation_snapshot(journey: Journey, editor: Locator, step: str) -> None:
    notice = editor.get_by_role("alert")
    expect(notice).to_be_visible()
    journey.snapshot(step)
    if journey.width != 390:
        return
    nav = journey.page.get_by_role("navigation", name="Mobile Sales Xray navigation", exact=True)
    notice_box, nav_box = notice.bounding_box(), nav.bounding_box()
    assert notice_box is not None and nav_box is not None
    targets = nav.locator("a, button").evaluate_all(
        """els => els.filter(el => el.checkVisibility()).map(el => {
          const r = el.getBoundingClientRect();
          const hit = document.elementFromPoint(r.x + r.width / 2, r.y + r.height / 2);
          return {width: r.width, height: r.height,
            reachable: hit === el || el.contains(hit)};
        })"""
    )
    journey.observations[-1]["validation_corner"] = {
        "notice": notice_box,
        "mobile_navigation": nav_box,
        "navigation_targets": targets,
    }
    assert notice_box["y"] + notice_box["height"] <= nav_box["y"], (
        "Outcome validation covers the phone's bottom navigation"
    )
    assert targets and all(target["reachable"] for target in targets), (
        "Outcome validation covers a phone navigation target"
    )


def _word_call_outcome(page: Page, status: str, detail: str | None) -> None:
    page.locator("[data-document-export]").evaluate(
        "element => element.scrollIntoView({block: 'start'})"
    )
    with page.expect_download() as downloaded:
        _document_download(page).click()
    download = downloaded.value
    assert download.failure() is None, "Recorded-outcome Word download failed"
    path = download.path()
    assert path is not None
    with ZipFile(path) as docx:
        document = docx.read("word/document.xml").decode()
    paragraphs = _word_paragraphs(document)
    start = next(
        index
        for index, text in enumerate(paragraphs)
        if re.fullmatch(r"1\.1\s+Call Outcome", text, flags=re.IGNORECASE)
    )
    end = next(
        index
        for index in range(start + 1, len(paragraphs))
        if re.match(r"1\.2\s", paragraphs[index])
    )
    outcome = "\n".join(paragraphs[start + 1 : end])
    assert status in outcome, "Word Call Outcome does not reflect the person's choice"
    assert "Set by your team" in outcome, "Word outcome loses its human attribution"
    if detail:
        assert detail in outcome, "Word Call Outcome omits the recorded reason/date"


def _outcome_controls_and_documents(journey: Journey) -> None:
    """Fixture formatting or an explicitly supplied fictional dev call only."""
    page = journey.page
    nav = page.locator("[data-report-sections]")
    picture = page.locator('[data-report-pillar="overview"]')
    badge = picture.locator('span[data-size="lg"] > span[data-tone]')
    editor = picture.get_by_role("region", name=re.compile(r"^Call outcome$", re.IGNORECASE))
    nav.get_by_role("link", name="The Big Picture", exact=True).click()
    expect(editor).to_be_visible()
    editor.get_by_role("button", name="Deal value", exact=True).click()
    editor.get_by_label("Amount", exact=True).fill("25000")
    editor.get_by_label("Currency", exact=True).fill("INR")
    reason = "Fictional prospect chose another option."
    choices = (
        ("won", "Won", None),
        ("lost", "Lost", reason),
        ("follow-up", "Follow-up Set", "Wednesday, 11 Nov"),
        ("no-decision", "Decision Pending", None),
    )
    for key, status, detail in choices:
        editor.get_by_role("button", name=status, exact=True).click()
        if key == "lost":
            editor.get_by_label("Why was it lost?", exact=True).fill("")
            editor.get_by_role("button", name="Save", exact=True).click()
            expect(editor.get_by_role("alert")).to_contain_text("Add why it was lost.")
            expect(badge).to_have_text("Won")
            _outcome_validation_snapshot(journey, editor, "outcome-lost-required")
            editor.get_by_label("Why was it lost?", exact=True).fill(reason)
            editor.get_by_role("button", name="Save", exact=True).click()
        elif key == "follow-up":
            editor.get_by_label("Follow-up date", exact=True).fill("")
            editor.get_by_role("button", name="Save", exact=True).click()
            expect(editor.get_by_role("alert")).to_contain_text("Pick a follow-up date.")
            expect(badge).to_have_text("Lost")
            _outcome_validation_snapshot(journey, editor, "outcome-follow-up-required")
            editor.get_by_label("Follow-up date", exact=True).fill("2026-11-11")
            editor.get_by_role("button", name="Save", exact=True).click()
        expect(editor).to_have_attribute("aria-busy", "false")
        expect(badge).to_have_text(status)
        if not journey.fixture:
            # Each human choice must survive a real document reload. This branch
            # is reachable only through the explicitly opted-in fictional dev test.
            page.reload(wait_until="domcontentloaded")
            expect(badge).to_have_text(status)
            journey.snapshot(f"outcome-{key}-reloaded")
        expect(picture.get_by_text("Set by your team", exact=True)).to_be_visible()
        expect(editor).to_contain_text("25000 INR")
        if key == "lost":
            expect(editor).to_contain_text(reason)
        elif key == "follow-up":
            expect(editor).to_contain_text("2026-11-11")
        journey.snapshot(f"outcome-{key}")
        nav.get_by_role("link", name="Where the Deal Stands", exact=True).click()
        deal_badge = page.locator('[data-report-pillar="facts"] span[data-size] > span[data-tone]')
        expect(deal_badge).to_be_visible()
        expect(deal_badge).to_have_text(status)
        _switch_report_view(page, "Document view")
        outcome = _document_preview(page).locator('[data-document-section="overview"]')
        expect(outcome.get_by_text(status, exact=True)).to_be_visible()
        expect(outcome).to_contain_text("Set by your team")
        if detail:
            expect(outcome).to_contain_text(detail)
        outcome.get_by_text(status, exact=True).scroll_into_view_if_needed()
        journey.snapshot(f"outcome-{key}-document")
        _word_call_outcome(page, status, detail)
        _switch_report_view(page, "Report view")
        nav.get_by_role("link", name="The Big Picture", exact=True).click()
    editor.get_by_role("button", name="Won", exact=True).click()
    expect(editor).to_have_attribute("aria-busy", "false")
    expect(badge).to_have_text("Won")


def _recorded_outcome_reload(journey: Journey) -> None:
    """Actual authenticated fictional persistence; never a fixture substitute."""
    assert not journey.fixture
    page = journey.page
    picture = page.locator('[data-report-pillar="overview"]')
    badge = picture.locator('span[data-size="lg"] > span[data-tone]')
    page.reload(wait_until="domcontentloaded")
    expect(badge).to_have_text("Won")
    expect(picture.get_by_text("Set by your team", exact=True)).to_be_visible()
    journey.snapshot("outcome-reloaded")
    _switch_report_view(page, "Document view")
    expect(
        _document_preview(page)
        .locator('[data-document-section="overview"]')
        .get_by_text("Won", exact=True)
    ).to_be_visible()
    _word_call_outcome(page, "Won", None)


def test_dashboard_to_report(browser: Browser, viewport: tuple[int, str]) -> None:
    with _journey(browser, viewport, "dashboard") as journey:
        default = "/review-fixture/dashboard" if journey.fixture else "/dashboard"
        journey.open(_path("WB_DASHBOARD_PATH", default))
        # A sign-in/empty page must never count as populated acceptance.
        expect(
            journey.page.get_by_role("heading", name="Recent calls", exact=False)
        ).to_be_visible()
        journey.snapshot("populated")
        link = journey.page.locator(
            'a[href*="/analysis/calls/"], a[href*="/calls/"], '
            'a[href*="/review-fixture/report/story"]'
        ).first
        expect(link).to_be_visible()
        link.click()
        expect(journey.page.locator('[data-report-modes][data-view="story"]')).to_be_visible()
        journey.snapshot("opened-report")


def test_report_sections_and_document(browser: Browser, viewport: tuple[int, str]) -> None:
    with _journey(browser, viewport, "report") as journey:
        journey.open(_path("WB_REPORT_PATH", "/review-fixture/report/story"))
        page = journey.page
        report = page.locator('[data-report-modes][data-view="story"]')
        expect(report).to_be_visible()
        nav = page.locator("[data-report-sections]")
        expect(nav.get_by_role("link")).to_have_count(6)
        assert nav.get_by_role("link").evaluate_all(
            "els => els.map(el => el.getAttribute('aria-label'))"
        ) == [label for _, label in REPORT_SECTIONS], "Report order differs from Dipak's spec"
        actions = page.locator('summary[aria-label="More report actions"]')
        actions.click()
        expect(page.get_by_role("button", name="Download report", exact=False)).to_be_visible()
        journey.snapshot("actions")
        # Hit-test without copying a link or invoking a disabled fixture download.
        reachable = page.get_by_role("button", name="Copy link", exact=True).evaluate(
            """el => {
              const r = el.getBoundingClientRect();
              const hit = document.elementFromPoint(r.x + r.width / 2, r.y + r.height / 2);
              return hit === el || el.contains(hit);
            }"""
        )
        journey.observations[-1]["actions_pointer_reachable"] = reachable
        if not reachable:
            journey.visual_errors.append("actions: Copy link is covered by another element")
        actions.click()
        for section, label in REPORT_SECTIONS:
            nav.get_by_role("link", name=label, exact=True).click()
            pillar = page.locator(f'[data-report-pillar="{section}"]:visible')
            expect(pillar).to_be_visible()
            expect(page.get_by_role("heading", name=label, exact=True)).to_be_visible()
            assert len(pillar.inner_text().strip()) > 40, f"{label} is an empty pillar"
            expect(pillar).not_to_contain_text("This part of the report couldn't be shown")
            if journey.fixture:
                for block in REPORT_BLOCKS.get(section, ()):
                    expect(pillar).to_contain_text(block)
            if section == "skills":
                # Dipak specifies eight skills; deeper analysis stays collapsed.
                skill_rows = pillar.locator("li > details")
                expect(skill_rows).to_have_count(8)
                for index, name in enumerate(SKILL_ROWS):
                    expect(skill_rows.nth(index).locator("summary")).to_contain_text(name)
                skill_rows.first.locator("summary").click()
                expect(skill_rows.first).to_have_attribute("open", "")
                expect(skill_rows.first).to_contain_text("Observation")
            if section == "missed":
                expand = pillar.locator('button[aria-expanded="false"]')
                if expand.count():
                    expand.click()
                    expect(pillar.locator('button[aria-expanded="true"]')).to_have_count(1)
            journey.snapshot(section)
            if section == "skills":
                deeper = pillar.locator("details").filter(
                    has=page.get_by_text("Explore deeper analysis", exact=True)
                )
                if journey.fixture:
                    expect(deeper).to_have_count(1)
                if deeper.count():
                    expect(deeper).not_to_have_attribute("open", "")
                    deeper.locator("summary").click()
                    groups = deeper.get_by_role("heading", level=4)
                    if journey.fixture:
                        expect(groups).to_have_count(4)
                        assert groups.all_text_contents() == list(DEEPER_GROUPS)
                    for index in range(groups.count()):
                        groups.nth(index).scroll_into_view_if_needed()
                        expect(groups.nth(index)).to_be_visible()
                        journey.snapshot(f"skills-deeper-{index + 1}")
        # Sharing/reloading preserves the chosen section instead of resetting it.
        page.reload(wait_until="domcontentloaded")
        expect(page).to_have_url(re.compile(r"[?&]section=facts(?:&|$)"))
        expect(
            page.get_by_role("heading", name="Where the Deal Stands", exact=True)
        ).to_be_visible()
        _switch_report_view(page, "Document view")
        preview = _document_preview(page)
        expect(preview).to_be_visible(timeout=30_000)
        headings = preview.locator("[data-report-mode-section]")
        expect(headings).to_have_count(6)
        assert headings.evaluate_all(
            "els => els.map(el => el.getAttribute('data-report-mode-section'))"
        ) == [section for section, _ in REPORT_SECTIONS]
        expect(
            preview.locator('section[data-document-section="skills"]').get_by_role("rowheader")
        ).to_have_text(list(SKILL_ROWS))
        journey.snapshot("document")
        journey.document_controls()
        # A section deep link can land below the document's export controls.
        page.locator("[data-document-export]").evaluate(
            "element => element.scrollIntoView({block: 'start'})"
        )
        with page.expect_download() as downloaded:
            _document_download(page).click()
        download = downloaded.value
        assert download.failure() is None, "Document download failed"
        file = download.path()
        assert file is not None
        with ZipFile(file) as docx:
            document = docx.read("word/document.xml").decode()
            assert all(f'w:name="{section}"' in document for section, _ in REPORT_SECTIONS)
            _word_skill_names(document)
        _switch_report_view(page, "Report view")
        expect(page.locator('[data-report-modes][data-view="story"]')).to_be_visible()
        journey.snapshot("returned")


def test_fixture_legacy_deal_action(browser: Browser, viewport: tuple[int, str]) -> None:
    """An older saved Report keeps its next move across reload, Document and Word."""
    if os.environ.get("WB_MODE", "fixture") != "fixture":
        pytest.skip("Legacy example words are limited to the fictional dev fixture")
    with _journey(browser, viewport, "legacy-action") as journey:
        journey.open("/review-fixture/report/real-format")
        page = journey.page
        action = "Explore internal evaluation criteria before proposing follow-up agendas."
        page.locator("[data-report-sections]").get_by_role(
            "link", name="Where the Deal Stands", exact=True
        ).click()
        deal = page.locator('[data-report-pillar="facts"]:visible')
        expect(deal).to_contain_text("Next move on this deal")
        expect(deal).to_contain_text(action)
        page.reload(wait_until="domcontentloaded")
        expect(deal).to_contain_text(action)
        expect(page).to_have_url(re.compile(r"[?&]section=facts(?:&|$)"))
        selected = page.locator("[data-report-sections]").get_by_role(
            "link", name="Where the Deal Stands", exact=True
        )
        expect(selected).to_have_attribute("aria-current", "location")
        expect(selected).to_be_in_viewport()
        journey.snapshot("saved-next-move")
        mission_label = deal.get_by_text("Coaching mission for your next call", exact=True)
        expect(mission_label).to_be_visible()
        mission_label.locator("..").evaluate("element => element.scrollIntoView({block: 'center'})")
        expect(mission_label).to_be_in_viewport()
        journey.snapshot("coaching-mission")
        mission_geometry = mission_label.evaluate(
            """label => {
              const labelRect = label.getBoundingClientRect();
              const walker = document.createTreeWalker(label.parentElement, NodeFilter.SHOW_TEXT);
              let node;
              while ((node = walker.nextNode())) {
                if (label.contains(node) || !node.textContent.trim()) continue;
                const range = document.createRange();
                range.selectNodeContents(node);
                const textRect = range.getClientRects()[0];
                if (textRect) return {gap: textRect.top - labelRect.bottom};
              }
              return {gap: null};
            }"""
        )
        journey.observations[-1]["coaching_mission_label"] = mission_geometry
        assert mission_geometry["gap"] is not None and mission_geometry["gap"] >= 2, (
            "Coaching mission needs a visible gap below its label"
        )

        _switch_report_view(page, "Document view")
        preview = _document_preview(page)
        expect(preview.locator("section[data-document-section]")).to_have_count(6)
        part = preview.get_by_role("heading", level=4, name=re.compile(r"^6\.9\s")).locator("..")
        expect(part).to_contain_text(action)
        part.scroll_into_view_if_needed()
        journey.snapshot("document-next-move")
        journey.document_controls()
        page.locator("[data-document-export]").evaluate(
            "element => element.scrollIntoView({block: 'start'})"
        )
        with page.expect_download() as downloaded:
            _document_download(page).click()
        download = downloaded.value
        file = download.path()
        assert download.failure() is None and file is not None
        with ZipFile(file) as docx:
            paragraphs = _word_paragraphs(docx.read("word/document.xml").decode())
        start = next(
            index
            for index, text in enumerate(paragraphs)
            if re.fullmatch(r"6\.9\s+Recommended Deal Action", text, re.IGNORECASE)
        )
        end = next(
            (index for index in range(start + 1, len(paragraphs)) if paragraphs[index]),
            None,
        )
        assert end is not None and paragraphs[end] == action, (
            "Word's Recommended Deal Action differs from the saved Report"
        )
        journey.observations[-1]["legacy_action_agreement"] = {
            "report_reload": True,
            "document_part": "6.9",
            "word_verified": True,
        }


def test_fixture_outcome_formats(browser: Browser, viewport: tuple[int, str]) -> None:
    """Separate format acceptance from the full Report and canonical persistence."""
    if os.environ.get("WB_MODE", "fixture") != "fixture":
        pytest.skip("Fictional formatting does not certify a live report")
    with _journey(browser, viewport, "outcome-format") as journey:
        journey.open("/review-fixture/report/story")
        _outcome_controls_and_documents(journey)
        journey.outcome_persistence = {
            "scope": "fixture_format_agreement",
            "canonical_reload_verified": False,
        }


def test_fictional_outcome_persistence(browser: Browser, viewport: tuple[int, str]) -> None:
    # The named builder supplies this exact owned fictional call and an existing
    # approved dev session. Ordinary/staging acceptance cannot enable writes.
    if os.environ.get("WB_MODE") != "live" or not os.environ.get("WB_OUTCOME_WRITE_PATH"):
        pytest.skip("Requires an explicitly supplied fictional dev call and existing session")
    origin = urlsplit(os.environ["WB_BASE_URL"])
    assert (
        origin.scheme == "https" and origin.hostname == "salesxray-dev.authorityclosers.com"
    ) or (origin.scheme == "http" and origin.hostname == "127.0.0.1" and origin.port == 3026), (
        "Outcome writes are limited to the approved dev origin"
    )
    path = _path("WB_OUTCOME_WRITE_PATH", "/")
    matched = re.fullmatch(r"/analysis/calls/([0-9a-f-]{36})", path, re.IGNORECASE)
    assert matched is not None, "Supply the exact owned fictional finished-call route"
    api = f"/v1/conversation/prospects/calls/{matched.group(1)}/outcome"
    with _journey(browser, viewport, "outcome-persistence") as journey:
        journey.open(path)
        before = journey.page.request.get(api)
        assert before.status == 200, "Fictional call outcome is unavailable"
        initial = before.json()
        assert initial.get("schema") == "ac.sales-xray.call-outcome/1"
        assert initial.get("submission_id") == matched.group(1)
        assert initial.get("can_edit") is True, "Existing account must own the fictional call"
        _outcome_controls_and_documents(journey)
        _recorded_outcome_reload(journey)
        after = journey.page.request.get(api)
        assert after.status == 200, "Reloaded fictional outcome is unavailable"
        persisted = after.json()
        saved_value = persisted.get("value")
        assert isinstance(saved_value, dict), "Reloaded outcome must be a saved human fact"
        assert saved_value.get("outcome") == "won"
        assert saved_value.get("deal_value") == {
            "amount": "25000",
            "currency_code": "INR",
        }
        assert persisted.get("revision", 0) > initial.get("revision", 0)
        journey.outcome_persistence = {
            "scope": "authenticated_fictional_dev_api",
            "revision_before": initial["revision"],
            "revision_after": persisted["revision"],
            "canonical_reload_verified": True,
            "choices_reloaded": ["won", "lost", "follow_up", "no_decision"],
        }


def test_document_view(browser: Browser, viewport: tuple[int, str]) -> None:
    with _journey(browser, viewport, "document") as journey:
        if journey.fixture:
            journey.open("/review-fixture/document")
        else:
            journey.open(_path("WB_REPORT_PATH", "/"))
            _switch_report_view(journey.page, "Document view")
        preview = _document_preview(journey.page)
        expect(preview).to_be_visible(timeout=30_000)
        expect(preview.locator("[data-report-mode-section]")).to_have_count(6)
        expect(_document_download(journey.page)).to_be_visible()
        journey.snapshot("ready")
        journey.document_controls()
        if journey.fixture:
            # This fixture's three source excerpts are confirmed by G57fd8db7.
            # Keep the repaired diagnosis/deal action bound to that buyer boundary.
            diagnosis = "The buyer declined a next step and asked the seller not to follow up."
            action = "Respect the buyer's request not to follow up."
            for number, text in (("1.3", diagnosis), ("6.9", action)):
                part = preview.get_by_role(
                    "heading", level=4, name=re.compile(r"^" + re.escape(number) + r"\s")
                ).locator("..")
                expect(part).to_contain_text(text)
            with journey.page.expect_download() as downloaded:
                _document_download(journey.page).click()
            file = downloaded.value.path()
            assert downloaded.value.failure() is None and file is not None
            with ZipFile(file) as docx:
                document = docx.read("word/document.xml").decode()
            assert all(f'w:name="{section}"' in document for section, _ in REPORT_SECTIONS)
            _word_skill_names(document)
            words = " ".join(_word_paragraphs(document))
            assert diagnosis in words and action in words
            assert "The closer clarified a follow-up time." not in words
            journey.observations[-1]["fictional_source_agreement"] = {
                "document_parts": ["1.3", "6.9"],
                "word_verified": True,
                "bookmarks": 6,
                "short_skills": 8,
            }
        sections = preview.locator("section[data-document-section]")
        expect(sections).to_have_count(6)
        assert sections.evaluate_all(
            "els => els.map(el => el.getAttribute('data-document-section'))"
        ) == [section for section, _ in REPORT_SECTIONS]
        for section, label in REPORT_SECTIONS:
            panel = preview.locator(f'section[data-document-section="{section}"]')
            if section == "skills":
                expect(panel.get_by_role("rowheader")).to_have_text(list(SKILL_ROWS))
            heading = panel.get_by_role("heading", level=3)
            expect(heading).to_contain_text(label, ignore_case=True)
            assert len(panel.inner_text().strip()) > 40, "Document section is empty"
            heading.evaluate("element => element.scrollIntoView({block: 'start'})")
            expect(heading).to_be_in_viewport()
            journey.snapshot(section)


def test_coaching_pages(browser: Browser, viewport: tuple[int, str]) -> None:
    with _journey(browser, viewport, "coaching") as journey:
        journey.open(
            _path(
                "WB_COACHING_PATH", "/review-fixture/coaching" if journey.fixture else "/coaching"
            )
        )
        page = journey.page
        if journey.fixture:
            expect(
                page.get_by_role(
                    "heading",
                    name=re.compile(r"^(?:One focus for this call|What You Should Work On Now)$"),
                )
            ).to_be_visible()
            expect(
                page.get_by_role("heading", name="Try This on Your Next Call", exact=True)
            ).to_be_visible()
            expect(page.locator("#call-mission")).to_contain_text("Done when")
            journey.snapshot("call")
            journey.follow_mission("call-mission", "call-mission")
            personal = page.get_by_role("button", name="My coaching", exact=True)
            # Diagnose a lost switch without changing its single-click journey.
            page.evaluate(
                """() => {
                  window.__wbCoachingClick = null;
                  document.addEventListener('click', event => {
                    const button = event.target?.closest?.('button');
                    const label = button?.textContent?.trim();
                    window.__wbCoachingClick = {
                      control: label === 'My coaching' ? 'personal'
                        : label === 'This call' ? 'call' : 'other',
                      x: event.clientX, y: event.clientY,
                      at_ms: Date.now(),
                      pressed: button?.getAttribute('aria-pressed') === 'true'
                    };
                  }, {capture: true, once: true});
                }"""
            )
            try:
                personal.click()
                expect(personal).to_have_attribute("aria-pressed", "true", timeout=15_000)
            finally:
                journey.coaching_switch = page.evaluate(
                    """() => {
                      const buttons = [...document.querySelectorAll('button')];
                      const pressed = label => buttons.find(
                        button => button.textContent.trim() === label
                      )?.getAttribute('aria-pressed') === 'true';
                      const view = new URL(location.href).searchParams.get('view');
                      return {
                        click: window.__wbCoachingClick ?? null,
                        personal_pressed: pressed('My coaching'),
                        call_pressed: pressed('This call'),
                        url_view: ['me', 'team'].includes(view) ? view : null
                      };
                    }"""
                )
        for index, label in enumerate(COACHING_SECTIONS):
            heading = _heading(page, label)
            heading.scroll_into_view_if_needed()
            expect(heading).to_be_visible()
            journey.snapshot(f"personal-pillar-{index + 1}")
        expect(page.locator("#mission")).to_contain_text("Done when")
        expect(_heading(page, COACHING_SECTIONS[0])).to_have_count(1)
        assert page.locator("audio[autoplay],video[autoplay]").count() == 0
        _heading(page, COACHING_SECTIONS[0]).scroll_into_view_if_needed()
        journey.snapshot("personal")
        journey.follow_mission("mission", "personal-mission")
        # Read-only selection: do not send learner feedback, sharing or billing writes.
        if journey.fixture:
            page.get_by_role("button", name="Team", exact=True).click()
        else:
            journey.open(_path("WB_TEAM_PATH", "/coaching?view=team"))
        expect(
            page.get_by_role("heading", name="Who needs help with what", exact=False)
        ).to_be_visible()
        totals = page.get_by_role("region", name="Team coaching totals", exact=True)
        totals.scroll_into_view_if_needed()
        expect(totals.get_by_text("Analysed calls", exact=True)).to_be_visible()
        journey.snapshot("team")
        journey.unclipped_text(totals)
        if journey.fixture:
            page.get_by_role("button", name="AC Sandbox", exact=True).click()
            totals.scroll_into_view_if_needed()
            journey.snapshot("sandbox-team")
            journey.unclipped_text(totals)
            # Latest-call context must remain readable after leaving the small tile.
            context = page.get_by_role(
                "region", name=re.compile(r"^What the team should work on(?:\s|$)")
            ).get_by_text(re.compile(r"Latest call .+\.$"))
            context.scroll_into_view_if_needed()
            expect(context).to_be_visible()
            expect(context).to_be_in_viewport(ratio=1)
            journey.snapshot("sandbox-team-context")
            page.get_by_role("button", name="One rep", exact=True).click()
            expect(
                page.get_by_role(
                    "heading",
                    name=re.compile(r"^What (?:You|They) Should Work On Now(?:\s|$)"),
                )
            ).to_be_visible()
            journey.snapshot("sandbox-rep")
            for index, label in enumerate(REP_COACHING_SECTIONS):
                heading = _heading(page, label)
                heading.scroll_into_view_if_needed()
                expect(heading).to_be_visible()
                journey.snapshot(f"sandbox-rep-pillar-{index + 1}")
            progress = page.locator("#coaching-progress")
            spoken = progress.aria_snapshot()
            summary = "Their calls on this skill, oldest first: 40 needed work."
            assert spoken.count(summary) == 1, "Rep progress needs one spoken summary"
            assert spoken.count("- listitem") <= 6, "Progress announces a row per call"
            expect(progress.get_by_text("Needed work", exact=True)).to_be_visible()


def test_fixture_team_search_and_rep_calls(browser: Browser, viewport: tuple[int, str]) -> None:
    """Find a hidden fictional rep and exercise the separate rep-history fixture."""
    if os.environ.get("WB_MODE", "fixture") != "fixture":
        pytest.skip("Named synthetic Coaching checks are limited to the dev fixture")
    payload = json.loads(
        (
            Path(__file__).resolve().parents[3]
            / "apps/sales-xray-web/app/review-fixture/coaching/sandbox-team.json"
        ).read_text()
    )
    team_data = payload["team"]
    rep = team_data["reps"][8]
    other_area = next(
        row["skill_id"] for row in team_data["suggestions"] if row["skill_id"] != rep["skill_id"]
    )
    latest = max(
        (call for call in payload["rep"]["calls"] if call["state"] == "ready"),
        key=lambda call: datetime.fromisoformat(call["created_at"]),
    )
    skill_ids = {
        point["submission_id"]
        for point in payload["rep"]["progress"]
        if point["state"] != "not_covered"
    }
    skill_calls = [
        call
        for call in payload["rep"]["calls"]
        if call["state"] == "ready" and call["submission_id"] in skill_ids
    ]
    with _journey(browser, viewport, "team-search") as journey:
        journey.open("/review-fixture/coaching?data=sandbox&view=team")
        page = journey.page
        team = page.get_by_role("region", name=re.compile(r"^Who needs help with what"))
        rows = team.get_by_role("list", name="Reps and their current focus").get_by_role("link")
        expect(rows).to_have_count(8)
        match = team.get_by_role("link", name=re.compile(re.escape(rep["name"])))
        expect(match).to_have_count(0)
        search = team.get_by_role("searchbox", name="Find a rep", exact=True)
        area = team.get_by_role("combobox", name="Coaching area", exact=True)
        search.fill(f"  {rep['name'].swapcase()}  ")
        expect(rows).to_have_count(1)
        expect(match).to_contain_text(rep["focus_label"])
        expect(match).to_have_attribute("href", f"/coaching?person={rep['person_id']}")
        expect(team.get_by_role("status")).to_have_text("1 rep")
        area.select_option(rep["skill_id"])
        expect(rows).to_have_count(1)
        team.scroll_into_view_if_needed()
        journey.snapshot("named-match")
        for control, label in ((search, "rep-search"), (area, "area-filter"), (match, "rep-link")):
            journey.control_target(control, label)
        journey.unclipped_text(team)

        area.select_option(other_area)
        expect(rows).to_have_count(0)
        expect(team.get_by_text("No reps match", exact=True)).to_be_visible()
        expect(team.get_by_role("status")).to_have_text("0 reps")
        clear = team.get_by_role("button", name="Clear filters", exact=True)
        clear.scroll_into_view_if_needed()
        journey.snapshot("no-match")
        journey.control_target(clear, "clear-filters")
        clear.click()
        expect(search).to_have_value("")
        expect(search).to_be_focused()
        expect(area).to_have_value("all")
        expect(rows).to_have_count(8)
        expect(team.get_by_role("status")).to_have_text(f"{len(team_data['reps'])} reps")

        expand_reps = team.get_by_role(
            "button", name=f"Show all {len(team_data['reps'])} people", exact=True
        )
        journey.control_target(expand_reps, "show-team-reps")
        expect(expand_reps).to_have_attribute("aria-expanded", "false")
        expand_reps.click()
        expect(rows).to_have_count(len(team_data["reps"]))
        fewer_reps = team.get_by_role("button", name="Show fewer people", exact=True)
        expect(fewer_reps).to_have_attribute("aria-expanded", "true")
        journey.control_target(fewer_reps, "shorten-team-reps")
        fewer_reps.click()
        expect(rows).to_have_count(8)
        expect(search).to_be_focused()
        expect(search).to_be_in_viewport()
        expect(search).to_have_value("")
        expect(area).to_have_value("all")
        expect(expand_reps).to_have_attribute("aria-expanded", "false")
        journey.snapshot("team-shortened")

        page.get_by_role("button", name="One rep", exact=True).click()
        shortcuts = page.get_by_role("navigation", name="This rep’s calls", exact=True)
        expect(shortcuts).to_contain_text(latest["call_label"])
        report = shortcuts.get_by_role("link", name="Open Report", exact=True)
        coaching = shortcuts.get_by_role("link", name="Call coaching", exact=True)
        history_link = shortcuts.get_by_role("link", name="See calls", exact=True)
        expect(report).to_have_attribute("href", f"/analysis/calls/{latest['submission_id']}")
        expect(coaching).to_have_attribute("href", f"/coaching?call={latest['submission_id']}")
        expect(history_link).to_have_attribute("href", "#coaching-calls")
        shortcuts.scroll_into_view_if_needed()
        journey.snapshot("rep-shortcuts")
        for control, label in (
            (report, "open-report"),
            (coaching, "call-coaching"),
            (history_link, "see-calls"),
        ):
            journey.control_target(control, label)
        journey.unclipped_text(shortcuts)
        history_link.click()
        expect(page).to_have_url(re.compile(r"#coaching-calls$"))
        history = page.locator("#coaching-calls")
        expect(history.get_by_role("heading").first).to_be_in_viewport()
        expect(
            _call_title_links(history.get_by_role("list"), payload["rep"]["calls"])
        ).to_have_count(3 if journey.width == 390 else 8)
        journey.snapshot("rep-history")
        show_all = history.get_by_role(
            "button", name=f"Show all {len(payload['rep']['calls'])} calls", exact=True
        )
        journey.control_target(show_all, "show-call-history")
        show_all.click()
        expect(
            _call_title_links(history.get_by_role("list"), payload["rep"]["calls"])
        ).to_have_count(len(payload["rep"]["calls"]))
        on_skill = history.get_by_role("button", name="On this skill", exact=True)
        all_calls = history.get_by_role("button", name="All calls", exact=True)
        journey.control_target(on_skill, "on-this-skill")
        journey.control_target(all_calls, "all-calls")
        on_skill.click()
        expect(on_skill).to_have_attribute("aria-pressed", "true")
        expect(history.get_by_role("status")).to_have_text(f"{len(skill_calls)} calls")
        expect(
            _call_title_links(history.get_by_role("list"), payload["rep"]["calls"])
        ).to_have_count(min(len(skill_calls), 3 if journey.width == 390 else 8))
        skill_expand = history.get_by_role(
            "button", name=f"Show all {len(skill_calls)} calls", exact=True
        )
        skill_expand.click()
        expect(
            _call_title_links(history.get_by_role("list"), payload["rep"]["calls"])
        ).to_have_count(len(skill_calls))
        expect(skill_expand).to_have_count(0)
        assert set(
            _call_title_links(history.get_by_role("list"), payload["rep"]["calls"]).evaluate_all(
                "els => els.map(el => el.getAttribute('href'))"
            )
        ) == {f"/coaching?call={call['submission_id']}" for call in skill_calls}
        history.get_by_role("heading").first.scroll_into_view_if_needed()
        journey.snapshot("skill-history")
        fewer_calls = history.get_by_role("button", name="Show fewer calls", exact=True)
        expect(fewer_calls).to_have_attribute("aria-expanded", "true")
        journey.control_target(fewer_calls, "shorten-skill-calls")
        fewer_calls.click()
        skill_links = _call_title_links(history.get_by_role("list"), payload["rep"]["calls"])
        expect(skill_links).to_have_count(min(len(skill_calls), 3 if journey.width == 390 else 8))
        expect(skill_links.first).to_be_focused()
        expect(skill_links.first).to_be_in_viewport()
        expect(on_skill).to_have_attribute("aria-pressed", "true")
        expect(history.get_by_role("status")).to_have_text(f"{len(skill_calls)} calls")
        expect(skill_expand).to_have_attribute("aria-expanded", "false")
        journey.snapshot("skill-history-shortened")
        all_calls.click()
        expect(all_calls).to_have_attribute("aria-pressed", "true")
        expect(history.get_by_role("status")).to_have_text(f"{len(payload['rep']['calls'])} calls")
        expect(
            _call_title_links(history.get_by_role("list"), payload["rep"]["calls"])
        ).to_have_count(3 if journey.width == 390 else 8)
        journey.observations[-1]["fictional_navigation"] = {
            "initially_hidden_rep_found": True,
            "combined_filter_reset": True,
            "latest_ready_destinations_checked": True,
            "history_expanded": True,
            "saved_skill_history_filtered": True,
            "team_list_shortened_with_focus": True,
            "skill_list_shortened_with_filter_and_focus": True,
            "product_call_destinations_opened": False,
        }


def test_fixture_team_skill_reps(browser: Browser, viewport: tuple[int, str]) -> None:
    """Skill summaries find current reps; progress reaches their saved skill calls."""
    if os.environ.get("WB_MODE", "fixture") != "fixture":
        pytest.skip("Skill-to-rep checks use the fictional dev fixture")
    payload = json.loads(
        (
            Path(__file__).resolve().parents[3]
            / "apps/sales-xray-web/app/review-fixture/coaching/sandbox-team.json"
        ).read_text()
    )
    data = payload["team"]
    skills = [
        skill
        for skill in data["suggestions"]
        if any(rep["skill_id"] == skill["skill_id"] for rep in data["reps"])
    ]
    with _journey(browser, viewport, "team-skill-reps") as journey:
        page = journey.page
        journey.open("/review-fixture/coaching?data=sandbox&view=team")
        team = page.get_by_role("region", name=re.compile(r"^Who needs help with what"))
        summary = page.get_by_role("region", name=re.compile(r"^What the team should work on"))
        search = team.get_by_role("searchbox", name="Find a rep", exact=True)
        area = team.get_by_role("combobox", name="Coaching area", exact=True)
        links = team.get_by_role("list", name="Reps and their current focus").get_by_role("link")
        expect(
            summary.get_by_role("button", name=re.compile(r"^Find reps working on "))
        ).to_have_count(len(skills))
        expect(summary).to_contain_text("Find reps uses their current focus.")
        summary.scroll_into_view_if_needed()
        journey.snapshot("skills")
        journey.unclipped_text(summary)

        def assert_reps(skill: dict[str, object]) -> int:
            matches = [rep for rep in data["reps"] if rep["skill_id"] == skill["skill_id"]]
            expect(search).to_have_value("")
            expect(search).to_be_focused()
            expect(search).to_be_in_viewport()
            expect(area).to_have_value(str(skill["skill_id"]))
            expect(team.get_by_role("status")).to_have_text(f"{len(matches)} reps")
            expect(links).to_have_count(min(8, len(matches)))
            for index, rep in enumerate(matches[:8]):
                expect(links.nth(index)).to_contain_text(rep["name"])
                expect(links.nth(index)).to_contain_text(rep["focus_label"])
                expect(links.nth(index)).to_have_attribute(
                    "href", f"/coaching?person={rep['person_id']}"
                )
            if len(matches) > 8:
                expect(
                    team.get_by_role("button", name=f"Show all {len(matches)} people", exact=True)
                ).to_have_attribute("aria-expanded", "false")
            source_row = summary.get_by_role("listitem").filter(
                has=page.get_by_role(
                    "button", name=f"Find reps working on {skill['label']}", exact=True
                )
            )
            expect(source_row).to_contain_text(
                f"{skill['suggestion_calls']} of {data['analysed_calls']} calls"
            )
            return len(matches)

        previous_count = len(data["reps"])
        for index, skill in enumerate(skills):
            if previous_count > 8:
                team.get_by_role(
                    "button", name=f"Show all {previous_count} people", exact=True
                ).click()
                expect(links).to_have_count(previous_count)
            button = summary.get_by_role(
                "button", name=f"Find reps working on {skill['label']}", exact=True
            )
            journey.control_target(button, f"find-{skill['skill_id']}")
            button.click()
            previous_count = assert_reps(skill)
            if index == 0:
                journey.snapshot("pointer-filtered")
                journey.unclipped_text(team)
                journey.control_target(links.first, "matched-rep")

        last = skills[-1]
        other = next(skill for skill in skills if skill["skill_id"] != last["skill_id"])
        conflict = next(rep for rep in data["reps"] if rep["skill_id"] == last["skill_id"])
        area.select_option(other["skill_id"])
        search.fill(f"  {conflict['name'].swapcase()}  ")
        expect(team.get_by_role("status")).to_have_text("0 reps")
        expect(team.get_by_text("No reps match", exact=True)).to_be_visible()
        button = summary.get_by_role(
            "button", name=f"Find reps working on {last['label']}", exact=True
        )
        button.focus()
        page.keyboard.press("Enter")
        assert_reps(last)
        journey.snapshot("keyboard-filtered")
        journey.unclipped_text(team)
        expect(page).to_have_url(re.compile(r"/review-fixture/coaching\?data=sandbox&view=team$"))
        journey.observations[-1]["skill_reps"] = {
            "skills_checked": len(skills),
            "expanded_list_reset": True,
            "conflicting_name_and_area_reset": True,
            "pointer_and_enter_focus_search": True,
            "current_focus_names_destinations_preserved": True,
            "call_suggestion_counts_preserved": True,
            "product_destinations_opened": False,
        }

        page.get_by_role("button", name="One rep", exact=True).click()
        rep = payload["rep"]
        records = {point["submission_id"]: point["state"] for point in rep["progress"]}
        skill_calls = [
            call
            for call in rep["calls"]
            if call["state"] == "ready"
            and call["submission_id"] in records
            and records[call["submission_id"]] != "not_covered"
        ]
        progress_action = page.get_by_role("button", name="See calls on this skill", exact=True)
        expect(progress_action).to_have_attribute("aria-controls", "coaching-calls")
        history = page.locator("#coaching-calls")
        history_links = _call_title_links(history.get_by_role("list"), rep["calls"])
        compact_calls = min(len(skill_calls), 3 if journey.width == 390 else 8)
        progress_action.scroll_into_view_if_needed()
        journey.snapshot("rep-progress")
        journey.control_target(progress_action, "progress-calls")
        for step, activation in (
            ("rep-pointer-calls", "pointer"),
            ("rep-keyboard-calls", "keyboard"),
        ):
            history.get_by_role("button", name="All calls", exact=True).click()
            history.get_by_role(
                "button", name=f"Show all {len(rep['calls'])} calls", exact=True
            ).click()
            expect(history_links).to_have_count(len(rep["calls"]))
            if activation == "pointer":
                progress_action.click()
            else:
                progress_action.focus()
                page.keyboard.press("Enter")
            expect(history).to_be_focused()
            expect(history.get_by_role("heading").first).to_be_in_viewport()
            expect(
                history.get_by_role("button", name="On this skill", exact=True)
            ).to_have_attribute("aria-pressed", "true")
            expect(history.get_by_role("status")).to_have_text(f"{len(skill_calls)} calls")
            expect(history_links).to_have_count(compact_calls)
            for index, call in enumerate(skill_calls[:compact_calls]):
                expect(history_links.nth(index)).to_contain_text(call["call_label"])
                expect(history_links.nth(index)).to_have_attribute(
                    "href", f"/coaching?call={call['submission_id']}"
                )
            page.keyboard.press("Tab")
            assert history.evaluate("el => el.contains(document.activeElement)"), (
                "Next Tab left the skill-call list after landing"
            )
            journey.snapshot(step)
            journey.unclipped_text(history)
        journey.observations[-1]["progress_calls"] = {
            "saved_skill_call_count": len(skill_calls),
            "compact_count": compact_calls,
            "pointer_and_enter_focus_calls": True,
            "expanded_all_calls_reset": True,
            "source_names_destinations_preserved": True,
            "product_destinations_opened": False,
        }


@pytest.mark.parametrize("kind", ["review", "sandbox"])
def test_fixture_coaching_call_search(
    browser: Browser, viewport: tuple[int, str], kind: str
) -> None:
    """Find retained calls without losing their saved skill, state or destination."""
    if os.environ.get("WB_MODE", "fixture") != "fixture":
        pytest.skip("Call-name search checks use the fictional dev fixture")
    filename, key = ("sandbox-team.json", "rep") if kind == "sandbox" else ("sandbox.json", "me")
    payload = json.loads(
        (
            Path(__file__).resolve().parents[3]
            / "apps/sales-xray-web/app/review-fixture/coaching"
            / filename
        ).read_text()
    )[key]
    calls = payload["calls"]
    records = {point["submission_id"]: point["state"] for point in payload["progress"]}
    skill_calls = [
        call
        for call in calls
        if call["state"] == "ready"
        and call["submission_id"] in records
        and records[call["submission_id"]] != "not_covered"
    ]
    target = skill_calls[-1]
    point_labels = {"suggested": "Needed work", "no_suggestion": "Skill used, nothing to fix"}
    with _journey(browser, viewport, f"coaching-call-search-{kind}") as journey:
        page = journey.page
        mutation_requests: list[str] = []

        def observe_read(route: Route) -> None:
            if route.request.method not in {"GET", "HEAD", "OPTIONS"}:
                mutation_requests.append(route.request.method)
                route.abort("blockedbyclient")
            else:
                route.continue_()

        page.route("**/v1/**", observe_read)
        journey.open(f"/review-fixture/coaching?data={kind}&view=me")
        history = page.locator("#coaching-calls")
        search = history.get_by_role("searchbox", name="Find a call", exact=True)
        all_calls = history.get_by_role("button", name="All calls", exact=True)
        on_skill = history.get_by_role("button", name="On this skill", exact=True)
        clear = history.get_by_role("button", name="Clear search", exact=True)
        list_name = "Their recent calls" if kind == "sandbox" else "Your recent calls"
        call_list = history.get_by_role("list", name=list_name, exact=True)
        compact_count = 3 if journey.width == 390 else 8

        def assert_calls(expected: list[dict[str, object]], *, skill: bool = False) -> None:
            count = len(expected)
            expect(history.get_by_role("status")).to_have_text(
                f"{count} call{'s' if count != 1 else ''}"
            )
            if not expected:
                expect(history.get_by_text("No matching calls", exact=True)).to_be_visible()
                expect(history.get_by_role("link")).to_have_count(0)
                expect(
                    history.get_by_role("button", name=re.compile(r"^Show (all|fewer)"))
                ).to_have_count(0)
                return
            # Inspect retained hidden rows too; screenshots separately check the compact list.
            links = _call_title_links(call_list, calls, include_hidden=True)
            expect(links).to_have_count(count)
            for index, call in enumerate(expected):
                expect(links.nth(index)).to_have_text(str(call["call_label"]))
                href = (
                    f"/coaching?call={call['submission_id']}"
                    if call["state"] == "ready"
                    else f"/analysis/calls/{call['submission_id']}"
                )
                expect(links.nth(index)).to_have_attribute("href", href)
                row = call_list.get_by_role("listitem", include_hidden=True).nth(index)
                if skill:
                    expect(row).to_contain_text(point_labels[records[call["submission_id"]]])
                elif call["state"] == "pending":
                    expect(row).to_contain_text("Analysing…")
                reports = row.get_by_role(
                    "link", name=re.compile(r"^Open Report for "), include_hidden=True
                )
                if call["state"] == "ready":
                    expect(reports).to_have_count(1)
                    expect(reports).to_have_attribute(
                        "aria-label", f"Open Report for {call['call_label']}"
                    )
                    expect(reports).to_have_attribute(
                        "href", f"/analysis/calls/{call['submission_id']}"
                    )
                else:
                    expect(reports).to_have_count(0)

        assert_calls(calls)
        expect(search).to_have_attribute(
            "aria-controls", call_list.locator("..").get_attribute("id")
        )
        if len(calls) > compact_count:
            history.get_by_role("button", name=f"Show all {len(calls)} calls", exact=True).click()
            expect(_call_title_links(call_list, calls)).to_have_count(len(calls))
        query = f"  {target['call_label'].swapcase()}  "
        search.fill(query)
        matches = [call for call in calls if call["call_label"] == target["call_label"]]
        assert_calls(matches)
        expect(search).to_be_focused()
        expect(call_list.locator("..")).not_to_have_attribute("data-expanded", "")
        expect(_call_title_links(call_list, calls)).to_have_count(len(matches))
        # A person's name can match several calls, including calls beyond the folded rows.
        name = target["call_label"].split("·")[1].strip()
        query = f"  {name.swapcase()}  "
        matches = [call for call in calls if name.casefold() in call["call_label"].casefold()]
        assert len(matches) > 1, "Fictional name search needs several retained calls"
        search.fill(query)
        assert_calls(matches)
        history.scroll_into_view_if_needed()
        journey.snapshot("named-match")
        journey.unclipped_text(history)
        journey.control_target(search, "find-call")
        journey.control_target(clear, "clear-search")
        journey.row_link_target(_call_title_links(call_list, calls).first, "matched-call")
        report = call_list.get_by_role(
            "link", name=f"Open Report for {matches[0]['call_label']}", exact=True
        )
        journey.control_target(report, "matched-report")
        _call_title_links(call_list, calls).first.focus()
        page.keyboard.press("Tab")
        expect(report).to_be_focused()

        on_skill.click()
        expect(search).to_have_value(query)
        assert_calls([call for call in skill_calls if call in matches], skill=True)
        search.fill("no such fictional call")
        assert_calls([])
        search.scroll_into_view_if_needed()
        journey.snapshot("no-match")
        journey.unclipped_text(history)
        for keyboard in (False, True):
            if keyboard:
                search.fill("no such fictional call")
                clear.focus()
                page.keyboard.press("Enter")
            else:
                clear.click()
            expect(search).to_have_value("")
            expect(search).to_be_focused()
            expect(on_skill).to_have_attribute("aria-pressed", "true")
            assert_calls(skill_calls, skill=True)
        journey.snapshot("cleared-skill")
        journey.unclipped_text(history)
        all_calls.click()
        assert_calls(calls)
        # A pending source call keeps its original status/route and is absent on this skill.
        pending = next((call for call in calls if call["state"] == "pending"), None)
        if pending:
            search.fill(pending["call_label"])
            assert_calls([pending])
            on_skill.click()
            assert_calls([])
            clear.click()
        progress_action = page.get_by_role("button", name="See calls on this skill", exact=True)
        for keyboard in (False, True):
            all_calls.click()
            search.fill("no such fictional call")
            assert_calls([])
            if keyboard:
                progress_action.focus()
                page.keyboard.press("Enter")
            else:
                progress_action.click()
            expect(search).to_have_value("")
            expect(on_skill).to_have_attribute("aria-pressed", "true")
            expect(history).to_be_focused()
            expect(history.get_by_role("heading").first).to_be_in_viewport()
            assert_calls(skill_calls, skill=True)
            expect(_call_title_links(call_list, calls)).to_have_count(
                min(len(skill_calls), compact_count)
            )
            page.keyboard.press("Tab")
            expect(search).to_be_focused()
        journey.snapshot("progress-reset")
        journey.unclipped_text(history)
        expect(page).to_have_url(re.compile(rf"/review-fixture/coaching\?data={kind}&view=me$"))
        journey.observations[-1]["call_search"] = {
            "source_call_count": len(calls),
            "saved_skill_call_count": len(skill_calls),
            "trimmed_mixed_case_match": True,
            "partial_name_match_count": len(matches),
            "expanded_history_reset": True,
            "search_and_skill_combined": True,
            "pointer_and_enter_clear_with_search_focus": True,
            "pending_state_and_route_checked": pending is not None,
            "pointer_and_enter_progress_reset_search": True,
            "source_names_states_destinations_preserved": True,
            "ready_report_destinations_and_keyboard_order_checked": True,
            "api_mutations": len(mutation_requests),
            "product_destinations_opened": False,
        }
        assert not mutation_requests, "Read-only call search attempted an API mutation"


def test_fixture_rep_calls_reset(browser: Browser, viewport: tuple[int, str]) -> None:
    """See calls restores the rep's full history after a conflicting search/filter."""
    if os.environ.get("WB_MODE", "fixture") != "fixture":
        pytest.skip("Rep call-reset checks use the fictional dev fixture")
    payload = json.loads(
        (
            Path(__file__).resolve().parents[3]
            / "apps/sales-xray-web/app/review-fixture/coaching/sandbox-team.json"
        ).read_text()
    )["rep"]
    calls = payload["calls"]
    with _journey(browser, viewport, "rep-calls-reset") as journey:
        page = journey.page
        mutation_requests: list[str] = []

        def observe_read(route: Route) -> None:
            if route.request.method not in {"GET", "HEAD", "OPTIONS"}:
                mutation_requests.append(route.request.method)
                route.abort("blockedbyclient")
            else:
                route.continue_()

        page.route("**/v1/**", observe_read)
        journey.open("/review-fixture/coaching?data=sandbox&view=me")
        shortcuts = page.get_by_role("navigation", name="This rep’s calls", exact=True)
        jump = shortcuts.get_by_role("link", name="See calls", exact=True)
        expect(jump).to_have_attribute("href", "#coaching-calls")
        shortcuts.scroll_into_view_if_needed()
        journey.snapshot("shortcut")
        journey.control_target(jump, "see-calls")
        history = page.locator("#coaching-calls")
        search = history.get_by_role("searchbox", name="Find a call", exact=True)
        all_calls = history.get_by_role("button", name="All calls", exact=True)
        on_skill = history.get_by_role("button", name="On this skill", exact=True)
        expand = history.get_by_role("button", name=f"Show all {len(calls)} calls", exact=True)
        call_list = history.get_by_role("list", name="Their recent calls", exact=True)
        compact_count = min(len(calls), 3 if journey.width == 390 else 8)
        for step, keyboard in (("pointer-restored", False), ("keyboard-restored", True)):
            all_calls.click()
            expand.click()
            expect(_call_title_links(call_list, calls)).to_have_count(len(calls))
            on_skill.click()
            search.fill("no such fictional call")
            expect(history.get_by_role("status")).to_have_text("0 calls")
            expect(history.get_by_text("No matching calls", exact=True)).to_be_visible()
            if keyboard:
                jump.focus()
                page.keyboard.press("Enter")
            else:
                jump.click()
            expect(page).to_have_url(
                re.compile(r"/review-fixture/coaching\?data=sandbox&view=me#coaching-calls$")
            )
            expect(history).to_be_focused()
            expect(history.get_by_role("heading").first).to_be_in_viewport()
            expect(search).to_have_value("")
            expect(all_calls).to_have_attribute("aria-pressed", "true")
            expect(on_skill).to_have_attribute("aria-pressed", "false")
            expect(history.get_by_role("status")).to_have_text(f"{len(calls)} calls")
            expect(expand).to_have_attribute("aria-expanded", "false")
            expect(_call_title_links(call_list, calls)).to_have_count(compact_count)
            links = _call_title_links(call_list, calls, include_hidden=True)
            expect(links).to_have_count(len(calls))
            for index, call in enumerate(calls):
                expect(links.nth(index)).to_have_text(call["call_label"])
                expect(links.nth(index)).to_have_attribute(
                    "href", f"/coaching?call={call['submission_id']}"
                )
            page.keyboard.press("Tab")
            expect(search).to_be_focused()
            history.scroll_into_view_if_needed()
            journey.snapshot(step)
            journey.unclipped_text(history)
        journey.observations[-1]["rep_call_reset"] = {
            "source_call_count": len(calls),
            "compact_count": compact_count,
            "pointer_and_enter_restore_all_calls": True,
            "prior_search_skill_and_expansion_reset": True,
            "section_focus_then_search_tab": True,
            "source_names_destinations_preserved": True,
            "native_hash_and_query_preserved": True,
            "api_mutations": len(mutation_requests),
            "product_destinations_opened": False,
        }
        assert not mutation_requests, "Read-only rep shortcut attempted an API mutation"


def test_fixture_insights_people(browser: Browser, viewport: tuple[int, str]) -> None:
    """Reach all 65 fictional returned people and retain filter identity/focus."""
    if os.environ.get("WB_MODE", "fixture") != "fixture":
        pytest.skip("Insights expansion checks use G's fictional read-only harness")
    if (
        os.environ.get("WB_STORAGE_STATE")
        or os.environ["WB_BASE_URL"].rstrip("/") != "http://127.0.0.1:3026"
    ):
        pytest.fail(
            "Fictional Insights replies require shared dev3026 and a fresh no-session browser"
        )
    root = Path(__file__).resolve().parents[3]
    fixture = json.loads(
        (root / "apps/sales-xray-web/app/review-fixture/insights/sandbox.json").read_text()
    )
    # Exact 65-person source construction from G's existing populated dev harness.
    base_people = fixture["overview"]["people"]
    people = [
        {
            **base_people[index % len(base_people)],
            "key": f"fictional-person-{index + 1}",
            "name": f"Fictional rep {index + 1}",
        }
        for index in range(65)
    ]
    overview = {
        **fixture["overview"],
        "totals": {**fixture["overview"]["totals"], "people": len(people)},
        "people": people,
        "pending": 0,
        "facets": {**fixture["overview"]["facets"], "people": people},
    }
    endpoint = "/v1/conversation/acquisition/insights"
    with _journey(browser, viewport, "insights-people") as journey:
        page = journey.page
        reads: list[str] = []
        mutations: list[str] = []

        def fictional_read(route: Route) -> None:
            request = route.request
            if request.method not in {"GET", "HEAD"}:
                mutations.append(request.method)
                route.abort("blockedbyclient")
                return
            url = urlsplit(request.url)
            reads.append(url.path)
            if url.path == endpoint:
                reply = {"status": 200, "body": overview}
            elif url.path == endpoint + "/calls":
                reply = {"status": 200, "body": fixture["calls"]}
            else:
                reply = _fictional_api_reply(request.method, url.path, url.query)
            route.fulfill(
                status=reply["status"],
                content_type="application/json",
                body=json.dumps(reply["body"]),
            )

        journey.context.route("**/v1/**", fictional_read)
        journey.context.add_init_script(
            "localStorage.setItem("
            "'sx.guide.off:00000000-0000-4000-8000-000000000001:first-call', '1');"
        )
        journey.open("/organisation/insights?view=people")
        expect(page.get_by_text("Synthetic sandbox data", exact=True)).to_be_visible()
        surface = page.get_by_role(
            "list" if journey.width == 390 else "table", name="People", exact=True
        )
        names = surface.locator(
            "article button" if journey.width == 390 else "tbody td:first-child button"
        )
        more = page.get_by_role("button", name="Show more", exact=True)
        fewer = page.get_by_role("button", name="Show fewer", exact=True)
        count = page.get_by_role("status").filter(
            has_text=re.compile(r"^Showing \d+ of 65 people$")
        )
        expect(names).to_have_text([person["name"] for person in people[:50]])
        expect(surface.get_by_role("link", name=re.compile(r"^Open .+’s profile$"))).to_have_count(
            0
        )
        expect(count).to_have_text("Showing 50 of 65 people")
        expect(more).to_have_attribute("aria-expanded", "false")
        more.scroll_into_view_if_needed()
        journey.snapshot("compact")
        journey.control_target(more, "show-people")
        reads_before = len(reads)
        more.click()
        expect(names).to_have_text([person["name"] for person in people])
        expect(surface.get_by_role("link", name=re.compile(r"^Open .+’s profile$"))).to_have_count(
            0
        )
        expect(count).to_have_text("Showing 65 of 65 people")
        expect(fewer).to_have_attribute("aria-expanded", "true")
        expect(names.last).to_have_text(people[-1]["name"])
        names.last.scroll_into_view_if_needed()
        journey.snapshot("last-returned")
        journey.control_target(names.last, "last-person")
        journey.control_target(fewer, "show-fewer-people")
        # Exercise hidden-tail focus recovery, as in G's existing harness.
        names.last.focus()
        fewer.evaluate("button => button.click()")
        expect(more).to_be_focused()
        expect(names).to_have_count(50)
        expect(count).to_have_text("Showing 50 of 65 people")
        assert len(reads) == reads_before, "Disclosure unexpectedly fetched another API page"
        more.scroll_into_view_if_needed()
        journey.snapshot("collapsed-focus")
        more.focus()
        page.keyboard.press("Enter")
        expect(names).to_have_count(65)
        last = people[-1]
        with page.expect_response(
            lambda response: (
                urlsplit(response.url).path == endpoint
                and parse_qs(urlsplit(response.url).query).get("person") == [last["key"]]
            )
        ) as filtered:
            names.last.click()
        assert filtered.value.status == 200
        expect(page.get_by_role("combobox", name="Person", exact=True)).to_have_value(last["key"])
        address = urlsplit(page.url)
        assert address.path == "/organisation/insights"
        assert parse_qs(address.query).get("person") == [last["key"]]
        assert parse_qs(address.query).get("view") == ["people"]
        page.get_by_role("group", name="Filters", exact=True).scroll_into_view_if_needed()
        journey.snapshot("last-person-filter")
        journey.observations[-1]["fictional_insights"] = {
            "source": "G19eca7b7's existing 65-person fictional API harness",
            "returned_people": len(people),
            "compact_people": 50,
            "source_order_and_last_person_preserved": True,
            "disclosure_fetches": 0,
            "collapse_restores_control_focus": True,
            "last_source_key_in_address_api_and_selector": True,
            "api_mutations": len(mutations),
            "authenticated_hosted_acceptance": False,
        }
        assert not mutations, "Fictional Insights attempted an API mutation"


def test_fixture_organisation_people_search(browser: Browser, viewport: tuple[int, str]) -> None:
    """Search all returned active, quiet and test people without changing their figures."""
    if os.environ.get("WB_MODE", "fixture") != "fixture":
        pytest.skip("Organisation search uses A's existing fictional read-only harness")
    if (
        os.environ.get("WB_STORAGE_STATE")
        or os.environ["WB_BASE_URL"].rstrip("/") != "http://127.0.0.1:3026"
    ):
        pytest.fail("Fictional Organisation replies require shared dev3026 with no session")
    active_id = "00000000-0000-4000-8000-000000000001"
    quiet_id = "00000000-0000-4000-8000-000000000006"
    with _journey(browser, viewport, "organisation-people-search") as journey:
        page = journey.page
        mutations: list[str] = []
        reads: list[str] = []

        def fictional_read(route: Route) -> None:
            request = route.request
            if request.method not in {"GET", "HEAD"}:
                mutations.append(request.method)
                route.abort("blockedbyclient")
                return
            url = urlsplit(request.url)
            reads.append(url.path)
            reply = _fictional_api_reply(request.method, url.path, url.query)
            if url.path == "/v1/organisation/members" and reply["status"] == 200:
                body = reply["body"]
                reply["body"] = {
                    "members": [
                        *body["members"],
                        {
                            **body["members"][0],
                            "person_id": quiet_id,
                            "name": "Asha Menon",
                            "email": "asha-desk@brightline.example.in",
                            "role": "member",
                            "calls_30d": 0,
                            "minutes_used_30d": 0,
                        },
                    ]
                }
            if url.path == "/v1/organisation" and reply["status"] == 200:
                reply["body"] = {**reply["body"], "member_count": 6}
            route.fulfill(
                status=reply["status"],
                content_type="application/json",
                body=json.dumps(reply["body"]),
            )

        journey.context.route("**/v1/**", fictional_read)
        journey.context.add_init_script(
            "localStorage.setItem("
            "'sx.guide.off:00000000-0000-4000-8000-000000000001:first-call', '1');"
        )
        journey.open("/organisation")
        people = page.locator('[aria-labelledby="org-people"]')
        search = people.get_by_role("searchbox", name="Search people", exact=True)
        clear = people.get_by_role("button", name="Clear search", exact=True)
        rows = people.locator("li")
        expect(people.get_by_role("status")).to_have_text("Showing 4 of 6 people")
        expect(rows).to_have_count(4)
        figures = page.locator("[data-organisation-view] dl").first.inner_text()
        team_calls = page.locator('[aria-label="Team calls"]').inner_text()

        def row_values() -> list[object]:
            return rows.evaluate_all(
                """els => els.map(el => ({
                  href: el.querySelector('a').getAttribute('href'),
                  text: el.innerText, quiet: el.hasAttribute('data-quiet')
                }))"""
            )

        baseline = row_values()
        reads_before = len(reads)
        search.fill("  aShA  ")
        expect(rows).to_have_count(2)
        expect(people.get_by_role("status")).to_have_text("Matches: 2 of 6 people")
        for index, person_id in enumerate((active_id, quiet_id)):
            expect(rows.nth(index).get_by_role("link")).to_have_attribute(
                "href", f"/organisation/people/{person_id}"
            )
        expect(rows.first).to_contain_text("3 calls")
        expect(rows.last).to_contain_text("No calls")
        expect(rows.last).to_have_attribute("data-quiet", "")
        expect(rows.first).to_contain_text("asha@brightline.example.in")
        expect(rows.last).to_contain_text("asha-desk@brightline.example.in")
        people.scroll_into_view_if_needed()
        journey.snapshot("same-name")
        for control, label in (
            (search, "search-people"),
            (clear, "clear-people"),
            (rows.last.get_by_role("link"), "quiet-person"),
        ):
            journey.control_target(control, label)
        search.fill("Quinn")
        expect(rows).to_have_count(1)
        expect(rows.first).to_contain_text("Quinn Fixture")
        expect(rows.first).to_contain_text("No calls")
        expect(rows.first).to_have_attribute("data-quiet", "")
        expect(rows.first).to_contain_text("Test")
        test_person_href = "/organisation/people/00000000-0000-4000-8000-000000000005"
        expect(rows.first.get_by_role("link")).to_have_attribute("href", test_person_href)
        journey.snapshot("folded-test-person")
        search.fill("brightline.example.in")
        expect(rows).to_have_count(0)
        expect(people.get_by_role("status")).to_have_text("Matches: 0 of 6 people")
        expect(people.get_by_text("No people match this name.", exact=True)).to_be_visible()
        journey.snapshot("no-name-match")
        clear.focus()
        page.keyboard.press("Enter")
        expect(search).to_be_focused()
        expect(search).to_have_value("")
        assert row_values() == baseline
        expand = people.get_by_role(
            "button", name="2 more people with no calls or test accounts", exact=True
        )
        expect(expand).to_have_attribute("aria-expanded", "false")
        expand.click()
        expect(rows).to_have_count(6)
        expanded = row_values()
        search.fill("Quinn")
        expect(rows.first.get_by_role("link")).to_have_attribute("href", test_person_href)
        clear.click()
        expect(search).to_be_focused()
        assert row_values() == expanded
        expect(
            people.get_by_role("button", name="Show only people with calls", exact=True)
        ).to_have_attribute("aria-expanded", "true")
        assert page.locator("[data-organisation-view] dl").first.inner_text() == figures
        assert page.locator('[aria-label="Team calls"]').inner_text() == team_calls
        assert len(reads) == reads_before, "Local name search unexpectedly fetched new data"
        people.scroll_into_view_if_needed()
        journey.snapshot("restored-expanded")
        journey.observations[-1]["fictional_organisation_search"] = {
            "source": "A8c290b4f's existing six-person fictional API harness",
            "same_name_active_and_quiet_people_distinct": True,
            "folded_test_name_reachable": True,
            "names_only_empty_result": True,
            "source_order_identity_figures_routes_preserved": True,
            "clear_restores_focus_and_prior_disclosure": True,
            "extra_reads": 0,
            "api_mutations": len(mutations),
            "profile_destinations_opened": False,
            "authenticated_hosted_acceptance": False,
        }
        assert not mutations, "Fictional Organisation search attempted an API mutation"


def test_fixture_team_current_areas(browser: Browser, viewport: tuple[int, str]) -> None:
    """Current Delivery reps stay filterable without adding a historic total."""
    if os.environ.get("WB_MODE", "fixture") != "fixture":
        pytest.skip("Current-area checks use D's existing fictional example")
    data = json.loads(
        (
            Path(__file__).resolve().parents[3]
            / "apps/sales-xray-web/app/review-fixture/coaching/sandbox-team.json"
        ).read_text()
    )["team"]
    missing_skill = data["reps"][0]["skill_id"]
    suggestions = [row for row in data["suggestions"] if row["skill_id"] != missing_skill]
    matching = [rep for rep in data["reps"] if rep["skill_id"] == missing_skill]
    target = matching[-1]
    options = list(
        dict.fromkeys(
            [row["skill_id"] for row in suggestions] + [rep["skill_id"] for rep in data["reps"]]
        )
    )
    with _journey(browser, viewport, "team-current-areas") as journey:
        page = journey.page
        mutations: list[str] = []

        def observe_read(route: Route) -> None:
            if route.request.method not in {"GET", "HEAD", "OPTIONS"}:
                mutations.append(route.request.method)
                route.abort("blockedbyclient")
            else:
                route.continue_()

        page.route("**/v1/**", observe_read)
        journey.open("/review-fixture/coaching?data=sandbox&view=team&example=current-focus-areas")
        team = page.get_by_role("region", name=re.compile(r"^Who needs help with what"))
        search = team.get_by_role("searchbox", name="Find a rep", exact=True)
        area = team.get_by_role("combobox", name="Coaching area", exact=True)
        reset = team.get_by_role("button", name="Clear filters", exact=True)
        links = team.get_by_role(
            "list", name="Reps and their current focus", exact=True
        ).get_by_role("link")
        totals = page.get_by_role("list", name="Coaching areas", exact=True)
        historical = totals.inner_text()
        assert area.locator("option").evaluate_all("els => els.map(el => el.value)") == [
            "all",
            *options,
        ]
        expect(totals.get_by_role("listitem")).to_have_count(len(suggestions))
        removed = next(row for row in data["suggestions"] if row["skill_id"] == missing_skill)
        expect(
            page.get_by_role("button", name=f"Find reps working on {removed['label']}", exact=True)
        ).to_have_count(0)
        expect(area.locator(f'option[value="{missing_skill}"]')).to_have_text("Delivery")

        def assert_reps(expected: list[dict[str, object]]) -> None:
            expect(links).to_have_count(min(len(expected), 8))
            for index, rep in enumerate(expected[:8]):
                expect(links.nth(index)).to_contain_text(str(rep["name"]))
                expect(links.nth(index)).to_contain_text(str(rep["focus_label"]))
                expect(links.nth(index)).to_have_attribute(
                    "href", f"/coaching?person={rep['person_id']}"
                )

        area.select_option(missing_skill)
        assert_reps(matching)
        expect(team.get_by_role("status")).to_have_text(f"{len(matching)} reps")
        team.scroll_into_view_if_needed()
        journey.snapshot("delivery-reps")
        journey.control_target(area, "current-area")
        search.fill(f"  {target['name'].swapcase()}  ")
        assert_reps([target])
        expect(team.get_by_role("status")).to_have_text("1 rep")
        journey.snapshot("named-current-rep")
        for control, label in (
            (search, "rep-search"),
            (links.first, "matched-rep"),
            (reset, "reset-matching"),
        ):
            journey.control_target(control, label)
        reset.focus()
        page.keyboard.press("Enter")
        expect(search).to_have_value("")
        expect(search).to_be_focused()
        expect(area).to_have_value("all")
        assert_reps(data["reps"])
        assert totals.inner_text() == historical, (
            "Current focus filtering changed historical counters"
        )
        journey.snapshot("reset-current-filter")
        journey.observations[-1]["current_area"] = {
            "current_reps_without_historic_total": len(matching),
            "source_names_focuses_destinations_preserved": True,
            "historical_counters_unchanged": True,
            "combined_name_filter_and_enter_reset_focus": True,
            "api_mutations": len(mutations),
            "product_destinations_opened": False,
        }
        assert not mutations, "Current-focus filter attempted an API mutation"


@pytest.mark.parametrize("kind", ["review", "sandbox"])
def test_fixture_coaching_focus_moments(
    browser: Browser, viewport: tuple[int, str], kind: str
) -> None:
    """Current focus reaches the original call evidence by pointer and keyboard."""
    if os.environ.get("WB_MODE", "fixture") != "fixture":
        pytest.skip("Focus-to-moment checks use the fictional dev fixture")
    filename, key = ("sandbox-team.json", "rep") if kind == "sandbox" else ("sandbox.json", "me")
    payload = json.loads(
        (
            Path(__file__).resolve().parents[3]
            / "apps/sales-xray-web/app/review-fixture/coaching"
            / filename
        ).read_text()
    )[key]
    evidence = payload["evidence"]
    with _journey(browser, viewport, f"coaching-focus-{kind}") as journey:
        page = journey.page
        media_requests: list[str] = []
        mutation_requests: list[str] = []

        def observe_read(route: Route) -> None:
            if route.request.method not in {"GET", "HEAD", "OPTIONS"}:
                mutation_requests.append(route.request.method)
                route.abort("blockedbyclient")
            else:
                route.continue_()

        page.route("**/v1/**", observe_read)
        page.on(
            "request",
            lambda request: (
                media_requests.append("media") if request.resource_type == "media" else None
            ),
        )
        journey.open(f"/review-fixture/coaching?data={kind}&view=me")
        hero = page.locator("#coaching-focus")
        expect(hero).to_contain_text(payload["focus"]["label"])
        jump = hero.get_by_role("link", name="See the moments", exact=True)
        expect(jump).to_have_attribute("href", "#coaching-evidence")
        jump.scroll_into_view_if_needed()
        journey.snapshot("focus")
        journey.unclipped_text(hero)
        journey.control_target(jump, "see-moments")
        jump.click()
        target = page.locator("#coaching-evidence")
        expect(target).to_be_focused()
        caption = target.locator("p").first
        expect(caption).to_contain_text(
            "From their calls" if kind == "sandbox" else "From your calls"
        )
        expect(caption).to_be_in_viewport()
        expected_url = re.compile(
            rf"/review-fixture/coaching\?data={kind}&view=me#coaching-evidence$"
        )
        expect(page).to_have_url(expected_url)
        moments = target.get_by_role(
            "list",
            name="Moments from their calls" if kind == "sandbox" else "Moments from your calls",
            exact=True,
        )
        rows = moments.get_by_role("listitem")
        compact_count = 1 if journey.width == 390 else 2
        expect(rows).to_have_count(compact_count)
        original = evidence[0]
        first = rows.first
        expect(first.locator("blockquote")).to_have_text(original["quote"])
        start, end = (int(original[field]) // 1000 for field in ("start_ms", "end_ms"))
        span = f"{start // 60}:{start % 60:02d}–{end // 60}:{end % 60:02d}"
        expect(first).to_contain_text(span)
        call_link = first.get_by_role("link", name=original["call_label"], exact=True)
        expect(call_link).to_have_attribute("href", f"/coaching?call={original['submission_id']}")
        journey.snapshot("pointer-landed")
        journey.unclipped_text(call_link.locator(".."))
        journey.control_target(call_link, "supporting-call")
        jump.focus()
        expect(jump).to_be_focused()
        page.keyboard.press("Enter")
        expect(target).to_be_focused()
        expect(caption).to_be_in_viewport()
        expect(page).to_have_url(expected_url)
        page.keyboard.press("Tab")
        assert target.evaluate("el => el.contains(document.activeElement)"), (
            "Keyboard navigation left the supporting moments after landing"
        )
        journey.snapshot("keyboard-landed")
        assert not mutation_requests, "Reading the focus attempted an API mutation"
        assert not media_requests, "Reading the focus requested media"
        assert page.locator("audio,video").count() == 0
        journey.observations[-1]["focus_moments"] = {
            "source_count": len(evidence),
            "compact_count": compact_count,
            "pointer_and_keyboard_landed": True,
            "next_tab_inside_evidence": True,
            "first_quote_time_destination_preserved": True,
            "product_destinations_opened": False,
            "playback_tested": False,
        }


def test_fixture_coaching_moment_fold(browser: Browser, viewport: tuple[int, str]) -> None:
    """Supporting moments remain readable and retain their source after shortening."""
    if os.environ.get("WB_MODE", "fixture") != "fixture":
        pytest.skip("Supporting-moment checks use the fictional dev fixture")
    payload = json.loads(
        (
            Path(__file__).resolve().parents[3]
            / "apps/sales-xray-web/app/review-fixture/coaching/sandbox-team.json"
        ).read_text()
    )
    evidence = payload["rep"]["evidence"]
    with _journey(browser, viewport, "coaching-moments") as journey:
        page = journey.page
        media_requests: list[str] = []
        page.on(
            "request",
            lambda request: (
                media_requests.append("media") if request.resource_type == "media" else None
            ),
        )
        journey.open("/review-fixture/coaching?data=sandbox&view=me")
        section = page.locator("#coaching-why")
        moments = section.get_by_role("list", name="Moments from their calls", exact=True)
        rows = moments.get_by_role("listitem")
        compact_count = 1 if journey.width == 390 else 2
        expect(rows).to_have_count(compact_count)
        expand = section.get_by_role("button", name=f"Show all {len(evidence)} moments", exact=True)
        expect(expand).to_have_attribute("aria-expanded", "false")
        expect(expand).to_have_attribute("aria-controls", moments.get_attribute("id"))
        section.get_by_role("heading").first.scroll_into_view_if_needed()
        journey.snapshot("compact")
        journey.control_target(expand, "expand-moments")
        expand.click()
        expect(rows).to_have_count(len(evidence))
        for index, original in enumerate(evidence):
            row = rows.nth(index)
            expect(row.locator("blockquote")).to_have_text(original["quote"])
            start, end = (int(original[key]) // 1000 for key in ("start_ms", "end_ms"))
            span = f"{start // 60}:{start % 60:02d}–{end // 60}:{end % 60:02d}"
            expect(row).to_contain_text(span)
            call_link = row.get_by_role("link", name=original["call_label"], exact=True)
            expect(call_link).to_have_attribute(
                "href", f"/coaching?call={original['submission_id']}"
            )
        fewer = section.get_by_role("button", name="Show fewer moments", exact=True)
        expect(fewer).to_have_attribute("aria-expanded", "true")
        journey.control_target(fewer, "shorten-moments")
        journey.snapshot("expanded")
        fewer.click()
        expect(rows).to_have_count(compact_count)
        expect(expand).to_have_attribute("aria-expanded", "false")
        expect(moments).to_be_focused()
        expect(moments).to_be_in_viewport()
        assert moments.locator("blockquote").all_text_contents() == [
            original["quote"] for original in evidence
        ]
        journey.snapshot("shortened")
        assert page.locator("audio,video").count() == 0
        assert not media_requests, "Reading supporting moments requested media"
        journey.observations[-1]["supporting_moments"] = {
            "source_count": len(evidence),
            "compact_count": compact_count,
            "quotes_times_destinations_preserved": True,
            "focus_returned": True,
            "product_destinations_opened": False,
            "playback_tested": False,
        }


def test_fixture_coaching_quote_fold(browser: Browser, viewport: tuple[int, str]) -> None:
    if os.environ.get("WB_MODE", "fixture") != "fixture":
        pytest.skip("Long-quote reproduction is dev fixture coverage only")
    source = json.loads(
        (
            Path(__file__).resolve().parents[3]
            / "apps/sales-xray-web/app/review-fixture/coaching/long-quote.json"
        ).read_text()
    )
    evidence = source["call"]["evidence"][0]
    quote = evidence["quote"]
    assert source["synthetic"] is True
    assert len(quote) == 1232
    assert (evidence["start_ms"], evidence["end_ms"]) == (130930, 217313)
    with _journey(browser, viewport, "coaching-quote") as journey:
        media_requests: list[str] = []
        page = journey.page
        page.on(
            "request",
            lambda request: (
                media_requests.append("media") if request.resource_type == "media" else None
            ),
        )
        journey.open("/review-fixture/coaching?data=sandbox&example=long-quote")
        words = page.locator("blockquote").filter(has_text=quote)
        expect(words).to_have_count(1)
        expect(words).to_have_text(quote)
        control = page.get_by_role("button", name="Read full quote", exact=True)
        expect(control).to_have_count(1)
        expect(control).to_have_attribute("aria-controls", words.get_attribute("id"))
        folded_height = words.bounding_box()["height"]
        for state, opened in (("folded", False), ("expanded", True), ("refolded", False)):
            if opened:
                control.click()
                control = page.get_by_role("button", name="Show less", exact=True)
            elif state == "refolded":
                control.click()
                control = page.get_by_role("button", name="Read full quote", exact=True)
            expect(control).to_have_attribute("aria-expanded", str(opened).lower())
            assert words.evaluate("el => el.hasAttribute('data-folded')") is not opened
            expect(words).to_have_text(quote)
            expect(words.locator("..")).to_contain_text("2:10–3:37")
            assert (
                page.locator("[data-coaching-pillar]").evaluate_all(
                    """(els, quote) => els.map(el => el.textContent).join(' ')
                      .split(quote).length - 1""",
                    quote,
                )
                == 1
            ), "The source quote is repeated as an observation"
            if opened:
                assert words.bounding_box()["height"] > folded_height
            control.scroll_into_view_if_needed()
            expect(control).to_be_in_viewport(ratio=1)
            bounds = control.bounding_box()
            minimum = 44 if journey.width == 390 else 32
            assert min(bounds["width"], bounds["height"]) >= minimum - 0.01
            assert control.evaluate(
                """el => {const r = el.getBoundingClientRect();
                return el.contains(document.elementFromPoint(
                  r.x + r.width / 2, r.y + r.height / 2));}"""
            ), "Quote disclosure is covered by another control"
            journey.snapshot(state)
            journey.observations[-1]["quote_control"] = {
                "width": bounds["width"],
                "height": bounds["height"],
                "minimum": minimum,
                "source_characters": len(quote),
                "start_ms": evidence["start_ms"],
                "end_ms": evidence["end_ms"],
                "expanded": opened,
            }
            assert page.locator("audio,video").count() == 0
            assert not media_requests, "Reading the quote started a media request"


def test_fixture_document_print(browser: Browser, viewport: tuple[int, str]) -> None:
    if os.environ.get("WB_MODE", "fixture") != "fixture":
        pytest.skip("Independent print repair readback is dev fixture coverage only")
    with _journey(browser, viewport, "document-print") as journey:
        page = journey.page
        journey.open("/review-fixture/report/story")
        expect(page.locator('[data-report-modes][data-view="story"]')).to_be_visible()
        _switch_report_view(page, "Document view")
        preview = _document_preview(page)
        expect(preview.locator("section[data-document-section]")).to_have_count(6)
        page.locator("[data-document-export]").evaluate("el => el.scrollIntoView({block: 'start'})")
        journey.snapshot("screen")
        journey.document_controls()
        page.emulate_media(media="print")
        page.set_viewport_size({"width": 794, "height": 1123})
        preview.evaluate("el => el.scrollIntoView({block: 'start'})")
        metrics = page.evaluate(
            """() => {
              const search = document.querySelector('input[aria-label="Search calls"]')
                ?.closest('form');
              const account = document.querySelector('button[aria-label="Open AC account menu"]');
              const controls = [search, account].filter(Boolean).map(el => {
                const style = getComputedStyle(el);
                return {visibility: style.visibility, transition: style.transitionDuration,
                  animation: style.animationName};
              });
              const sheet = document.querySelector('[data-document-export] article');
              const bounds = sheet.getBoundingClientRect();
              return {controls, headings: sheet.querySelectorAll('h3').length,
                layout_width: innerWidth,
                visual_width: visualViewport?.width ?? innerWidth,
                visual_offset: visualViewport?.offsetLeft ?? 0,
                sheet_left: bounds.left, sheet_right: bounds.right,
                overflow: Math.max(document.documentElement.scrollWidth - innerWidth,
                  sheet.scrollWidth - sheet.clientWidth)};
            }"""
        )
        assert len(metrics["controls"]) == 2, "Print shell controls were not checked"
        assert all(
            control["visibility"] == "hidden"
            and all(
                float(value.strip().removesuffix("s")) == 0
                for value in control["transition"].split(",")
            )
            and control["animation"] == "none"
            for control in metrics["controls"]
        ), "Hidden print shell controls can still paint during motion"
        assert metrics["headings"] == 6
        assert metrics["overflow"] <= 1
        facts = preview.locator("header dl")
        expect(facts).to_have_count(1)
        expect(facts).to_contain_text("25:08")
        expect(facts).to_contain_text("Arjun")
        expect(facts).to_contain_text("Amit Sharma")
        shot = journey.directory / f"document-print-a4-{journey.width}-{journey.theme}.png"
        page.screenshot(path=str(shot))
        pdf = journey.directory / f"document-print-{journey.width}-{journey.theme}.pdf"
        page.pdf(path=str(pdf), prefer_css_page_size=True, print_background=True)
        assert pdf.read_bytes().startswith(b"%PDF-")
        journey.observations.append(
            {"step": "print", "screenshot": str(shot), "pdf": str(pdf), "print_metrics": metrics}
        )
