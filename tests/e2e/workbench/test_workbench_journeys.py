"""Opt-in browser acceptance on an existing dev/staging server; never starts one."""

from __future__ import annotations

import json
import os
import re
from collections.abc import Iterator
from contextlib import contextmanager, suppress
from dataclasses import dataclass, field
from datetime import UTC, datetime
from html import unescape
from http.cookiejar import HTTPONLY_ATTR, LoadError, MozillaCookieJar
from pathlib import Path
from urllib.parse import urlsplit
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
    observations: list[dict[str, object]] = field(default_factory=list)
    main_navigations: int = 0
    live_refreshes: int = 0

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
              for (const el of document.querySelectorAll('main *, [data-report-modes] *')) {
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
                const cssSize = parseFloat(style.fontSize);
                const size = cssSize * scale(el);
                if (size < 11.99) undersized.push({tag: el.tagName, size, cssSize,
                  class: typeof el.className === 'string' ? el.className : '',
                  width: r.width, height: r.height});
              }
              return {viewport: innerWidth, document: root.scrollWidth,
                body: document.body.scrollWidth, undersized,
                busy: document.querySelectorAll('[aria-busy="true"]').length};
            }"""
        )
        self.observations.append({"step": step, "screenshot": str(path), **metrics})
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
        assert (
            not self.page.locator("nextjs-portal").get_by_text("Runtime Error", exact=False).count()
        ), "Next runtime error overlay is present"

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
        accept_downloads=True,
    )
    context.add_init_script(f"localStorage.setItem('sales-xray:theme', {json.dumps(theme)});")
    page = context.new_page()
    page.set_default_timeout(15_000)
    journey = Journey(page, context, name, width, theme, directory)
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
        if "[Fast Refresh]" in message.text:
            journey.live_refreshes += 1

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
            "runtime_errors": journey.runtime_errors,
            "server_errors": journey.server_errors,
            "visual_errors": journey.visual_errors,
            "fixture_outcome_requests": journey.fixture_outcome_requests,
            "outcome_persistence": journey.outcome_persistence,
            "observations": journey.observations,
        }
        (directory / f"{name}-{width}-{theme}.json").write_text(json.dumps(receipt, indent=2))
        context.close()


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
    # Read generated OOXML text without an XML parser or entity resolution.
    paragraphs = [
        "".join(
            unescape(text)
            for text in re.findall(r"<w:t(?:\s[^>]*)?>(.*?)</w:t>", paragraph, re.DOTALL)
        )
        for paragraph in re.findall(r"<w:p(?:\s[^>]*)?>(.*?)</w:p>", document, re.DOTALL)
    ]
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
            editor.get_by_label("Why was it lost?", exact=True).fill(reason)
            editor.get_by_role("button", name="Save", exact=True).click()
        elif key == "follow-up":
            editor.get_by_label("Follow-up date", exact=True).fill("")
            editor.get_by_role("button", name="Save", exact=True).click()
            expect(editor.get_by_role("alert")).to_contain_text("Pick a follow-up date.")
            expect(badge).to_have_text("Lost")
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
        expect(
            page.locator('[data-report-pillar="facts"]').get_by_text(status, exact=True)
        ).to_be_visible()
        _switch_report_view(page, "Document view")
        outcome = _document_preview(page).locator('[data-report-mode-section="overview"]')
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
        .locator('[data-report-mode-section="overview"]')
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
        journey.snapshot("document")
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
        _switch_report_view(page, "Report view")
        expect(page.locator('[data-report-modes][data-view="story"]')).to_be_visible()
        journey.snapshot("returned")
        if journey.fixture:
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
            personal.click()
            expect(personal).to_have_attribute("aria-pressed", "true", timeout=15_000)
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
        journey.snapshot("team")
        if journey.fixture:
            page.get_by_role("button", name="AC Sandbox", exact=True).click()
            journey.snapshot("sandbox-team")
            page.get_by_role("button", name="One rep", exact=True).click()
            expect(
                page.get_by_role(
                    "heading",
                    name=re.compile(r"^What (?:You|They) Should Work On Now(?:\s|$)"),
                )
            ).to_be_visible()
            journey.snapshot("sandbox-rep")
