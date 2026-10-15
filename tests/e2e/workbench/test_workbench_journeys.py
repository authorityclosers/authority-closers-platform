"""Opt-in browser acceptance on an existing dev/staging server; never starts one."""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import wave
from collections.abc import Iterator
from contextlib import contextmanager, suppress
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from html import unescape
from http.cookiejar import HTTPONLY_ATTR, LoadError, MozillaCookieJar
from io import BytesIO
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
                const namedCellAvatar = el.matches('i[aria-hidden="true"]') &&
                  el.parentElement?.getAttribute('role') === 'cell' &&
                  el.nextElementSibling?.tagName === 'SPAN';
                if (el.matches('[aria-hidden="true"][class*="avatar"]') ||
                    namedCellAvatar) continue;
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


@pytest.mark.parametrize("scene", ("call", "rep-call", "report"))
def test_fixture_call_focus_moments(
    browser: Browser, viewport: tuple[int, str], scene: str
) -> None:
    """Call/retained Report focus reaches original moments below sticky navigation."""
    if os.environ.get("WB_MODE", "fixture") != "fixture":
        pytest.skip("Call-to-moment navigation uses D's existing fictional surfaces")
    report = scene == "report"
    data = "sandbox" if scene == "rep-call" else "review"
    payload = None
    if not report:
        filename = "sandbox-team.json" if data == "sandbox" else "sandbox.json"
        payload = json.loads(
            (
                Path(__file__).resolve().parents[3]
                / "apps/sales-xray-web/app/review-fixture/coaching"
                / filename
            ).read_text()
        )["call"]
    with _journey(browser, viewport, f"call-focus-moments-{scene}") as journey:
        page = journey.page
        mutations: list[str] = []
        media: list[str] = []

        def observe_read(route: Route) -> None:
            request = route.request
            path = urlsplit(request.url).path
            if request.method not in {"GET", "HEAD"}:
                mutations.append(request.method)
                route.abort("blockedbyclient")
            elif re.search(r"/(source|media)/", path) or path.endswith("/source"):
                media.append("source-read")
                route.abort("blockedbyclient")
            else:
                route.continue_()

        page.route("**/v1/**", observe_read)
        page.on(
            "request",
            lambda request: media.append("media") if request.resource_type == "media" else None,
        )
        journey.open(
            "/review-fixture/report/story?call=00000000-0000-4000-8000-000000000077&view=coaching&section=call-coaching"
            if report
            else f"/review-fixture/coaching?data={data}&view=call"
        )
        if not report:
            expect(
                page.get_by_role(
                    "button",
                    name="AC Sandbox" if data == "sandbox" else "Design review",
                    exact=True,
                )
            ).to_have_attribute("aria-pressed", "true")
            expect(page.get_by_role("button", name="This call", exact=True)).to_have_attribute(
                "aria-pressed", "true"
            )
        page.evaluate("() => document.fonts.ready")
        page.wait_for_load_state("networkidle", timeout=15000)
        hero = page.locator("#report-coaching-focus" if report else "#coaching-focus")
        target_id = "report-coaching-why" if report else "coaching-why"
        target = page.locator(f"#{target_id}")
        jump = hero.get_by_role("link", name="See the moments", exact=True)
        expect(jump).to_have_attribute("href", f"#{target_id}")
        expect(jump).to_have_attribute("aria-controls", target_id)
        expect(target).to_have_attribute("tabindex", "-1")
        expect(target).to_have_attribute("aria-labelledby", f"{target_id}-heading")
        source_text = target.inner_text()
        quotes = target.locator("blockquote").all_text_contents()
        assert quotes, "No original moment quote was supplied"
        times = target.locator(
            '[aria-label^="Moment at"],button[aria-label^="Play moment"]'
        ).all_text_contents()
        if payload:
            assert quotes == [moment["quote"] for moment in payload["evidence"]]
            expect(hero).to_contain_text(payload["focus"]["label"])
            assert times == [
                f"{moment['start_ms'] // 60000}:{moment['start_ms'] // 1000 % 60:02d}"
                for moment in payload["evidence"]
            ]
        mission = page.locator("[data-active-mission]")
        mission_text = mission.inner_text()
        hero.evaluate("el => el.scrollIntoView({block: 'center', behavior: 'instant'})")
        journey.snapshot("focus-source-shortcut")
        journey.control_target(jump, "call-moments-shortcut")

        def landed() -> None:
            expect(target).to_be_focused()
            heading = target.get_by_role("heading").first
            expect(heading).to_be_in_viewport()
            assert heading.evaluate("""el => {
                const r = el.getBoundingClientRect();
                const hit = document.elementFromPoint(r.x + r.width/2,r.y + r.height/2);
                return hit === el || el.contains(hit);
            }"""), "Moment heading is covered by sticky navigation"
            location = urlsplit(page.url)
            assert location.fragment == target_id
            assert parse_qs(location.query).get("view") == ["coaching" if report else "call"]
            if report:
                assert parse_qs(location.query).get("call") == [
                    "00000000-0000-4000-8000-000000000077"
                ]
            else:
                assert parse_qs(location.query).get("data") == [data]
            assert target.inner_text() == source_text
            assert target.locator("blockquote").all_text_contents() == quotes
            assert (
                target.locator(
                    '[aria-label^="Moment at"],button[aria-label^="Play moment"]'
                ).all_text_contents()
                == times
            )
            assert mission.inner_text() == mission_text
            expect(target.locator("blockquote").first).to_be_visible()

        jump.click()
        landed()
        page.keyboard.press("Tab")
        assert target.evaluate("el => el.contains(document.activeElement)"), (
            "Next Tab left the moments"
        )
        jump.focus()
        page.keyboard.press("Enter")
        landed()
        journey.snapshot("original-moments-native-focus")
        expect(page.locator("audio[src]")).to_have_count(0)
        assert not media, "Call moment navigation fetched media or a recording source"
        assert not mutations, "Call moment navigation attempted an API mutation"
        journey.observations[-1]["fictional_call_focus_moments"] = {
            "source": "D021e7fa0/0fc46c26 existing call/retained Report authored examples",
            "original_quotes": len(quotes),
            "original_times_unchanged": True,
            "pointer_enter_focus_and_heading_actual_hit": True,
            "next_tab_inside_and_query_mission_unchanged": True,
            "shortcut_32_44px": True,
            "media_requests": len(media),
            "api_mutations": len(mutations),
            "authenticated_or_canonical_report_acceptance": False,
        }


def test_fixture_coaching_moment_ended(browser: Browser, viewport: tuple[int, str]) -> None:
    """A local silent recording can end early and replay its original saved moment."""
    if (
        os.environ.get("WB_MODE", "fixture") != "fixture"
        or os.environ["WB_BASE_URL"].rstrip("/") != "http://127.0.0.1:3026"
    ):
        pytest.skip("Native end checks use only the existing local Design review")
    payload = json.loads(
        (
            Path(__file__).resolve().parents[3]
            / "apps/sales-xray-web/app/review-fixture/coaching/sandbox.json"
        ).read_text()
    )["me"]
    evidence = payload["evidence"][0]
    start, end = evidence["start_ms"] / 1000, evidence["end_ms"] / 1000
    assert evidence["playable"] and start + 3 < end
    # Reuse D's short, silent PCM source in memory; no recording is fetched.
    with BytesIO() as output:
        with wave.open(output, "wb") as local_audio:
            local_audio.setnchannels(1)
            local_audio.setsampwidth(2)
            local_audio.setframerate(8000)
            local_audio.writeframes(b"\0\0" * round((start + 3) * 8000))
        silent_wav = output.getvalue()
    source = f"/v1/conversation/acquisition/submissions/{evidence['submission_id']}/source"
    with _journey(browser, viewport, "moment-ended") as journey:
        page = journey.page
        source_reads: list[str] = []
        unexpected_media: list[str] = []
        mutations: list[str] = []
        page.add_init_script("""(() => {
          window.__wbMomentStarts = [];
          const nativePlay = HTMLMediaElement.prototype.play;
          HTMLMediaElement.prototype.play = function () {
            window.__wbMomentStarts.push(this.currentTime);
            this.muted = true;
            return nativePlay.call(this);
          };
        })();""")

        def local_read(route: Route) -> None:
            request = route.request
            url = urlsplit(request.url)
            if request.method not in {"GET", "HEAD"}:
                mutations.append(request.method)
                route.abort("blockedbyclient")
            elif url.netloc == "127.0.0.1:3026" and url.path == source:
                source_reads.append(request.method)
                byte_range = re.fullmatch(r"bytes=(\d+)-(\d*)", request.headers.get("range", ""))
                first = int(byte_range[1]) if byte_range else 0
                last = (
                    min(int(byte_range[2]), len(silent_wav) - 1)
                    if byte_range and byte_range[2]
                    else len(silent_wav) - 1
                )
                if first > last:
                    route.fulfill(
                        status=416, headers={"Content-Range": f"bytes */{len(silent_wav)}"}
                    )
                    return
                body = silent_wav[first : last + 1]
                headers = {"Accept-Ranges": "bytes", "Content-Length": str(len(body))}
                if byte_range:
                    headers["Content-Range"] = f"bytes {first}-{last}/{len(silent_wav)}"
                route.fulfill(
                    status=206 if byte_range else 200,
                    content_type="audio/wav",
                    headers=headers,
                    body=body if request.method == "GET" else b"",
                )
            elif (
                request.resource_type == "media"
                or url.path.endswith("/source")
                or (url.path.startswith("/v1/") and "/media/" in url.path)
            ):
                unexpected_media.append("unexpected-source")
                route.abort("blockedbyclient")
            else:
                route.continue_()

        page.route("**/*", local_read)
        journey.open("/review-fixture/coaching?data=review&view=me")
        for label in ("Design review", "My coaching"):
            expect(page.get_by_role("button", name=label, exact=True)).to_have_attribute(
                "aria-pressed", "true"
            )
        page.evaluate("() => document.fonts.ready")
        page.wait_for_load_state("networkidle", timeout=15_000)
        expect(page.locator("audio,video")).to_have_count(0)
        assert not source_reads, "Reading Coaching eagerly requested the local media"
        moment = page.locator("#coaching-evidence li").first
        expect(moment.locator("blockquote")).to_have_text(evidence["quote"])
        call_link = moment.get_by_role("link", name=evidence["call_label"], exact=True)
        call_href = call_link.get_attribute("href")
        assert call_href and evidence["submission_id"] in call_href
        play = moment.get_by_role("button", name=re.compile(r"^Play moment"))
        original_time = play.get_attribute("aria-label")
        play.click()
        pause = moment.get_by_role("button", name=re.compile(r"^Pause moment"))
        expect(pause).to_be_visible()
        audio = moment.locator("audio")
        expect(audio).to_have_attribute("src", source)
        expect(play).to_be_enabled(timeout=15_000)
        assert audio.evaluate("el => el.ended"), "Play returned before native recording end"
        duration = audio.evaluate("el => el.duration")
        assert start < duration < end, "The controlled source did not end inside the saved moment"
        moment.evaluate("el => el.scrollIntoView({block: 'center', behavior: 'instant'})")
        journey.snapshot("recording-ended-replay-ready")
        journey.control_target(play, "ended-moment-play")
        expect(play).to_have_attribute("aria-label", original_time)
        play.focus()
        page.keyboard.press("Enter")
        expect(pause).to_be_visible()
        expect(pause).to_be_focused()
        expect(audio).to_have_attribute("src", source)
        assert page.evaluate("window.__wbMomentStarts") == [start, start]
        resumed_at = audio.evaluate("el => el.currentTime")
        assert start <= resumed_at < start + 1, "Replay did not begin at the saved timestamp"
        pause.click()
        expect(play).to_be_enabled()
        assert audio.evaluate("el => el.paused")
        expect(play).to_have_attribute("aria-label", original_time)
        expect(moment.locator("blockquote")).to_have_text(evidence["quote"])
        expect(call_link).to_have_attribute("href", call_href)
        expect(page.locator("[data-active-mission]")).to_have_text(payload["mission"]["behavior"])
        expect(page).to_have_url(re.compile(r"/review-fixture/coaching\?data=review&view=me$"))
        expect(moment.get_by_role("status")).to_have_count(0)
        journey.snapshot("original-timestamp-replayed-paused")
        journey.control_target(play, "replayed-moment-play")
        assert source_reads and not unexpected_media and not mutations
        assert journey.live_refreshes == 0, "Live source changed during native end/replay"
        journey.observations[-1]["fictional_native_moment_end"] = {
            "source": "D688a8670 existing authored me/evidence[0]; local silent PCM WAV",
            "native_end_inside_saved_moment": True,
            "source_duration_seconds": duration,
            "native_play_start_seconds": [start, start],
            "replayed_at_seconds": resumed_at,
            "source_reads_intercepted": len(source_reads),
            "quote_time_call_link_mission_query_and_32_44px_preserved": True,
            "keyboard_replay_then_pointer_pause": True,
            "api_mutations": len(mutations),
            "real_recording_provider_or_authenticated_acceptance": False,
        }


def test_fixture_coaching_hear_lesson_focus(browser: Browser, viewport: tuple[int, str]) -> None:
    """The existing narration shortcut moves focus to its own playback control."""
    if (
        os.environ.get("WB_MODE", "fixture") != "fixture"
        or os.environ["WB_BASE_URL"].rstrip("/") != "http://127.0.0.1:3026"
    ):
        pytest.skip("Narration shortcut checks use only the local Design review")
    payload = json.loads(
        (
            Path(__file__).resolve().parents[3]
            / "apps/sales-xray-web/app/review-fixture/coaching/sandbox.json"
        ).read_text()
    )["me"]
    clip = payload["media_clips"][0]
    source = (
        f"/v1/me/coaching/media/{clip['topic_id']}/{clip['revision']}/{clip['review_id']}/source"
    )
    with _journey(browser, viewport, "hear-lesson-focus") as journey:
        page = journey.page
        pending: list[Route] = []
        requests: list[str] = []
        unexpected_media: list[str] = []
        mutations: list[str] = []

        def controlled_read(route: Route) -> None:
            request = route.request
            url = urlsplit(request.url)
            if request.method not in {"GET", "HEAD"}:
                mutations.append(request.method)
                route.abort("blockedbyclient")
            elif url.netloc == "127.0.0.1:3026" and url.path == source:
                requests.append(request.method)
                pending.append(route)
            elif (
                request.resource_type == "media"
                or url.path.endswith("/source")
                or (url.path.startswith("/v1/") and "/media/" in url.path)
            ):
                unexpected_media.append("unexpected-source")
                route.abort("blockedbyclient")
            else:
                route.continue_()

        page.route("**/*", controlled_read)
        journey.open("/review-fixture/coaching?data=review&view=me")
        for label in ("Design review", "My coaching"):
            expect(page.get_by_role("button", name=label, exact=True)).to_have_attribute(
                "aria-pressed", "true"
            )
        page.evaluate("() => document.fonts.ready")
        page.wait_for_load_state("networkidle", timeout=15_000)
        hero = page.locator("#coaching-focus")
        hear = hero.get_by_role("button", name=re.compile(r"^Hear Dipak’s take"))
        card = page.locator("#coaching-better article[data-recommended]")
        play = card.locator("button").first
        transcript = card.locator("details").text_content()
        quote = page.locator("#coaching-evidence blockquote").first
        expect(quote).to_have_text(payload["evidence"][0]["quote"])
        expect(card.locator("h3")).to_have_text(clip["title"])
        expect(card).to_have_attribute("data-access", clip["access"])
        expect(page.locator("audio,video")).to_have_count(0)
        assert not requests, "Reading Coaching eagerly requested narration"
        hero.evaluate("el => el.scrollIntoView({block: 'center', behavior: 'instant'})")
        journey.snapshot("original-source-shortcut")
        journey.control_target(hear, "hear-dipak-shortcut")
        actions: list[dict[str, object]] = []
        for activation in ("pointer", "Enter"):
            with page.expect_request(lambda request: urlsplit(request.url).path == source):
                if activation == "pointer":
                    hear.click()
                else:
                    hear.focus()
                    page.keyboard.press("Enter")
            expect(card.locator("audio")).to_have_attribute("src", source)
            expect(play).to_be_disabled()
            expect(play).to_be_focused()
            # Wait for a stationary, reachable landing, rather than demanding
            # an exact card centre as its measured height changes.
            page.evaluate("window.__wbHearPreviousY = null")
            page.wait_for_function("""() => {
              const card = document.querySelector('#coaching-better article[data-recommended]');
              const control = card?.querySelector('button');
              if (!card || !control) return false;
              const r = control.getBoundingClientRect(), previous = window.__wbHearPreviousY;
              window.__wbHearPreviousY = r.y;
              return previous !== null && Math.abs(previous - r.y) < 0.5 && r.y >= 0 &&
                r.bottom <= innerHeight && control.contains(
                  document.elementFromPoint(r.x + r.width/2, r.y + r.height/2));
            }""")
            expect(play).to_be_disabled()
            expect(card.get_by_role("status")).to_have_count(0)
            journey.snapshot(f"{activation.lower()}-lesson-playback-focus")
            expect(play).to_be_disabled()
            expect(card.get_by_role("status")).to_have_count(0)
            journey.control_target(play, f"{activation.lower()}-lesson-playback")
            box = play.bounding_box()
            assert box and min(box["height"], box["width"]) >= (44 if journey.width == 390 else 40)
            page.keyboard.press("Tab")
            assert card.evaluate("el => el.contains(document.activeElement)"), (
                "Next Tab left the recommended lesson"
            )
            page.evaluate("window.__wbHearMovedFocus = document.activeElement")
            with page.expect_response(
                lambda response: response.status == 404 and urlsplit(response.url).path == source
            ):
                while pending:
                    with suppress(Exception):
                        # Ending one range can cancel another browser request;
                        # the response guard still requires an actual local404.
                        pending.pop().fulfill(status=404, content_type="text/plain", body="")
            expect(card.get_by_role("button", name="Try clip again", exact=True)).to_be_enabled()
            assert page.evaluate("document.activeElement === window.__wbHearMovedFocus"), (
                "Narration error stole the learner's moved focus"
            )
            expect(card.locator("audio")).to_have_count(0)
            expect(card.get_by_role("status")).to_contain_text("Narration is unavailable")
            expect(card.locator("h3")).to_have_text(clip["title"])
            expect(card).to_have_attribute("data-access", clip["access"])
            expect(card.locator("details[open]")).to_have_count(0)
            assert card.locator("details").text_content() == transcript
            expect(card).to_contain_text(clip["reason"])
            expect(quote).to_have_text(payload["evidence"][0]["quote"])
            expect(page.locator("[data-active-mission]")).to_have_text(
                payload["mission"]["behavior"]
            )
            expect(page).to_have_url(re.compile(r"/review-fixture/coaching\?data=review&view=me$"))
            actions.append(
                {
                    "activation": activation,
                    "playback_focused": True,
                    "next_tab_inside": True,
                    "error_preserves_moved_focus": True,
                    "source_still_loading_before_controlled_404": True,
                }
            )
        assert len(requests) >= 2 and not pending and not unexpected_media and not mutations
        assert journey.live_refreshes == 0, "Live source changed during narration shortcut"
        journey.observations[-1]["fictional_hear_lesson_focus"] = {
            "source": "Da97c3d38 existing authored me/media_clips[0]; held then404 source",
            "actions": actions,
            "original_quote_lesson_access_transcript_mission_query_preserved": True,
            "playback_targets_40_44px": True,
            "source_reads_intercepted": len(requests),
            "api_mutations": len(mutations),
            "actual_playback_provider_or_authenticated_acceptance": False,
        }


@pytest.mark.parametrize("interruption", ("moment", "fold", "pause", "viewclose"))
def test_fixture_coaching_interrupted_lesson_resume(
    browser: Browser, viewport: tuple[int, str], interruption: str
) -> None:
    """A source lesson remembers the native position when another control pauses it."""
    if (
        os.environ.get("WB_MODE", "fixture") != "fixture"
        or os.environ["WB_BASE_URL"].rstrip("/") != "http://127.0.0.1:3026"
    ):
        pytest.skip("Interruption/resume checks use only the local Design review")
    payload = json.loads(
        (
            Path(__file__).resolve().parents[3]
            / "apps/sales-xray-web/app/review-fixture/coaching/sandbox.json"
        ).read_text()
    )["me"]
    clip = payload["media_clips"][1 if interruption == "fold" else 0]
    source = (
        f"/v1/me/coaching/media/{clip['topic_id']}/{clip['revision']}/{clip['review_id']}/source"
    )
    call_source = (
        f"/v1/conversation/acquisition/submissions/{payload['evidence'][0]['submission_id']}/source"
    )
    storage_key = f"sx-coaching-clip:{clip['topic_id']}:{clip['revision']}:{clip['review_id']}"
    with BytesIO() as output:
        with wave.open(output, "wb") as local_audio:
            local_audio.setnchannels(1)
            local_audio.setsampwidth(2)
            local_audio.setframerate(8000)
            local_audio.writeframes(b"\0\0" * 70 * 8000)
        silent_wav = output.getvalue()
    with _journey(browser, viewport, f"lesson-resume-{interruption}") as journey:
        page = journey.page
        reads = {source: 0, call_source: 0}
        unexpected_media: list[str] = []
        mutations: list[str] = []
        page.add_init_script("""(() => {
          window.__wbLessonStarts = [];
          const nativePlay = HTMLMediaElement.prototype.play;
          HTMLMediaElement.prototype.play = function () {
            window.__wbLessonStarts.push({source: this.getAttribute('src'), at: this.currentTime});
            this.muted = true;
            return nativePlay.call(this);
          };
        })();""")

        def local_read(route: Route) -> None:
            request = route.request
            url = urlsplit(request.url)
            if request.method not in {"GET", "HEAD"}:
                mutations.append(request.method)
                route.abort("blockedbyclient")
            elif url.netloc == "127.0.0.1:3026" and url.path == source:
                reads[source] += 1
                byte_range = re.fullmatch(r"bytes=(\d+)-(\d*)", request.headers.get("range", ""))
                first = int(byte_range[1]) if byte_range else 0
                last = (
                    min(int(byte_range[2]), len(silent_wav) - 1)
                    if byte_range and byte_range[2]
                    else len(silent_wav) - 1
                )
                if first > last:
                    route.fulfill(
                        status=416, headers={"Content-Range": f"bytes */{len(silent_wav)}"}
                    )
                    return
                body = silent_wav[first : last + 1]
                headers = {"Accept-Ranges": "bytes", "Content-Length": str(len(body))}
                if byte_range:
                    headers["Content-Range"] = f"bytes {first}-{last}/{len(silent_wav)}"
                route.fulfill(
                    status=206 if byte_range else 200,
                    content_type="audio/wav",
                    headers=headers,
                    body=body if request.method == "GET" else b"",
                )
            elif url.netloc == "127.0.0.1:3026" and url.path == call_source:
                reads[call_source] += 1
                route.fulfill(status=404, content_type="text/plain", body="")
            elif (
                request.resource_type == "media"
                or url.path.endswith("/source")
                or (url.path.startswith("/v1/") and "/media/" in url.path)
            ):
                unexpected_media.append("unexpected-source")
                route.abort("blockedbyclient")
            else:
                route.continue_()

        page.route("**/*", local_read)

        def ready() -> None:
            for label in ("Design review", "My coaching"):
                expect(page.get_by_role("button", name=label, exact=True)).to_have_attribute(
                    "aria-pressed", "true"
                )
            page.evaluate("() => document.fonts.ready")
            expect(page.locator("audio,video")).to_have_count(0)

        journey.open("/review-fixture/coaching?data=review&view=me")
        ready()
        assert not any(reads.values()), "Reading Coaching eagerly requested media"
        more = page.locator("#coaching-better details[data-other-lessons]")
        summary = more.locator(":scope > summary")
        card = (
            more.locator("article").first
            if interruption == "fold"
            else page.locator("#coaching-better article[data-recommended]")
        )
        quote = page.locator("#coaching-evidence blockquote").first
        expect(quote).to_have_text(payload["evidence"][0]["quote"])
        if interruption == "fold":
            summary.click()
        card.get_by_role("button", name="Play coaching clip", exact=True).click()
        pause = card.get_by_role("button", name="Pause", exact=True)
        expect(pause).to_be_visible()
        audio = card.locator("audio")
        expect(audio).to_have_attribute("src", source)
        audio.evaluate("el => { window.__wbInterruptedLesson = el; }")
        page.wait_for_function(
            """({source, start}) => {
              const audio = document.querySelector(`audio[src="${source}"]`);
              return audio && audio.currentTime >= start + 0.8;
            }""",
            arg={"source": source, "start": clip["start_ms"] / 1000},
        )
        assert page.evaluate("key => localStorage.getItem(key)", storage_key) is None
        if interruption == "moment":
            moment = page.locator("#coaching-evidence li").first
            moment.get_by_role("button", name=re.compile(r"^Play moment")).click()
            expect(
                moment.get_by_role("button", name=re.compile(r"^Try audio again"))
            ).to_be_enabled()
            assert reads[call_source] >= 1
        elif interruption == "fold":
            summary.click()
            assert more.get_attribute("open") is None
        elif interruption == "pause":
            pause.click()
        else:
            page.get_by_role("button", name="This call", exact=True).click()
            expect(page.get_by_role("button", name="This call", exact=True)).to_have_attribute(
                "aria-pressed", "true"
            )
        page.wait_for_function("window.__wbInterruptedLesson.paused")
        paused_at = page.evaluate("Math.round(window.__wbInterruptedLesson.currentTime * 1000)")
        saved = int(page.evaluate("key => localStorage.getItem(key)", storage_key) or 0)
        assert 0 < saved < 2000, "Interruption was not before the first device checkpoint"
        assert saved == paused_at - clip["start_ms"], "Saved offset differs from native paused time"
        resume = card.get_by_role("button", name="Resume clip", exact=True)
        if interruption == "viewclose":
            assert page.evaluate("window.__wbInterruptedLesson.isConnected") is False
            before_return = dict(reads)
            page.get_by_role("button", name="My coaching", exact=True).click()
            ready()
            assert reads == before_return, "Returning to Coaching eagerly requested media"
            assert (
                page.evaluate("Math.round(window.__wbInterruptedLesson.currentTime * 1000)")
                == paused_at
            )
        if interruption == "fold":
            summary.click()
        expect(resume).to_be_visible()
        card.evaluate("el => el.scrollIntoView({block: 'center', behavior: 'instant'})")
        journey.snapshot("interruption-saved-native-position")
        journey.control_target(resume, "interrupted-lesson-resume")
        if interruption == "fold":
            journey.control_target(summary, "secondary-lesson-fold")
        before_reload = dict(reads)
        response = page.reload(wait_until="domcontentloaded", timeout=60_000)
        assert response and response.status < 400
        ready()
        assert reads == before_reload, "Reload eagerly requested media"
        if interruption == "fold":
            assert more.get_attribute("open") is None
            summary.click()
        expect(resume).to_be_visible()
        resume.focus()
        page.keyboard.press("Enter")
        expect(pause).to_be_visible()
        expect(pause).to_be_focused()
        expect(audio).to_have_attribute("src", source)
        expected_start = (clip["start_ms"] + saved) / 1000
        assert page.evaluate("window.__wbLessonStarts") == [
            {"source": source, "at": expected_start}
        ]
        card.evaluate("el => el.scrollIntoView({block: 'center', behavior: 'instant'})")
        journey.snapshot("reloaded-original-source-resumed")
        journey.control_target(pause, "reloaded-lesson-pause")
        pause.click()
        assert audio.evaluate("el => el.paused")
        expect(card.locator("h3")).to_have_text(clip["title"])
        expect(card).to_have_attribute("data-access", clip["access"])
        expect(card).to_contain_text(clip["reason"])
        expect(card).to_contain_text(clip["transcript_excerpt"])
        expect(quote).to_have_text(payload["evidence"][0]["quote"])
        expect(page.locator("[data-active-mission]")).to_have_text(payload["mission"]["behavior"])
        expect(page).to_have_url(re.compile(r"/review-fixture/coaching\?data=review&view=me$"))
        assert not unexpected_media and not mutations
        assert journey.live_refreshes == 0, "Live source changed during interruption/resume"
        journey.observations[-1]["fictional_interrupted_lesson_resume"] = {
            "source": "D135be632/b7623097/f20b606f authored clips; local70s silent WAV/404 call",
            "interruption": interruption,
            "native_paused_at_ms": paused_at,
            "saved_window_offset_ms": saved,
            "native_reloaded_start_seconds": expected_start,
            "no_eager_audio_before_play_or_after_reload": True,
            "quote_lesson_access_transcript_mission_query_focus_and_32_44px_preserved": True,
            "source_reads_intercepted": sum(reads.values()),
            "api_mutations": len(mutations),
            "device_position_only_not_canonical_progress": True,
            "real_recording_provider_or_authenticated_acceptance": False,
        }


def test_fixture_coaching_moment_view_close(browser: Browser, viewport: tuple[int, str]) -> None:
    """Leaving a fictional moment stops its detached player and preserves original replay."""
    if (
        os.environ.get("WB_MODE", "fixture") != "fixture"
        or os.environ["WB_BASE_URL"].rstrip("/") != "http://127.0.0.1:3026"
    ):
        pytest.skip("Moment teardown uses only the existing local Design review")
    payload = json.loads(
        (
            Path(__file__).resolve().parents[3]
            / "apps/sales-xray-web/app/review-fixture/coaching/sandbox.json"
        ).read_text()
    )["me"]
    evidence = payload["evidence"][0]
    source = f"/v1/conversation/acquisition/submissions/{evidence['submission_id']}/source"
    start = evidence["start_ms"] / 1000
    with BytesIO() as output:
        with wave.open(output, "wb") as local_audio:
            local_audio.setnchannels(1)
            local_audio.setsampwidth(2)
            local_audio.setframerate(8000)
            local_audio.writeframes(b"\0\0" * round((evidence["end_ms"] / 1000 + 5) * 8000))
        silent_wav = output.getvalue()
    with _journey(browser, viewport, "moment-view-close") as journey:
        page = journey.page
        loading = False
        pending: list[Route] = []
        reads: list[str] = []
        media: list[str] = []
        mutations: list[str] = []
        page.add_init_script("""(() => {
          window.__wbLeavingMomentStarts = [];
          const nativePlay = HTMLMediaElement.prototype.play;
          HTMLMediaElement.prototype.play = function () {
            window.__wbLeavingMomentStarts.push({
              source: this.getAttribute('src'), at: this.currentTime,
            });
            this.muted = true;
            return nativePlay.call(this);
          };
        })();""")

        def local_read(route: Route) -> None:
            request = route.request
            url = urlsplit(request.url)
            if request.method not in {"GET", "HEAD"}:
                mutations.append(request.method)
                route.abort("blockedbyclient")
            elif url.netloc == "127.0.0.1:3026" and url.path == source:
                reads.append(request.method)
                if loading:
                    pending.append(route)
                    return
                byte_range = re.fullmatch(r"bytes=(\d+)-(\d*)", request.headers.get("range", ""))
                first = int(byte_range[1]) if byte_range else 0
                last = (
                    min(int(byte_range[2]), len(silent_wav) - 1)
                    if byte_range and byte_range[2]
                    else len(silent_wav) - 1
                )
                if first > last:
                    route.fulfill(
                        status=416, headers={"Content-Range": f"bytes */{len(silent_wav)}"}
                    )
                    return
                body = silent_wav[first : last + 1]
                headers = {"Accept-Ranges": "bytes", "Content-Length": str(len(body))}
                if byte_range:
                    headers["Content-Range"] = f"bytes {first}-{last}/{len(silent_wav)}"
                route.fulfill(
                    status=206 if byte_range else 200,
                    content_type="audio/wav",
                    headers=headers,
                    body=body if request.method == "GET" else b"",
                )
            elif (
                request.resource_type == "media"
                or url.path.endswith("/source")
                or (url.path.startswith("/v1/") and "/media/" in url.path)
            ):
                media.append("unexpected-source")
                route.abort("blockedbyclient")
            else:
                route.continue_()

        page.route("**/*", local_read)

        def ready() -> None:
            for label in ("Design review", "My coaching"):
                expect(page.get_by_role("button", name=label, exact=True)).to_have_attribute(
                    "aria-pressed", "true"
                )
            page.evaluate("() => document.fonts.ready")
            expect(page.locator("audio,video")).to_have_count(0)

        def leave_and_return() -> dict[str, object]:
            page.get_by_role("button", name="This call", exact=True).click()
            expect(page.get_by_role("button", name="This call", exact=True)).to_have_attribute(
                "aria-pressed", "true"
            )
            old = page.evaluate("""() => ({
              connected: window.__wbLeftMoment.isConnected,
              paused: window.__wbLeftMoment.paused,
              position: window.__wbLeftMoment.currentTime,
            })""")
            assert old["connected"] is False and old["paused"] is True
            before_return = len(reads)
            page.get_by_role("button", name="My coaching", exact=True).click()
            ready()
            assert len(reads) == before_return, "Returning eagerly fetched a moment source"
            assert page.evaluate("window.__wbLeftMoment.currentTime") == old["position"]
            return old

        journey.open("/review-fixture/coaching?data=review&view=me")
        ready()
        assert not reads, "Reading Coaching eagerly fetched a moment source"
        moment = page.locator("#coaching-evidence li").first
        expect(moment.locator("blockquote")).to_have_text(evidence["quote"])
        call_link = moment.get_by_role("link", name=evidence["call_label"], exact=True)
        call_href = call_link.get_attribute("href")
        play = moment.get_by_role("button", name=re.compile(r"^Play moment"))
        original_label = play.get_attribute("aria-label")
        play.click()
        pause = moment.get_by_role("button", name=re.compile(r"^Pause moment"))
        expect(pause).to_be_visible()
        audio = moment.locator("audio")
        expect(audio).to_have_attribute("src", source)
        assert audio.evaluate("el => !el.paused")
        audio.evaluate("el => {window.__wbLeftMoment = el;}")
        closed_playing = leave_and_return()
        expect(play).to_have_attribute("aria-label", original_label)
        moment.evaluate("el => el.scrollIntoView({block: 'center', behavior: 'instant'})")
        journey.snapshot("playing-player-detached-return-ready")
        journey.control_target(play, "returned-moment-play")
        play.focus()
        page.keyboard.press("Enter")
        expect(pause).to_be_visible()
        expect(pause).to_be_focused()
        assert page.evaluate("window.__wbLeavingMomentStarts") == [
            {"source": source, "at": start},
            {"source": source, "at": start},
        ]
        journey.snapshot("original-source-replayed-native-focus")
        journey.control_target(pause, "replayed-moment-pause")
        pause.click()
        # The same existing source also covers closing while metadata is held.
        loading = True
        response = page.reload(wait_until="domcontentloaded", timeout=60_000)
        assert response and response.status < 400
        ready()
        with page.expect_request(lambda request: urlsplit(request.url).path == source):
            play.click()
        expect(moment.locator("audio")).to_have_attribute("src", source)
        expect(moment.locator("button").first).to_be_disabled()
        moment.locator("audio").evaluate("el => {window.__wbLeftMoment = el;}")
        closed_loading = leave_and_return()
        while pending:
            with suppress(Exception):
                pending.pop().fulfill(status=200, content_type="audio/wav", body=silent_wav)
        page.evaluate("""() => new Promise(resolve => requestAnimationFrame(
          () => requestAnimationFrame(resolve)))""")
        assert page.evaluate("window.__wbLeavingMomentStarts") == []
        assert page.evaluate("window.__wbLeftMoment.paused") is True
        assert page.evaluate("window.__wbLeftMoment.currentTime") == closed_loading["position"]
        expect(play).to_be_enabled()
        expect(play).to_have_attribute("aria-label", original_label)
        expect(moment.locator("blockquote")).to_have_text(evidence["quote"])
        expect(call_link).to_have_attribute("href", call_href)
        expect(page.locator("[data-active-mission]")).to_have_text(payload["mission"]["behavior"])
        expect(page).to_have_url(re.compile(r"/review-fixture/coaching\?data=review&view=me$"))
        moment.evaluate("el => el.scrollIntoView({block: 'center', behavior: 'instant'})")
        journey.snapshot("held-loading-player-detached-return-ready")
        journey.control_target(play, "loading-close-return-play")
        assert not media and not mutations
        assert journey.live_refreshes == 0, "Live source changed during moment teardown"
        journey.observations[-1]["fictional_moment_view_close"] = {
            "source": "D37f7ef65 existing authored first moment; muted local PCM/held source",
            "playing_detached_paused_position": closed_playing["position"],
            "held_loading_detached_paused_position": closed_loading["position"],
            "no_eager_return_or_native_play_after_loading_close": True,
            "original_source_start_quote_call_mission_query_focus_and_32_44px_preserved": True,
            "late_source_delivery_attempted_locally": True,
            "unresolved_play_promise_browser_tested": False,
            "api_mutations": len(mutations),
            "real_recording_provider_or_authenticated_acceptance": False,
        }


def test_fixture_coaching_audio_startup(browser: Browser, viewport: tuple[int, str]) -> None:
    """A stalled fictional source exposes retry while keeping its words and times."""
    if (
        os.environ.get("WB_MODE", "fixture") != "fixture"
        or os.environ["WB_BASE_URL"].rstrip("/") != "http://127.0.0.1:3026"
    ):
        pytest.skip("Controlled startup checks use only the existing local Design review")
    payload = json.loads(
        (
            Path(__file__).resolve().parents[3]
            / "apps/sales-xray-web/app/review-fixture/coaching/sandbox.json"
        ).read_text()
    )["me"]
    evidence, clip = payload["evidence"][0], payload["media_clips"][0]
    assert evidence["playable"] and clip["access"] == "full"
    moment_source = f"/v1/conversation/acquisition/submissions/{evidence['submission_id']}/source"
    lesson_source = (
        f"/v1/me/coaching/media/{clip['topic_id']}/{clip['revision']}/{clip['review_id']}/source"
    )
    with _journey(browser, viewport, "audio-startup") as journey:
        page = journey.page
        source_requests = {moment_source: 0, lesson_source: 0}
        pending: dict[str, Route] = {}
        mutations: list[str] = []
        unexpected_media: list[dict[str, str]] = []

        def controlled_read(route: Route) -> None:
            request = route.request
            url = urlsplit(request.url)
            is_media = (
                request.resource_type == "media"
                or re.search(r"/(source|media)/", url.path)
                or url.path.endswith("/source")
            )
            # Next also puts font files in /static/media; they are page assets,
            # not recording/lesson sources. Keep the exception local and typed.
            static_font = (
                request.resource_type == "font"
                and url.netloc == "127.0.0.1:3026"
                and url.path.startswith("/_next/static/media/")
            )
            if request.method not in {"GET", "HEAD"}:
                mutations.append(request.method)
                route.abort("blockedbyclient")
            elif is_media and not static_font:
                if url.netloc != "127.0.0.1:3026" or url.path not in source_requests:
                    unexpected_media.append(
                        {
                            "type": request.resource_type,
                            "path": url.path if url.netloc == "127.0.0.1:3026" else "external",
                        }
                    )
                    route.abort("blockedbyclient")
                else:
                    source_requests[url.path] += 1
                    if source_requests[url.path] in {1, 3}:
                        # Keep the browser's request pending; no server/provider
                        # receives it. The middle retry gets an unavailable reply;
                        # the last attempt checks that moved focus is respected.
                        pending[url.path] = route
                    else:
                        route.fulfill(status=404, content_type="text/plain", body="")
            else:
                route.continue_()

        page.route("**/*", controlled_read)
        journey.open("/review-fixture/coaching?data=review&view=me")
        for label in ("Design review", "My coaching"):
            expect(page.get_by_role("button", name=label, exact=True)).to_have_attribute(
                "aria-pressed", "true"
            )
        page.evaluate("() => document.fonts.ready")
        page.wait_for_load_state("networkidle", timeout=15_000)
        expect(page.locator("audio,video")).to_have_count(0)
        assert not any(source_requests.values()), "Reading Coaching eagerly requested media"
        moment = page.locator("#coaching-evidence li").first
        lesson = page.locator("#coaching-better article[data-recommended]")
        expect(moment.locator("blockquote")).to_have_text(evidence["quote"])
        expect(lesson.locator("h3")).to_have_text(clip["title"])
        original_lesson = lesson.locator("details").text_content()
        original_time = moment.get_by_role(
            "button", name=re.compile(r"^Play moment")
        ).get_attribute("aria-label")
        span = (
            f"{evidence['start_ms'] // 60_000}:{evidence['start_ms'] // 1000 % 60:02d}"
            f"–{evidence['end_ms'] // 60_000}:{evidence['end_ms'] // 1000 % 60:02d}"
        )
        assert original_time == f"Play moment {span}"
        page.clock.install()
        # Freeze time before clicks so request setup cannot consume the deadline.
        page.clock.pause_at(datetime.now(UTC) + timedelta(seconds=1))
        checks: list[dict[str, object]] = []
        for name, card, source, play_name, retry_name, failure_text in (
            (
                "moment",
                moment,
                moment_source,
                re.compile(r"^Play moment"),
                re.compile(r"^Try audio again"),
                "the quote stays here",
            ),
            (
                "lesson",
                lesson,
                lesson_source,
                "Play coaching clip",
                "Try clip again",
                "Narration is unavailable",
            ),
        ):
            play = card.get_by_role("button", name=play_name)
            with page.expect_request(
                lambda request, expected=source: urlsplit(request.url).path == expected
            ):
                play.click()
            expect(card.locator("audio")).to_have_attribute("src", source)
            loading = card.locator("button").first
            expect(loading).to_have_count(1)
            expect(loading).to_be_disabled()
            page.clock.fast_forward(14_999)
            expect(loading).to_be_disabled()
            expect(card.get_by_role("status")).to_have_count(0)
            page.clock.fast_forward(1)
            retry = card.get_by_role("button", name=retry_name)
            expect(retry).to_be_enabled()
            expect(card.locator("audio")).to_have_count(0)
            expect(card.get_by_role("status")).to_contain_text(failure_text)
            assert source_requests[source] == 1
            pending.pop(source).abort("blockedbyclient")
            card.evaluate("el => el.scrollIntoView({block: 'center', behavior: 'instant'})")
            journey.snapshot(f"{name}-retry-keeps-source")
            journey.control_target(retry, f"{name}-retry")
            retry.focus()
            with page.expect_request(
                lambda request, expected=source: urlsplit(request.url).path == expected
            ):
                page.keyboard.press("Enter")
            expect(retry).to_be_enabled()
            journey.observations[-1]["keyboard_retry"] = retry.evaluate(
                """el => ({focused: document.activeElement === el,
                  active_tag: document.activeElement?.tagName,
                  enabled: !el.disabled})"""
            )
            expect(retry).to_be_focused()
            expect(card.locator("audio")).to_have_count(0)
            expect(card.get_by_role("status")).to_contain_text(failure_text)
            assert source_requests[source] == 2, "Retry changed or duplicated its source request"
            if name == "moment":
                expect(retry).to_have_attribute("aria-label", f"Try audio again {span}")
            journey.snapshot(f"{name}-keyboard-retry-focus")

            # Loading must prevent another activation without dropping keyboard
            # focus. Deliberately move to another existing control before expiry:
            # the recovered player must then leave that chosen focus alone.
            with page.expect_request(
                lambda request, expected=source: urlsplit(request.url).path == expected
            ):
                page.keyboard.press("Enter")
            loading = card.locator("button").first
            expect(loading).to_have_count(1)
            expect(loading).to_be_disabled()
            expect(loading).to_be_focused()
            page.keyboard.press("Enter")
            page.clock.fast_forward(1)
            assert source_requests[source] == 3, "Loading activation duplicated its source request"
            moved_focus = page.get_by_role("button", name="Design review", exact=True)
            moved_focus.focus()
            expect(moved_focus).to_be_focused()
            page.clock.fast_forward(14_998)
            expect(loading).to_be_disabled()
            expect(card.get_by_role("status")).to_have_count(0)
            page.clock.fast_forward(1)
            expect(retry).to_be_enabled()
            expect(moved_focus).to_be_focused()
            expect(card.locator("audio")).to_have_count(0)
            expect(card.get_by_role("status")).to_contain_text(failure_text)
            assert source_requests[source] == 3
            pending.pop(source).abort("blockedbyclient")
            checks.append(
                {
                    "player": name,
                    "deadline_ms": 15_000,
                    "same_source_attempts": 3,
                    "keyboard_retry_focus_retained": True,
                    "loading_activation_inert": True,
                    "deliberately_moved_focus_retained": True,
                }
            )
        expect(moment.locator("blockquote")).to_have_text(evidence["quote"])
        final_moment_retry = moment.get_by_role("button", name=re.compile(r"^Try audio again"))
        expect(final_moment_retry).to_have_attribute("aria-label", f"Try audio again {span}")
        expect(lesson.locator("h3")).to_have_text(clip["title"])
        expect(lesson).to_have_attribute("data-access", clip["access"])
        assert lesson.locator("details").text_content() == original_lesson
        expect(lesson).to_contain_text(clip["reason"])
        expect(page.locator("[data-active-mission]")).to_have_text(payload["mission"]["behavior"])
        expect(page).to_have_url(re.compile(r"/review-fixture/coaching\?data=review&view=me$"))
        journey.observations[-1]["unexpected_media"] = unexpected_media
        assert not pending and not unexpected_media and not mutations
        assert journey.live_refreshes == 0, "Live source changed during controlled startup"
        journey.observations[-1]["fictional_audio_startup"] = {
            "source": "existing sandbox.json/me; intercepted stalled/404/stalled sources",
            "players": checks,
            "quote_times_lesson_access_transcript_mission_query_preserved": True,
            "keyboard_retry_and_32_44px_targets": True,
            "loading_activation_inert_and_moved_focus_not_stolen": True,
            "source_requests_intercepted": sum(source_requests.values()),
            "api_mutations": len(mutations),
            "actual_playback_provider_or_authenticated_acceptance": False,
            "late_play_promise_preview_and_switch_cleanup_browser_tested": False,
        }


@pytest.mark.parametrize("scene", ("personal", "rep"))
def test_fixture_coaching_secondary_lessons(
    browser: Browser, viewport: tuple[int, str], scene: str
) -> None:
    """Secondary source lessons fold independently without fetching their media."""
    if os.environ.get("WB_MODE", "fixture") != "fixture":
        pytest.skip("Secondary lessons use D's existing fictional personal/rep sources")
    sandbox = scene == "rep"
    data = "sandbox" if sandbox else "review"
    filename = "sandbox-team.json" if sandbox else "sandbox.json"
    key = "rep" if sandbox else "me"
    payload = json.loads(
        (
            Path(__file__).resolve().parents[3]
            / "apps/sales-xray-web/app/review-fixture/coaching"
            / filename
        ).read_text()
    )[key]
    clips = payload["media_clips"]
    assert len(clips) == 2, "The existing authored source has changed"
    with _journey(browser, viewport, f"secondary-lessons-{scene}") as journey:
        page = journey.page
        mutations: list[str] = []
        media: list[str] = []

        def observe_read(route: Route) -> None:
            request = route.request
            path = urlsplit(request.url).path
            if request.method not in {"GET", "HEAD"}:
                mutations.append(request.method)
                route.abort("blockedbyclient")
            elif re.search(r"/(source|media)/", path) or path.endswith("/source"):
                media.append("source-read")
                route.abort("blockedbyclient")
            else:
                route.continue_()

        page.route("**/v1/**", observe_read)
        page.on(
            "request",
            lambda request: media.append("media") if request.resource_type == "media" else None,
        )
        journey.open(f"/review-fixture/coaching?data={data}&view=me")
        expect(
            page.get_by_role(
                "button", name="AC Sandbox" if sandbox else "Design review", exact=True
            )
        ).to_have_attribute("aria-pressed", "true")
        expect(
            page.get_by_role("button", name="One rep" if sandbox else "My coaching", exact=True)
        ).to_have_attribute("aria-pressed", "true")
        page.evaluate("() => document.fonts.ready")
        page.wait_for_load_state("networkidle", timeout=15000)
        pillar = page.locator("#coaching-better")
        cards = pillar.locator("article[data-access]")
        expect(cards).to_have_count(len(clips))
        recommendation, secondary = cards.nth(0), cards.nth(1)
        original_recommendation = recommendation.inner_text()
        expect(recommendation).to_contain_text(clips[0]["title"])
        expect(recommendation).to_contain_text(clips[0]["reason"])
        expect(recommendation).to_have_attribute("data-recommended", "")
        expect(recommendation).to_have_attribute("data-access", clips[0]["access"])
        more = pillar.locator("details[data-other-lessons]")
        summary = more.locator(":scope > summary")
        expect(summary).to_have_text(f"More lessons · {len(clips) - 1}")
        controls = summary.get_attribute("aria-controls")
        assert controls
        expect(more.locator(f'[id="{controls}"]')).to_have_count(1)
        assert more.get_attribute("open") is None
        expect(secondary).not_to_be_visible()
        expect(recommendation.locator("details[open]")).to_have_count(0)
        summary.evaluate("el => el.scrollIntoView({block: 'center', behavior: 'instant'})")
        journey.snapshot("compact-summary")
        journey.control_target(summary, "more-lessons")
        journey.control_target(recommendation.locator("details > summary"), "recommended-takeaways")
        assert summary.bounding_box()["height"] >= (44 if journey.width == 390 else 40), (
            "The native lesson summary is below its existing 40/44px floor"
        )
        summary.click()
        expect(more).to_have_attribute("open", "")
        expect(secondary).to_be_visible()
        expect(secondary).to_contain_text(clips[1]["title"])
        expect(secondary).to_contain_text(clips[1]["reason"])
        expect(secondary).to_have_attribute("data-access", clips[1]["access"])
        assert secondary.get_attribute("data-recommended") is None
        for takeaway in clips[1]["takeaways"]:
            expect(secondary).to_contain_text(takeaway)
        if clips[1]["access"] == "preview":
            preview = (clips[1]["preview_end_ms"] - clips[1]["start_ms"]) // 1000
            expect(secondary).to_contain_text(f"Free preview · {preview // 60}:{preview % 60:02d}")
        nested = secondary.locator("details")
        nested_summary = nested.locator(":scope > summary")
        expect(nested_summary).to_have_text("Read key takeaways")
        assert nested.get_attribute("open") is None
        nested_summary.click()
        expect(nested).to_have_attribute("open", "")
        expect(nested).to_contain_text(clips[1]["transcript_excerpt"])
        nested_summary.focus()
        page.keyboard.press("Enter")
        assert nested.get_attribute("open") is None
        expect(nested_summary).to_be_focused()
        expect(more).to_have_attribute("open", "")
        page.keyboard.press("Enter")
        expect(nested).to_have_attribute("open", "")
        secondary.evaluate("el => el.scrollIntoView({block: 'center', behavior: 'instant'})")
        journey.snapshot("source-transcript-expanded")
        journey.control_target(nested_summary, "nested-takeaways")
        assert recommendation.inner_text() == original_recommendation
        nested_summary.click()
        assert nested.get_attribute("open") is None
        expect(more).to_have_attribute("open", "")
        summary.focus()
        page.keyboard.press("Enter")
        assert more.get_attribute("open") is None
        expect(summary).to_be_focused()
        expect(secondary).not_to_be_visible()
        page.keyboard.press("Enter")
        expect(more).to_have_attribute("open", "")
        page.keyboard.press("Tab")
        assert secondary.evaluate("el => el.contains(document.activeElement)"), (
            "Next Tab left the revealed secondary lesson"
        )
        summary.click()
        assert more.get_attribute("open") is None
        expect(summary).to_be_focused()
        expect(secondary).not_to_be_visible()
        assert recommendation.inner_text() == original_recommendation
        expect(page.locator("[data-active-mission]")).to_have_text(payload["mission"]["behavior"])
        expect(page).to_have_url(re.compile(rf"/review-fixture/coaching\?data={data}&view=me$"))
        expect(page.locator("audio,video")).to_have_count(0)
        summary.evaluate("el => el.scrollIntoView({block: 'center', behavior: 'instant'})")
        journey.snapshot("folded-native-focus")
        assert not media, "Secondary lesson disclosure fetched media or a recording source"
        assert not mutations, "Secondary lesson disclosure attempted an API mutation"
        journey.observations[-1]["fictional_secondary_lessons"] = {
            "source": f"De358c19a existing {filename}/{key}",
            "recommended_source_unchanged": True,
            "secondary_titles_reasons_takeaways_transcript_access_preview_preserved": True,
            "native_pointer_enter_nested_independence_and_next_tab": True,
            "summary_40_44px_and_mission_query_unchanged": True,
            "media_requests": len(media),
            "api_mutations": len(mutations),
            "audio_request_fold_pause_or_authenticated_acceptance": False,
        }


@pytest.mark.parametrize("scene", ("personal", "rep", "call", "rep-call"))
def test_fixture_coaching_focus_lesson(
    browser: Browser, viewport: tuple[int, str], scene: str
) -> None:
    """Native lesson/mission shortcuts retain source content, folded state and focus."""
    if os.environ.get("WB_MODE", "fixture") != "fixture":
        pytest.skip("Lesson shortcuts use D's four existing fictional surfaces")
    sandbox = scene in {"rep", "rep-call"}
    view = "call" if scene in {"call", "rep-call"} else "me"
    data = "sandbox" if sandbox else "review"
    filename = "sandbox-team.json" if sandbox else "sandbox.json"
    key = "call" if view == "call" else "rep" if sandbox else "me"
    payload = json.loads(
        (
            Path(__file__).resolve().parents[3]
            / "apps/sales-xray-web/app/review-fixture/coaching"
            / filename
        ).read_text()
    )[key]
    mission_id = "call-mission" if view == "call" else "mission"
    with _journey(browser, viewport, f"focus-lesson-{scene}") as journey:
        page = journey.page
        mutations: list[str] = []
        media: list[str] = []

        def observe_read(route: Route) -> None:
            request = route.request
            path = urlsplit(request.url).path
            if request.method not in {"GET", "HEAD"}:
                mutations.append(request.method)
                route.abort("blockedbyclient")
            elif re.search(r"/(source|media)/", path) or path.endswith("/source"):
                media.append("source-read")
                route.abort("blockedbyclient")
            else:
                route.continue_()

        page.route("**/v1/**", observe_read)
        page.on(
            "request",
            lambda request: media.append("media") if request.resource_type == "media" else None,
        )
        journey.open(f"/review-fixture/coaching?data={data}&view={view}")
        expect(
            page.get_by_role(
                "button", name="AC Sandbox" if sandbox else "Design review", exact=True
            )
        ).to_have_attribute("aria-pressed", "true")
        selected_view = "This call" if view == "call" else "One rep" if sandbox else "My coaching"
        expect(page.get_by_role("button", name=selected_view, exact=True)).to_have_attribute(
            "aria-pressed", "true"
        )
        page.evaluate("() => document.fonts.ready")
        hero = page.locator("#coaching-focus")
        lesson = page.locator("#coaching-better")
        mission = page.locator(f"#{mission_id}")
        lesson_link = hero.get_by_role("link", name="See the lesson", exact=True)
        mission_link = hero.get_by_role("link", name="See the mission", exact=True)
        expect(hero).to_contain_text(payload["focus"]["label"])
        expect(lesson).to_contain_text(payload["lesson"]["title"])
        expect(mission.locator("[data-active-mission]")).to_have_text(
            payload["mission"]["behavior"]
        )
        lesson_text = lesson.inner_text()
        hero.evaluate("el => el.scrollIntoView({block: 'center', behavior: 'instant'})")
        journey.snapshot("focus-shortcuts")
        for control, target, label in (
            (lesson_link, lesson, "lesson-shortcut"),
            (mission_link, mission, "mission-shortcut"),
        ):
            target_id = target.get_attribute("id")
            expect(control).to_have_attribute("href", f"#{target_id}")
            expect(control).to_have_attribute("aria-controls", target_id)
            expect(target).to_have_attribute("tabindex", "-1")
            journey.control_target(control, label)
        assert abs(lesson_link.bounding_box()["y"] - mission_link.bounding_box()["y"]) <= 1, (
            "Lesson and mission shortcuts left their shared row"
        )

        def landed(target: Locator, anchor: str) -> None:
            expect(target).to_be_focused()
            expect(target.get_by_role("heading").first).to_be_in_viewport()
            location = urlsplit(page.url)
            assert location.fragment == anchor
            assert parse_qs(location.query).get("data") == [data]
            assert parse_qs(location.query).get("view") == [view]

        lesson_link.click()
        landed(lesson, "coaching-better")
        page.keyboard.press("Tab")
        assert lesson.evaluate("el => el.contains(document.activeElement)"), (
            "Next Tab left the lesson"
        )
        expect(lesson.locator("details[open]")).to_have_count(0)
        assert lesson.inner_text() == lesson_text
        journey.snapshot("lesson-native-focus")
        lesson_link.focus()
        page.keyboard.press("Enter")
        landed(lesson, "coaching-better")
        mission_link.focus()
        page.keyboard.press("Enter")
        landed(mission, mission_id)
        mission_link.click()
        landed(mission, mission_id)
        expect(mission.locator("[data-active-mission]")).to_have_text(
            payload["mission"]["behavior"]
        )
        expect(lesson.locator("details[open]")).to_have_count(0)
        assert lesson.inner_text() == lesson_text
        expect(page.locator("audio")).to_have_count(0)
        if sandbox:
            expect(page.get_by_role("button", name="Share my coaching", exact=True)).to_have_count(
                0
            )
            expect(page.get_by_role("button", name="Not completely", exact=True)).to_have_count(0)
        journey.snapshot("mission-source-preserved")
        assert not media, "Lesson shortcut fetched media or a recording source"
        assert not mutations, "Lesson shortcut attempted an API mutation"
        journey.observations[-1]["fictional_focus_lesson"] = {
            "source": f"D624cf2bc existing {filename}/{key}",
            "pointer_enter_native_hash_query_and_target_focus": True,
            "next_tab_inside_folded_lesson": True,
            "same_row_and_32_44px": True,
            "original_lesson_and_mission_unchanged": True,
            "media_requests": len(media),
            "api_mutations": len(mutations),
            "authenticated_hosted_or_report_integration": False,
        }


def test_fixture_worked_clip_disclosure(browser: Browser, viewport: tuple[int, str]) -> None:
    """Each supplied Worked/Didn't clip remains reachable without changing its finding."""
    if (
        os.environ.get("WB_MODE", "fixture") != "fixture"
        or os.environ["WB_BASE_URL"].rstrip("/") != "http://127.0.0.1:3026"
    ):
        pytest.skip("Worked disclosure uses B's existing local fictional input boundary")

    def clock(ms: int) -> str:
        seconds = ms // 1000
        return f"{seconds // 60:02d}:{seconds % 60:02d}"

    with _journey(browser, viewport, "worked-clip-disclosure") as journey:
        page = journey.page
        mutations: list[str] = []
        media: list[str] = []
        reads: list[str] = []

        def observe_read(route: Route) -> None:
            request = route.request
            path = urlsplit(request.url).path
            if request.method not in {"GET", "HEAD"}:
                mutations.append(request.method)
                route.abort("blockedbyclient")
            elif (
                request.resource_type == "media"
                or path.endswith("/source")
                or (path.startswith("/v1/") and "/media/" in path)
            ):
                media.append("source-read")
                route.abort("blockedbyclient")
            else:
                if path.startswith("/v1/"):
                    reads.append("read")
                route.continue_()

        page.route("**/*", observe_read)
        journey.open("/review-fixture/report/story?view=story&section=moments")
        section = page.locator('[data-report-pillar="moments"]')
        expect(section).to_be_visible()
        columns = [
            section.get_by_role("region", name=label, exact=True)
            for label in ("What worked", "What didn't")
        ]
        rows = [column.locator("ul").first.locator(":scope > li") for column in columns]
        for group in rows:
            expect(group).to_have_count(3)
        page.evaluate("() => document.fonts.ready")
        page.wait_for_load_state("networkidle", timeout=15_000)
        # Exact B99a79943 presentation-only setup. No canonical fixture/model
        # file changes: repeat only each authored card's own original ref.
        fixture = section.evaluate("""element => {
          if (!document.querySelector('[data-full-shell-fixture="true"]'))
            throw new Error('Not the authored fictional Report');
          return [...element.querySelectorAll('section')].slice(0, 2).map((column, ci) =>
            [...column.querySelector('ul').children].map((row, ri) => {
              const key = Object.keys(row).find(key => key.startsWith('__reactFiber$'));
              let fiber = row[key];
              while (fiber && !fiber.memoizedProps?.item) fiber = fiber.return;
              const dispatch = fiber?.memoizedState?.queue?.dispatch ??
                fiber?.alternate?.memoizedState?.queue?.dispatch;
              const item = fiber?.memoizedProps.item, original = item?.what.sources[0];
              if (!dispatch || !original) throw new Error('Missing original ItemRow boundary');
              const paragraphs = [...row.querySelectorAll('p')].map(p => p.textContent);
              item.what.sources = Array.from({length: [[4,0,1],[3,2,1]][ci][ri]}, () => original);
              dispatch(true);
              return {title: item.title, sources: item.what.sources, paragraphs};
            }));
        }""")
        assert [[len(item["sources"]) for item in group] for group in fixture] == [
            [4, 0, 1],
            [3, 2, 1],
        ]
        toggles = [group.first.locator("button[aria-controls]") for group in rows]
        groups = []
        for index, toggle in enumerate(toggles):
            expect(toggle).to_have_text("Show fewer clips")
            toggle.click()
            expect(toggle).to_have_text(f"Show all {len(fixture[index][0]['sources'])} clips")
            expect(toggle).to_have_attribute("aria-expanded", "false")
            groups.append(
                rows[index].first.locator(f'[id="{toggle.get_attribute("aria-controls")}"]')
            )
            expect(groups[index].get_by_role("button")).to_have_count(2)
        expect(rows[0].nth(1).get_by_role("button")).to_have_count(0)
        expect(rows[0].nth(2).get_by_role("button")).to_have_count(1)
        expect(rows[1].nth(1).get_by_role("button")).to_have_count(2)
        expect(rows[1].nth(1).locator("button[aria-controls]")).to_have_count(0)
        expect(rows[1].nth(2).get_by_role("button")).to_have_count(1)
        before_reads = len(reads)
        toggles[0].click()
        expect(groups[0].get_by_role("button")).to_have_count(4)
        expect(groups[1].get_by_role("button")).to_have_count(2)
        toggles[1].focus()
        page.keyboard.press("Enter")
        expect(groups[1].get_by_role("button")).to_have_count(3)
        for index, group in enumerate(groups):
            buttons = group.get_by_role("button")
            item = fixture[index][0]
            expect(buttons).to_have_text(
                [f"{clock(ref['start_ms'])} · Play" for ref in item["sources"]]
            )
            for number, ref in enumerate(item["sources"]):
                button = buttons.nth(number)
                if number % 3 == 0:
                    button.click()
                else:
                    button.focus()
                    page.keyboard.press("Enter" if number % 3 == 1 else "Space")
                expect(
                    page.get_by_role("status", name="Fixture action status", exact=True)
                ).to_contain_text(
                    f"Selected {clock(ref['start_ms'])}–{clock(ref['end_ms'])} · "
                    f"{item['title']}. No audio exists in this fixture."
                )
        groups[0].get_by_role("button").last.focus()
        toggles[0].click()
        expect(toggles[0]).to_be_focused()
        expect(toggles[0]).to_have_attribute("aria-expanded", "false")
        expect(groups[0].get_by_role("button")).to_have_count(2)
        expect(groups[1].get_by_role("button")).to_have_count(3)
        toggles[0].focus()
        page.keyboard.press("Space")
        expect(groups[0].get_by_role("button")).to_have_count(4)
        for index, label in enumerate(("worked", "didnt")):
            row = rows[index].first
            row.evaluate("""element => {
              const navBottom = Math.max(0, ...[...document.querySelectorAll('[data-report-nav]')]
                .filter(nav => nav.getClientRects().length)
                .map(nav => nav.getBoundingClientRect().bottom));
              let scroller = element.parentElement;
              while (scroller && !/(auto|scroll)/.test(getComputedStyle(scroller).overflowY))
                scroller = scroller.parentElement;
              if (!scroller) throw new Error('Missing shared Report scroller');
              scroller.scrollBy({top: element.getBoundingClientRect().top - navBottom - 8,
                behavior:'instant'});
            }""")
            journey.snapshot(f"{label}-all-original-clips")
            for control, target in (
                (groups[index].get_by_role("button").last, f"{label}-tail-clip"),
                (toggles[index], f"{label}-all-fewer"),
            ):
                journey.control_target(control, target)
        for ci, group in enumerate(rows):
            expect(group).to_have_count(3)
            for ri, item in enumerate(fixture[ci]):
                assert group.nth(ri).locator("p").all_text_contents() == item["paragraphs"], (
                    "Source finding/prose changed during clip disclosure"
                )
        expect(page.locator("[data-report-pillar]")).to_have_count(6)
        assert len(reads) == before_reads and not media and not mutations
        assert journey.live_refreshes == 0, "Live source changed during Worked/Didn't disclosure"
        journey.observations[-1]["fictional_worked_clip_disclosure"] = {
            "source": "B99a79943 existing authored card refs; presentation-only repeats",
            "counts": [[len(item["sources"]) for item in group] for group in fixture],
            "first_two_all_fewer_independent_cards_and_fold_focus": True,
            "pointer_enter_space_original_displayed_bounds_title": True,
            "all_six_findings_prose_and_32_44px_preserved": True,
            "mixed_order_and_original_object_identity_browser_tested": False,
            "extra_api_reads": len(reads) - before_reads,
            "media_requests": len(media),
            "api_mutations": len(mutations),
            "canonical_payload_real_audio_or_authenticated_acceptance": False,
        }


def test_fixture_skill_clip_disclosure(browser: Browser, viewport: tuple[int, str]) -> None:
    """Every supplied fictional skill clip stays reachable, in its original order."""
    if os.environ.get("WB_MODE", "fixture") != "fixture":
        pytest.skip("Skill disclosure uses B's existing browser-only fictional source case")

    def clock(ms: int) -> str:
        seconds = ms // 1000
        return f"{seconds // 60:02d}:{seconds % 60:02d}"

    with _journey(browser, viewport, "skill-clip-disclosure") as journey:
        page = journey.page
        mutations: list[str] = []
        media: list[str] = []
        reads: list[str] = []

        def observe_read(route: Route) -> None:
            if route.request.method not in {"GET", "HEAD"}:
                mutations.append(route.request.method)
                route.abort("blockedbyclient")
            else:
                reads.append("read")
                route.continue_()

        page.route("**/v1/**", observe_read)
        page.on(
            "request",
            lambda request: media.append("media") if request.resource_type == "media" else None,
        )
        journey.open("/review-fixture/report/pillars?view=story&section=skills")
        skills = page.locator('[data-report-pillar="skills"]')
        expect(skills).to_be_visible()
        rows = skills.locator("li:has(> details > summary)")
        expect(rows).to_have_count(8)
        page.wait_for_load_state("networkidle", timeout=15000)
        # Exact browser-only source setup from B's existing disclosure harness.
        # This dev fixture has no account/recording; alter only these in-memory props.
        fixture = skills.evaluate("""element => {
            const fiberKey = Object.keys(element).find(key => key.startsWith('__reactFiber$'));
            let fiber = element[fiberKey];
            while (fiber && !fiber.memoizedProps?.documentData?.report) fiber = fiber.return;
            const report = fiber?.memoizedProps.documentData.report;
            if (!report || !document.querySelector('[data-full-shell-fixture="true"]'))
                throw new Error('No authored fictional Report props found');
            const dimensions = report.dimensions;
            const original = dimensions.map(dimension => dimension.evidence ?? []);
            const first = original[0], second = original[1];
            dimensions[0].evidence = [first[1], first[0], first[1], first[0], first[1]];
            dimensions[1].evidence = [...second, ...second, ...second];
            dimensions[2].evidence = [];
            dimensions[3].evidence = [...original[3], ...original[3]];
            return dimensions.slice(0, 4).map(d => ({
                label: d.label, sources: d.evidence, observation: d.observation}));
        }""")
        page.get_by_role("button", name="Coaching view", exact=True).click()
        page.get_by_role("button", name="Report view", exact=True).click()
        expect(skills).to_be_visible()
        for index in range(4):
            rows.nth(index).locator("summary").click()
            expect(rows.nth(index).locator("details")).to_have_attribute("open", "")
            expect(rows.nth(index)).to_contain_text(fixture[index]["observation"])
        toggles = [rows.nth(index).locator("button[aria-controls]") for index in range(2)]
        groups = []
        for index, toggle in enumerate(toggles):
            expect(toggle).to_have_text(f"Show all {len(fixture[index]['sources'])} clips")
            expect(toggle).to_have_attribute("aria-expanded", "false")
            group = rows.nth(index).locator(f'[id="{toggle.get_attribute("aria-controls")}"]')
            groups.append(group)
            expect(group.get_by_role("button")).to_have_count(4)
        expect(rows.nth(2).get_by_role("button")).to_have_count(0)
        expect(rows.nth(3).get_by_role("button")).to_have_count(4)
        expect(rows.nth(3).locator("button[aria-controls]")).to_have_count(0)
        page.wait_for_load_state("networkidle", timeout=15000)
        reads_before = len(reads)
        rows.first.evaluate("el => el.scrollIntoView({block: 'center', behavior: 'instant'})")
        journey.snapshot("first-four-clips")
        journey.control_target(toggles[0], "show-all-skill-clips")
        toggles[0].click()
        expect(groups[0].get_by_role("button")).to_have_count(5)
        expect(groups[1].get_by_role("button")).to_have_count(4)
        toggles[1].focus()
        page.keyboard.press("Enter")
        expect(groups[1].get_by_role("button")).to_have_count(6)
        for index, group in enumerate(groups):
            buttons = group.get_by_role("button")
            expect(buttons).to_have_text(
                [f"{clock(source['start_ms'])} · Play" for source in fixture[index]["sources"]]
            )
            for number, source in enumerate(fixture[index]["sources"]):
                button = buttons.nth(number)
                button.evaluate("el => el.scrollIntoView({block: 'center', behavior: 'instant'})")
                if number % 3 == 0:
                    button.click()
                else:
                    button.focus()
                    page.keyboard.press("Enter" if number % 3 == 1 else "Space")
                expect(
                    page.get_by_role("status", name="Fixture action status", exact=True)
                ).to_contain_text(
                    f"Selected {clock(source['start_ms'])}–{clock(source['end_ms'])} · "
                    f"{fixture[index]['label']}. No audio exists in this fixture."
                )
        rows.first.evaluate("el => el.scrollIntoView({block: 'center', behavior: 'instant'})")
        journey.snapshot("all-original-clips")
        journey.control_target(groups[0].get_by_role("button").last, "tail-skill-clip")
        groups[0].get_by_role("button").last.focus()
        toggles[0].click()
        expect(groups[0].get_by_role("button")).to_have_count(4)
        expect(groups[1].get_by_role("button")).to_have_count(6)
        expect(toggles[0]).to_be_focused()
        expect(toggles[0]).to_have_attribute("aria-expanded", "false")
        expect(rows.first.locator("details")).to_have_attribute("open", "")
        journey.snapshot("fold-keeps-other-skill")
        toggles[0].focus()
        page.keyboard.press("Space")
        expect(groups[0].get_by_role("button")).to_have_count(5)
        expect(toggles[0]).to_have_attribute("aria-expanded", "true")
        expect(skills.locator('a[href^="/coaching?focus="]')).to_have_count(8)
        expect(page.locator("[data-report-pillar]")).to_have_count(6)
        for index in range(4):
            expect(rows.nth(index)).to_contain_text(fixture[index]["observation"])
        assert len(reads) == reads_before, "Local skill disclosure fetched extra data"
        assert not media, "Fictional skill disclosure fetched audio"
        assert not mutations, "Fictional skill disclosure attempted an API mutation"
        journey.observations[-1]["fictional_skill_disclosure"] = {
            "source": "B's browser-only fictional native props; repeated original refs preserved",
            "source_counts": [len(row["sources"]) for row in fixture],
            "first_four_then_all_original_order": True,
            "per_skill_state_and_tail_fold_focus": True,
            "zero_four_source_rows_have_no_toggle": True,
            "pointer_enter_space_original_times_selected": True,
            "observation_labels_and_eight_coaching_links_unchanged": True,
            "extra_reads": 0,
            "media_requests": len(media),
            "api_mutations": len(mutations),
            "authenticated_or_real_audio_acceptance": False,
        }


def test_fixture_coaching_call_findings(browser: Browser, viewport: tuple[int, str]) -> None:
    """Compare only the current skill's explicit saved findings, with name/reset guards."""
    if os.environ.get("WB_MODE", "fixture") != "fixture":
        pytest.skip("Finding comparisons use D's existing fictional personal example")
    data = json.loads(
        (
            Path(__file__).resolve().parents[3]
            / "apps/sales-xray-web/app/review-fixture/coaching/sandbox.json"
        ).read_text()
    )["me"]
    points = {row["submission_id"]: row["state"] for row in data["progress"]}
    calls = data["calls"]
    skill_calls = [
        call
        for call in calls
        if call["state"] == "ready"
        and points.get(call["submission_id"]) in {"suggested", "no_suggestion"}
    ]
    findings = {
        "all": skill_calls,
        **{
            state: [call for call in skill_calls if points[call["submission_id"]] == state]
            for state in ("suggested", "no_suggestion")
        },
    }
    labels = {"suggested": "Needed work", "no_suggestion": "Skill used, nothing to fix"}
    with _journey(browser, viewport, "coaching-call-findings") as journey:
        page = journey.page
        mutations: list[str] = []

        def observe_read(route: Route) -> None:
            if route.request.method not in {"GET", "HEAD"}:
                mutations.append(route.request.method)
                route.abort("blockedbyclient")
            else:
                route.continue_()

        page.route("**/v1/**", observe_read)
        journey.open("/review-fixture/coaching?view=me")
        section = page.locator("#coaching-calls")
        search = section.get_by_role("searchbox", name="Find a call", exact=True)
        select = section.get_by_role("combobox", name="What the report found", exact=True)
        on_skill = section.get_by_role("button", name="On this skill", exact=True)
        all_calls = section.get_by_role("button", name="All calls", exact=True)
        listing = section.get_by_role("list", name="Your recent calls", exact=True)
        progress = page.locator("#coaching-progress")
        history = progress.inner_text()

        def verify(expected: list[dict[str, object]], saved: bool = True) -> None:
            rows = listing.locator("li")
            expect(rows).to_have_count(len(expected))
            titles = _call_title_links(listing, expected, include_hidden=True)
            expect(titles).to_have_text([call["call_label"] for call in expected])
            expect(section.get_by_role("status")).to_have_text(
                f"{len(expected)} call{'s' if len(expected) != 1 else ''}"
            )
            for index, call in enumerate(expected):
                expected_href = (
                    f"/coaching?call={call['submission_id']}"
                    if call["state"] == "ready"
                    else f"/analysis/calls/{call['submission_id']}"
                )
                expect(titles.nth(index)).to_have_attribute("href", expected_href)
                report = rows.nth(index).get_by_role(
                    "link",
                    name=f"Open Report for {call['call_label']}",
                    exact=True,
                    include_hidden=True,
                )
                expect(report).to_have_count(1 if call["state"] == "ready" else 0)
                if call["state"] == "ready":
                    expect(report).to_have_attribute(
                        "href", f"/analysis/calls/{call['submission_id']}"
                    )
                if saved:
                    expect(rows.nth(index)).to_contain_text(labels[points[call["submission_id"]]])
            expect(listing.locator("li:visible")).to_have_count(
                min(len(expected), 3 if journey.width == 390 else 8)
            )

        expect(select).to_have_count(0)
        on_skill.click()
        verify(findings["all"])
        expect(select).to_have_value("all")
        assert select.get_attribute("aria-controls") == listing.locator("..").get_attribute("id")
        select.select_option("suggested")
        verify(findings["suggested"])
        section.evaluate("el => el.scrollIntoView({block: 'start', behavior: 'instant'})")
        journey.snapshot("needed-work")
        journey.control_target(select, "saved-finding")
        select.select_option("no_suggestion")
        verify(findings["no_suggestion"])
        section.evaluate("el => el.scrollIntoView({block: 'center', behavior: 'instant'})")
        listing.locator("li").last.evaluate(
            "el => el.scrollIntoView({block: 'center', behavior: 'instant'})"
        )
        if journey.width == 1440:
            for row in listing.locator("li").all():
                expect(row).to_be_in_viewport(ratio=1)
        journey.snapshot("skill-used-no-fix")
        report = listing.get_by_role(
            "link", name=f"Open Report for {findings['no_suggestion'][0]['call_label']}", exact=True
        )
        journey.control_target(report, "saved-finding-report")
        match = findings["no_suggestion"][0]
        search.fill(f"  {match['call_label'].upper()}  ")
        verify([match])
        select.select_option("suggested")
        expect(listing).to_have_count(0)
        expect(section.get_by_role("status")).to_have_text("0 calls")
        expect(section).to_contain_text("Try another call name, or show all calls on this skill.")
        clear = section.get_by_role("button", name="Clear search", exact=True)
        clear.focus()
        page.keyboard.press("Enter")
        expect(search).to_be_focused()
        expect(search).to_have_value("")
        expect(select).to_have_value("suggested")
        verify(findings["suggested"])
        section.evaluate("el => el.scrollIntoView({block: 'center', behavior: 'instant'})")
        journey.snapshot("clear-keeps-finding")
        all_calls.click()
        expect(select).to_have_count(0)
        verify(calls, False)
        on_skill.focus()
        page.keyboard.press("Enter")
        expect(select).to_have_value("all")
        verify(findings["all"])
        select.select_option("no_suggestion")
        search.fill("Missing fictional call")
        shortcut = progress.get_by_role("button", name="See calls on this skill", exact=True)
        shortcut.focus()
        page.keyboard.press("Enter")
        expect(select).to_have_value("all")
        expect(search).to_have_value("")
        verify(findings["all"])
        expect(section).to_be_focused()
        page.keyboard.press("Tab")
        expect(search).to_be_focused()
        assert progress.inner_text() == history
        section.evaluate("el => el.scrollIntoView({block: 'center', behavior: 'instant'})")
        journey.snapshot("progress-restores-skill-calls")
        assert not mutations, "Fictional finding filter attempted an API mutation"
        journey.observations[-1]["fictional_call_findings"] = {
            "source": "D298f412b existing sandbox.json me.calls/progress",
            "source_counts": {state: len(rows) for state, rows in findings.items()},
            "source_names_order_ids_report_routes_preserved": True,
            "pending_and_not_covered_excluded": True,
            "name_intersection_and_clear_keeps_finding": True,
            "all_calls_and_progress_reset_finding": True,
            "section_focus_then_search_tab": True,
            "progress_unchanged": True,
            "api_mutations": len(mutations),
            "authenticated_hosted_acceptance": False,
        }


def test_fixture_summary_clips(browser: Browser, viewport: tuple[int, str]) -> None:
    """Saved summary sources select their original times without fetching audio."""
    if os.environ.get("WB_MODE", "fixture") != "fixture":
        pytest.skip("Summary clips use B's existing fictional report examples")
    source = json.loads(
        (
            Path(__file__).resolve().parents[3]
            / "apps/sales-xray-web/app/review-fixture/report/pillars/v8-fictional.json"
        ).read_text()
    )
    with _journey(browser, viewport, "summary-clips") as journey:
        page = journey.page
        mutations: list[str] = []
        media: list[str] = []

        def observe_read(route: Route) -> None:
            if route.request.method not in {"GET", "HEAD"}:
                mutations.append(route.request.method)
                route.abort("blockedbyclient")
            else:
                route.continue_()

        page.route("**/v1/**", observe_read)
        page.on(
            "request",
            lambda request: media.append("media") if request.resource_type == "media" else None,
        )
        journey.open("/review-fixture/report/pillars")
        picture = page.locator('[data-report-pillar="overview"]')
        summary = picture.get_by_role("group", name="Summary", exact=True)
        buttons = summary.get_by_role("button")
        native_summary = source["account"]["content"]["summary"]
        # Wait for the native fixture shell/style reads before its first image.
        page.wait_for_load_state("networkidle", timeout=15000)
        expect(picture).to_contain_text(native_summary)
        expect(buttons).to_have_text(["00:05–00:10", "00:26–00:31", "00:36–00:40"])
        summary.evaluate("el => el.scrollIntoView({block: 'center', behavior: 'instant'})")
        journey.snapshot("native-summary-before")
        for index, (action, span) in enumerate(
            zip(
                ("pointer", "Enter", "Space"),
                ("00:05–00:10", "00:26–00:31", "00:36–00:40"),
                strict=True,
            )
        ):
            button = buttons.nth(index)
            button.evaluate("el => el.scrollIntoView({block: 'center', behavior: 'instant'})")
            journey.control_target(button, f"native-summary-{index}")
            if action == "pointer":
                button.click()
            else:
                button.focus()
                page.keyboard.press(action)
            expect(
                page.get_by_text(
                    f"Selected {span} · Summary. No audio exists in this fixture.", exact=True
                )
            ).to_be_visible()
            expect(picture).to_contain_text(native_summary)
        summary.evaluate("el => el.scrollIntoView({block: 'center', behavior: 'instant'})")
        journey.snapshot("native-summary-selected")
        page.get_by_role("button", name="Revised Report", exact=True).click()
        expect(buttons).to_have_text(["00:00", "00:03", "00:05"])
        revised = (
            "The seller explained the purpose of the call. The delivery date remained open. "
            "Both agreed to meet Friday at 4 PM."
        )
        expect(picture).to_contain_text(revised)
        expect(page.locator("[data-report-pillar]")).to_have_count(6)
        quotes = [
            "This call is to arrange a meeting.",
            "I need to check the delivery date.",
            "Yes, Friday at 4 PM. I will bring the details.",
        ]
        for index, action in enumerate(("pointer", "Enter", "Space")):
            button = buttons.nth(index)
            button.evaluate("el => el.scrollIntoView({block: 'center', behavior: 'instant'})")
            journey.control_target(button, f"revised-summary-{index}")
            if action == "pointer":
                button.click()
            else:
                button.focus()
                page.keyboard.press(action)
            expect(page.locator('[data-synthetic-report] aside[role="status"] p')).to_have_text(
                quotes[index]
            )
            expect(picture).to_contain_text(revised)
        summary.evaluate("el => el.scrollIntoView({block: 'center', behavior: 'instant'})")
        journey.snapshot("revised-original-source")
        page.get_by_role("button", name="Older report", exact=True).click()
        expect(summary).to_have_count(0)
        picture.scroll_into_view_if_needed()
        journey.snapshot("older-no-summary-sources")
        assert not media, "Reading or selecting fictional summary clips fetched media"
        assert not mutations, "Fictional summary attempted an API mutation"
        journey.observations[-1]["fictional_summary_clips"] = {
            "native_ordered_spans": [[5400, 10300], [26200, 31000], [36000, 40100]],
            "revised_original_quote_selection": True,
            "pointer_enter_space_and_32_44px": True,
            "summary_prose_unchanged": True,
            "older_no_ref_has_no_clip_row": True,
            "duplicate_and_different_summary_browser_source": (
                "not supplied; builder unit evidence separate"
            ),
            "media_requests": len(media),
            "api_mutations": len(mutations),
            "real_audio_or_provider_acceptance": False,
        }


def test_fixture_team_shared_dates(browser: Browser, viewport: tuple[int, str]) -> None:
    """Keep the existing design records' latest-call and sharing dates distinct."""
    if os.environ.get("WB_MODE", "fixture") != "fixture":
        pytest.skip("Shared-date checks use D's existing synthetic design records")
    data = json.loads(
        (
            Path(__file__).resolve().parents[3]
            / "apps/sales-xray-web/app/review-fixture/coaching/sandbox.json"
        ).read_text()
    )["team"]
    with _journey(browser, viewport, "team-shared-dates") as journey:
        page = journey.page
        mutations: list[str] = []

        def observe_read(route: Route) -> None:
            if route.request.method not in {"GET", "HEAD"}:
                mutations.append(route.request.method)
                route.abort("blockedbyclient")
            else:
                route.continue_()

        page.route("**/v1/**", observe_read)
        journey.open("/review-fixture/coaching?view=team")
        team = page.get_by_role("region", name=re.compile(r"^Who needs help with what"))
        search = team.get_by_role("searchbox", name="Find a rep", exact=True)
        area = team.get_by_role("combobox", name="Coaching area", exact=True)
        rows = team.get_by_role(
            "list", name="Reps and their current focus", exact=True
        ).get_by_role("listitem")
        historical = page.get_by_role("list", name="Coaching areas", exact=True).inner_text()
        expect(rows).to_have_count(len(data["reps"]))
        for index, rep in enumerate(data["reps"]):
            row = rows.nth(index)
            expect(row).to_contain_text(rep["name"])
            expect(row).to_contain_text(rep["focus_label"])
            expect(row).to_contain_text(f"{rep['calls']} calls")
            for field, label in (("latest_call_at", "Latest call"), ("shared_at", "Shared")):
                stamp = datetime.fromisoformat(rep[field])
                expect(row).to_contain_text(f"{label} {stamp.day} Sept {stamp.year}")
            expect(row.get_by_role("link")).to_have_attribute(
                "href", f"/coaching?person={rep['person_id']}"
            )
        team.evaluate("el => el.scrollIntoView({block: 'center', behavior: 'instant'})")
        journey.snapshot("distinct-source-dates")
        journey.control_target(search, "find-shared-rep")
        journey.control_target(area, "shared-area")
        journey.control_target(rows.last.get_by_role("link"), "dated-rep")
        search.fill(f"  {data['reps'][-1]['name'].upper()}  ")
        expect(rows).to_have_count(1)
        expect(rows.first).to_contain_text("Latest call 5 Sept 2026")
        expect(rows.first).to_contain_text("Shared 1 Sept 2026")
        reset = team.get_by_role("button", name="Clear filters", exact=True)
        journey.control_target(reset, "reset-dated-rep")
        reset.focus()
        page.keyboard.press("Enter")
        expect(search).to_be_focused()
        expect(rows).to_have_count(2)
        assert (
            page.get_by_role("list", name="Coaching areas", exact=True).inner_text() == historical
        )
        journey.snapshot("date-filter-reset")
        assert not mutations, "Design date checks attempted an API mutation"
        journey.observations[-1]["fictional_shared_dates"] = {
            "source": "D's existing Design review sandbox.json team",
            "latest_and_share_dates_distinct": True,
            "source_names_counts_focus_routes_unchanged": True,
            "reset_focus_and_targets_preserved": True,
            "absent_latest_date_browser_case": "not supplied; unit evidence only",
            "api_mutations": len(mutations),
            "authenticated_sharing_acceptance": False,
        }


def test_fixture_person_call_search(browser: Browser, viewport: tuple[int, str]) -> None:
    """Find every returned call name without changing source rows or other panels."""
    if os.environ.get("WB_MODE", "fixture") != "fixture":
        pytest.skip("Person call search uses A's existing fictional read-only harness")
    if (
        os.environ.get("WB_STORAGE_STATE")
        or os.environ["WB_BASE_URL"].rstrip("/") != "http://127.0.0.1:3026"
    ):
        pytest.fail("Fictional person replies require shared dev3026 with no session")
    person_id = "00000000-0000-4000-8000-000000000003"
    now = datetime.now(UTC)
    listed = [
        {
            "id": f"00000000-0000-4000-8000-{index + 101:012}",
            "owner_person_id": person_id,
            "owner_name": "Neha Kulkarni",
            "label": None
            if index == 6
            else "मराठी · Budget review"
            if index == 11
            else "Discovery · Same prospect"
            if index in (0, 10)
            else f"Discovery · Prospect {index}",
            "created_at": (now - timedelta(days=index + 1)).isoformat(),
            "duration_seconds": 0 if index == 10 else 900,
            "state": "queued" if index == 10 else "completed",
            "has_report": index != 10,
        }
        for index in range(12)
    ]
    with _journey(browser, viewport, "person-call-search") as journey:
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
            if url.path == f"/v1/organisation/members/{person_id}/activity":
                reply = {
                    "status": 200,
                    "body": {
                        "person_id": person_id,
                        "totals": {"calls": 64, "recorded_minutes": 720, "reports_ready": 60},
                        "weeks": [
                            {
                                "start": (now - timedelta(weeks=12 - index)).isoformat(),
                                "calls": 9 if index == 11 else 5,
                                "recorded_minutes": 60,
                                "reports_ready": 5,
                            }
                            for index in range(12)
                        ],
                        "calls": listed,
                    },
                }
            elif url.path == f"/v1/me/coaching/people/{person_id}":
                reply = _fictional_api_reply("GET", "/v1/me/coaching", "")
                reply["body"] = {
                    **reply["body"],
                    "person_id": person_id,
                    "tenant_id": "22222222-2222-4222-8222-222222222222",
                    "sandbox": True,
                }
            elif re.fullmatch(r"/v1/conversation/acquisition/submissions/[^/]+/report", url.path):
                reply = {
                    "status": 200,
                    "body": {
                        "report": {
                            "content": {
                                "overview": {
                                    "outcome": {"kind": "follow_up"},
                                    "final_assessment": {"fix_first": "Ask what the budget is."},
                                },
                                "dimensions": [
                                    {
                                        "dimension_id": "discovery",
                                        "label": "Discovery",
                                        "status": "observed",
                                    }
                                ],
                            }
                        }
                    },
                }
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
        journey.open(f"/organisation/people/{person_id}")
        panel = page.get_by_role("region", name=re.compile(r"^Calls.*12 in the last 12 weeks$"))
        search = panel.get_by_role("searchbox", name="Search these calls", exact=True)
        clear = panel.get_by_role("button", name="Clear search", exact=True)
        rows = panel.locator("li a")
        expect(rows).to_have_count(8)
        # Match A's existing harness: allow its initial finite detail reads to settle.
        page.wait_for_timeout(800)
        figures = page.locator('[aria-label="Last 12 weeks"]').inner_html()

        def row_values() -> list[object]:
            return rows.evaluate_all(
                "els => els.map(el => ({html: el.innerHTML, href: el.getAttribute('href')}))"
            )

        baseline = row_values()
        reads_before = len(reads)
        search.fill("  dIsCoVeRy  ")
        expect(rows).to_have_count(10)
        expect(panel.get_by_role("status")).to_have_text("Matches: 10 of 12 listed calls")
        assert rows.evaluate_all("els => els.map(el => el.getAttribute('href'))") == [
            f"/analysis/calls/{call['id']}"
            for call in listed
            if call["label"] and call["label"].startswith("Discovery")
        ]
        search.fill("same prospect")
        expect(rows).to_have_count(2)
        for index, call in enumerate((listed[0], listed[10])):
            expect(rows.nth(index)).to_have_attribute("href", f"/analysis/calls/{call['id']}")
        expect(rows.last).to_contain_text("Queued")
        expect(rows.last).to_contain_text("—")
        expect(panel).to_contain_text("Searching the newest 12 of 64 calls.")
        panel.evaluate("el => el.scrollIntoView({block: 'center', behavior: 'instant'})")
        journey.snapshot("duplicate-call-names")
        for control, label in (
            (search, "search-these-calls"),
            (clear, "clear-call-search"),
            (rows.last, "queued-call"),
        ):
            journey.control_target(control, label)
        search.fill("Missing fictional prospect")
        expect(rows).to_have_count(0)
        expect(panel.get_by_text("No listed calls match this name.", exact=True)).to_be_visible()
        expect(panel).to_contain_text("Searching the newest 12 of 64 calls.")
        journey.snapshot("quiet-no-match")
        clear.focus()
        page.keyboard.press("Enter")
        expect(search).to_be_focused()
        assert row_values() == baseline
        more = panel.get_by_role("button", name="Show all 12 calls", exact=True)
        expect(more).to_have_attribute("aria-expanded", "false")
        more.click()
        expect(rows).to_have_count(12)
        expanded = row_values()
        search.fill("मराठी")
        expect(rows).to_have_count(1)
        expect(rows.first).to_contain_text("मराठी · Budget review")
        journey.snapshot("devanagari-tail-call")
        clear.click()
        expect(search).to_be_focused()
        assert row_values() == expanded
        expect(panel.get_by_role("button", name="Show fewer", exact=True)).to_have_attribute(
            "aria-expanded", "true"
        )
        expect(panel).to_contain_text("Showing the newest 12 of 64 calls.")
        assert page.locator('[aria-label="Last 12 weeks"]').inner_html() == figures
        assert len(reads) == reads_before, "Local call search unexpectedly fetched new data"
        panel.scroll_into_view_if_needed()
        journey.snapshot("expanded-restored")
        assert not mutations, "Fictional person call search attempted an API mutation"
        journey.observations[-1]["fictional_person_call_search"] = {
            "source": "A2eee20a9's existing twelve-call fictional API harness",
            "duplicate_names_keep_distinct_source_routes_status": True,
            "source_order_and_row_markup_preserved": True,
            "devanagari_tail_match_and_partial_scope": True,
            "quiet_no_match_and_prior_8_all_state": True,
            "pointer_enter_clear_focus": True,
            "extra_reads": 0,
            "figures_unchanged": True,
            "api_mutations": len(mutations),
            "authenticated_hosted_acceptance": False,
        }


def test_fixture_insights_people_search(browser: Browser, viewport: tuple[int, str]) -> None:
    """Search the full returned list, preserving duplicate identities and disclosure."""
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
    # Requested duplicate-name check: retain both distinct original source keys.
    people[54] = {**people[54], "name": people[-1]["name"]}
    overview = {
        **fixture["overview"],
        "totals": {**fixture["overview"]["totals"], "people": len(people)},
        "people": people,
        "pending": 0,
        "facets": {**fixture["overview"]["facets"], "people": people},
    }
    endpoint = "/v1/conversation/acquisition/insights"
    with _journey(browser, viewport, "insights-people-search") as journey:
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
        search = page.get_by_role("searchbox", name="Search people", exact=True)
        clear = page.get_by_role("button", name="Clear search", exact=True)
        more = page.get_by_role("button", name="Show more", exact=True)
        fewer = page.get_by_role("button", name="Show fewer", exact=True)
        status = page.get_by_role("status").filter(has_text=re.compile(r"people$"))
        panel = page.get_by_role("region", name=re.compile(r"^People and teams"))
        expect(names).to_have_text([person["name"] for person in people[:50]])
        expect(clear).to_be_disabled()
        figures = page.get_by_role("region", name="This period", exact=True).inner_text()
        address = page.url
        reads_before = len(reads)
        search.fill("  FICTIONAL REP 65  ")
        expect(names).to_have_text([people[54]["name"], people[-1]["name"]])
        expect(status).to_have_text("Matches: 2 of 65 people")
        expect(surface.get_by_role("link", name=re.compile(r"^Open .+’s profile$"))).to_have_count(
            0
        )
        panel.evaluate("el => el.scrollIntoView({block: 'center', behavior: 'instant'})")
        journey.snapshot("duplicate-tail-names")
        for control, label in (
            (search, "search-people"),
            (clear, "clear-search"),
            (names.last, "tail-person"),
        ):
            journey.control_target(control, label)
        clear.focus()
        page.keyboard.press("Enter")
        expect(search).to_be_focused()
        expect(search).to_have_value("")
        expect(names).to_have_text([person["name"] for person in people[:50]])
        expect(more).to_have_attribute("aria-expanded", "false")
        more.click()
        search.fill("fictional rep")
        expect(names).to_have_text([person["name"] for person in people])
        expect(status).to_have_text("Matches: 65 of 65 people")
        expect(fewer).to_have_count(0)
        names.last.scroll_into_view_if_needed()
        journey.snapshot("all-matching-source-order")
        clear.click()
        expect(search).to_be_focused()
        expect(names).to_have_count(65)
        expect(fewer).to_have_attribute("aria-expanded", "true")
        search.fill("Missing fictional name")
        expect(page.get_by_text("No people match this name.", exact=True)).to_be_visible()
        expect(status).to_have_text("Matches: 0 of 65 people")
        expect(surface).to_have_count(0)
        panel.scroll_into_view_if_needed()
        journey.snapshot("quiet-no-match")
        clear.click()
        expect(search).to_be_focused()
        expect(names).to_have_text([person["name"] for person in people])
        assert len(reads) == reads_before, "Local search unexpectedly fetched new data"
        assert page.url == address
        assert page.get_by_role("region", name="This period", exact=True).inner_text() == figures
        # Both equal display names must select their own original source key.
        for person in (people[54], people[-1]):
            search.fill(person["name"])
            index = 0 if person["key"] == people[54]["key"] else 1
            with page.expect_response(
                lambda response, key=person["key"]: (
                    urlsplit(response.url).path == endpoint
                    and parse_qs(urlsplit(response.url).query).get("person") == [key]
                )
            ) as filtered:
                names.nth(index).click()
            assert filtered.value.status == 200
            expect(page.get_by_role("combobox", name="Person", exact=True)).to_have_value(
                person["key"]
            )
            assert parse_qs(urlsplit(page.url).query).get("person") == [person["key"]]
        search.scroll_into_view_if_needed()
        journey.snapshot("duplicate-key-selection")
        journey.observations[-1]["fictional_insights_search"] = {
            "source": "G65-person harness with requested duplicate display name at source55/65",
            "both_original_keys_selected": True,
            "trimmed_case_insensitive_tail_match": True,
            "all_matches_source_order_preserved": True,
            "empty_state_and_clear_focus": True,
            "both_prior_disclosure_states_restored": True,
            "local_search_reads": 0,
            "figures_and_profile_suppression_preserved": True,
            "api_mutations": len(mutations),
            "authenticated_hosted_acceptance": False,
        }
        assert not mutations, "Fictional Insights search attempted an API mutation"


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


def test_fixture_team_missing_focus(browser: Browser, viewport: tuple[int, str]) -> None:
    """Filter existing reps with no focus without changing history or source dates."""
    if os.environ.get("WB_MODE", "fixture") != "fixture":
        pytest.skip("Missing-focus checks use D's existing fictional example")
    data = json.loads(
        (
            Path(__file__).resolve().parents[3]
            / "apps/sales-xray-web/app/review-fixture/coaching/sandbox-team.json"
        ).read_text()
    )["team"]
    missing = [data["reps"][8], data["reps"][19]]
    with _journey(browser, viewport, "team-missing-focus") as journey:
        page = journey.page
        mutations: list[str] = []

        def observe_read(route: Route) -> None:
            if route.request.method not in {"GET", "HEAD"}:
                mutations.append(route.request.method)
                route.abort("blockedbyclient")
            else:
                route.continue_()

        page.route("**/v1/**", observe_read)
        journey.open("/review-fixture/coaching?data=sandbox&view=team&example=no-focus-reps")
        team = page.get_by_role("region", name=re.compile(r"^Who needs help with what"))
        search = team.get_by_role("searchbox", name="Find a rep", exact=True)
        area = team.get_by_role("combobox", name="Coaching area", exact=True)
        reset = team.get_by_role("button", name="Clear filters", exact=True)
        listing = team.get_by_role("list", name="Reps and their current focus", exact=True)
        rows = listing.get_by_role("listitem")
        links = listing.get_by_role("link")
        totals = page.get_by_role("list", name="Coaching areas", exact=True)
        history = totals.inner_text()
        expect(links).to_have_count(8)

        def assert_reps(expected: list[dict[str, object]], no_focus: bool) -> None:
            expect(rows).to_have_count(len(expected))
            for index, rep in enumerate(expected):
                row = rows.nth(index)
                expect(row).to_contain_text(str(rep["name"]))
                expect(row).to_contain_text(
                    "No focus shown" if no_focus else str(rep["focus_label"])
                )
                if no_focus:
                    expect(row).not_to_contain_text(str(rep["focus_label"]))
                expect(row).to_contain_text(f"{rep['calls']} calls")
                stamp = datetime.fromisoformat(str(rep["latest_call_at"]))
                month = "Sept" if stamp.month == 9 else stamp.strftime("%b")
                expect(row).to_contain_text(f"Latest call {stamp.day} {month} {stamp.year}")
                expect(row).not_to_contain_text("Shared ")
                expect(links.nth(index)).to_have_attribute(
                    "href", f"/coaching?person={rep['person_id']}"
                )

        team.get_by_role("button", name="Show all 60 people", exact=True).click()
        expect(links).to_have_count(60)
        area.select_option("no-focus")
        assert_reps(missing, True)
        expect(team.get_by_role("status")).to_have_text("2 reps")
        expect(team.get_by_role("button", name="Show fewer people", exact=True)).to_have_count(0)
        team.evaluate("el => el.scrollIntoView({block: 'center', behavior: 'instant'})")
        journey.snapshot("missing-focus-source-reps")
        for control, label in (
            (search, "find-rep"),
            (area, "no-focus-filter"),
            (reset, "reset-filter"),
            (links.last, "no-focus-person"),
        ):
            journey.control_target(control, label)
        if journey.width == 390:
            assert abs(area.bounding_box()["y"] - reset.bounding_box()["y"]) < 1, (
                "Phone area and reset left their shared row"
            )
        search.fill(f"  {missing[-1]['name'].upper()}  ")
        assert_reps([missing[-1]], True)
        expect(team.get_by_role("status")).to_have_text("1 rep")
        journey.snapshot("named-missing-focus")
        search.fill("Missing fictional rep")
        expect(team.get_by_role("status")).to_have_text("0 reps")
        expect(listing).to_have_count(0)
        journey.snapshot("quiet-no-match")
        reset.focus()
        page.keyboard.press("Enter")
        expect(search).to_be_focused()
        expect(search).to_have_value("")
        expect(area).to_have_value("all")
        assert_reps(data["reps"][:8], False)
        area.select_option("no-focus")
        search.fill(str(missing[0]["name"]))
        assert_reps([missing[0]], True)
        reset.click()
        expect(search).to_be_focused()
        assert_reps(data["reps"][:8], False)
        assert totals.inner_text() == history
        team.scroll_into_view_if_needed()
        journey.snapshot("restored-source-reps")
        journey.observations[-1]["fictional_missing_focus"] = {
            "source": "D's existing no-focus-reps example changes only rep8/19 focus fields",
            "source_names_calls_dates_routes_preserved": True,
            "historical_totals_unchanged": True,
            "no_invented_share_dates": True,
            "pointer_enter_reset_focus_and_compact_list": True,
            "api_mutations": len(mutations),
            "distinct_shared_and_absent_latest_dates": "not supplied by this fixture",
            "authenticated_hosted_acceptance": False,
        }
        assert not mutations, "Missing-focus fixture attempted an API mutation"


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
        people.evaluate("el => el.scrollIntoView({block: 'center', behavior: 'instant'})")
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
