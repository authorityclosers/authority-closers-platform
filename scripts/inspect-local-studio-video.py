"""Bounded, read-only Coach Studio browser readiness probe.

The probe uses one fresh headless Playwright context, normal local form login,
and a route guard that permits only local GET/HEAD requests plus the ordinary
login/context POSTs. It never selects a file or submits a course mutation.
Credential values, form values, query strings, and signed locators are never
written to the proof or console output.
"""

from __future__ import annotations

import argparse
import json
import os
import re
from contextlib import suppress
from datetime import UTC, datetime
from pathlib import Path
from urllib.parse import urlsplit

from playwright.sync_api import Page, Response, Route, sync_playwright

ROOT = Path(__file__).resolve().parents[1]
SANDBOX = ROOT / ".tmp" / "local-platform" / "sandbox.json"
OUTPUT_ROOT = ROOT / ".tmp" / "local-platform" / "new" / "scanner-video-browser"
COACH_ORIGIN = "http://coach.localhost:3102"
API_ORIGIN = "http://127.0.0.1:8000"
LOGIN_WRITES = {"/v1/auth/password/login", "/v1/context"}
SAFE_TEXT = re.compile(
    r"(?:https?://|bearer\s+|password|token|secret|cookie|authorization)[^\s]*", re.I
)
UUID_PATH = re.compile(r"/[0-9a-fA-F]{8}(?:-[0-9a-fA-F]{4}){3}-[0-9a-fA-F]{12}(?=/|$)")


def compact(value: str, limit: int = 180) -> str:
    return SAFE_TEXT.sub("[redacted]", " ".join(value.split()))[:limit]


def wait_settled(page: Page, timeout_ms: int) -> None:
    with suppress(Exception):
        page.wait_for_load_state("networkidle", timeout=timeout_ms)
        # Next development pages may keep a hot-reload connection open. The
        # bounded DOM settle loop below remains the useful readiness signal.
    for _ in range(max(1, timeout_ms // 500)):
        if not page.locator(".studio-boundary:visible").count():
            return
        page.wait_for_timeout(500)


def wait_upload_capability(page: Page, timeout_ms: int) -> bool:
    """Let the read-only capability GET finish before capturing the editor."""

    for _ in range(max(1, timeout_ms // 500)):
        if not page.get_by_text("Checking upload availability", exact=False).count():
            return True
        page.wait_for_timeout(500)
    return False


def page_metrics(page: Page) -> dict[str, object]:
    return page.evaluate(
        r"""
        () => {
          const width = innerWidth;
          const visible = [...document.querySelectorAll(
            'a,button,input,select,textarea,[role="button"],[role="link"]'
          )]
            .filter((element) => {
              const style = getComputedStyle(element);
              const rect = element.getBoundingClientRect();
              return style.display !== 'none' && style.visibility !== 'hidden' &&
                rect.width > 0 && rect.height > 0;
            });
          const outside = visible.filter((element) => {
            const rect = element.getBoundingClientRect();
            return rect.left < -1 || rect.right > width + 1;
          }).length;
          return {
            viewport: width,
            document_scroll_width: document.documentElement.scrollWidth,
            body_scroll_width: document.body.scrollWidth,
            horizontal_overflow: document.documentElement.scrollWidth > width,
            visible_actions_outside_viewport: outside,
          };
        }
        """
    )


def inventory(page: Page) -> dict[str, object]:
    return page.evaluate(
        r"""
        () => {
          const visible = (element) => {
            const style = getComputedStyle(element);
            const rect = element.getBoundingClientRect();
            return style.display !== 'none' && style.visibility !== 'hidden' &&
              rect.width > 0 && rect.height > 0;
          };
          const label = (element) => (element.getAttribute('aria-label') ||
            element.innerText || element.getAttribute('title') ||
            element.getAttribute('placeholder') || '').replace(/\s+/g, ' ').trim().slice(0, 120);
          const controls = [...document.querySelectorAll(
            'a,button,input,select,textarea,[role="button"],[role="link"]'
          )].filter(visible).slice(0, 100).map((element) => ({
            tag: element.tagName.toLowerCase(),
            role: element.getAttribute('role'),
            type: element.getAttribute('type'),
            name: element.getAttribute('name'),
            aria_label: element.getAttribute('aria-label'),
            label: label(element),
            // Deliberately omit every input value and every href/query string.
          }));
          const text = (selector) => [...document.querySelectorAll(selector)]
            .filter(visible).map((element) => (element.innerText || '').replace(/\s+/g, ' ').trim())
            .filter(Boolean).slice(0, 30);
          return {
            headings: text('h1,h2,h3'),
            buttons: text('button,[role="button"]'),
            alerts: text('[role="alert"],[role="status"]'),
            controls,
          };
        }
        """
    )


def focus_snapshot(page: Page) -> dict[str, str | None]:
    return page.evaluate(
        r"""
        () => {
          const element = document.activeElement;
          return {
            tag: element?.tagName?.toLowerCase() || null,
            role: element?.getAttribute('role') || null,
            aria_label: element?.getAttribute('aria-label') || null,
            text: (element?.innerText || '').replace(/\s+/g, ' ').trim().slice(0, 100),
          };
        }
        """
    )


def capture(
    page: Page,
    output: Path,
    *,
    name: str,
    width: int,
    height: int,
    color_scheme: str,
    reduced_motion: bool,
) -> dict[str, object]:
    page.set_viewport_size({"width": width, "height": height})
    page.emulate_media(
        color_scheme=color_scheme,
        reduced_motion="reduce" if reduced_motion else "no-preference",
    )
    page.wait_for_timeout(250)
    screenshot = output / f"{name}.png"
    page.screenshot(path=str(screenshot), full_page=False)
    return {
        "name": name,
        "viewport": {"width": width, "height": height},
        "color_scheme": color_scheme,
        "reduced_motion": reduced_motion,
        "path": UUID_PATH.sub("/[id]", urlsplit(page.url).path),
        "metrics": page_metrics(page),
        "inventory": inventory(page),
        "screenshot": str(screenshot),
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--mode",
        choices=("live",),
        default="live",
        help="Inspect the actual local Coach app; no synthetic route fixture exists in this probe.",
    )
    parser.add_argument(
        "--timeout-seconds",
        type=int,
        choices=range(10, 121),
        default=45,
        help="Bound each navigation/readiness wait (10-120 seconds).",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    password = os.environ.get("AC_LOCAL_BROWSER_TEST_PASSWORD")
    if not password:
        raise SystemExit("AC_LOCAL_BROWSER_TEST_PASSWORD is required via the DPAPI launcher")
    if not SANDBOX.is_file():
        raise SystemExit("The disposable local sandbox manifest is missing")
    with SANDBOX.open(encoding="utf-8") as stream:
        sandbox = json.load(stream)
    tenant_id = sandbox.get("academy_tenant_id")
    program_id = sandbox.get("studio_program_id")
    if not isinstance(tenant_id, str) or not isinstance(program_id, str):
        raise SystemExit("The disposable local sandbox manifest has no Studio identifiers")

    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    output = OUTPUT_ROOT / f"coach-live-{stamp}"
    output.mkdir(parents=True, exist_ok=False)
    timeout_ms = args.timeout_seconds * 1000
    blocked: list[dict[str, str]] = []
    responses: list[dict[str, object]] = []
    console_counts: dict[str, int] = {}
    console_messages: list[dict[str, str]] = []
    records: list[dict[str, object]] = []
    proof: dict[str, object]

    def guard(route: Route) -> None:
        request = route.request
        parsed = urlsplit(request.url)
        origin = f"{parsed.scheme}://{parsed.netloc}"
        allowed = origin in {COACH_ORIGIN, API_ORIGIN} and request.method in {"GET", "HEAD"}
        allowed = allowed or (
            origin in {COACH_ORIGIN, API_ORIGIN}
            and request.method == "POST"
            and parsed.path in LOGIN_WRITES
        )
        if allowed:
            route.continue_()
            return
        blocked.append({"method": request.method, "origin": origin, "path": parsed.path})
        route.abort()

    def record_response(response: Response) -> None:
        request = response.request
        parsed = urlsplit(response.url)
        origin = f"{parsed.scheme}://{parsed.netloc}"
        if origin in {COACH_ORIGIN, API_ORIGIN}:
            responses.append(
                {
                    "method": request.method,
                    "origin": origin,
                    "path": UUID_PATH.sub("/[id]", parsed.path),
                    "status": response.status,
                }
            )

    try:
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(headless=True)
            context = browser.new_context(viewport={"width": 1440, "height": 1000})
            page = context.new_page()
            page.route("**/*", guard)
            page.on("response", record_response)
            page.on(
                "console",
                lambda message: (
                    console_counts.__setitem__(
                        message.type, console_counts.get(message.type, 0) + 1
                    ),
                    console_messages.append(
                        {"type": message.type, "text": compact(message.text, 900)}
                    )
                    if message.type in {"error", "warning"}
                    else None,
                ),
            )
            page.on(
                "pageerror",
                lambda error: console_messages.append(
                    {"type": "pageerror", "text": compact(str(error), 900)}
                ),
            )
            page.goto(
                f"{COACH_ORIGIN}/login",
                wait_until="domcontentloaded",
                timeout=timeout_ms,
            )
            wait_settled(page, timeout_ms)
            page.screenshot(path=str(output / "login-before.png"), full_page=False)
            page.get_by_label("Email address", exact=True).fill("coach@ac.localhost")
            page.get_by_label("Password", exact=True).fill(password)
            page.get_by_label("Local tenant ID", exact=True).fill(tenant_id)
            page.get_by_role("button", name="Sign in", exact=True).click()
            page.wait_for_url(
                lambda url: (
                    urlsplit(url).netloc == "coach.localhost:3102"
                    and urlsplit(url).path == "/studio"
                ),
                timeout=timeout_ms,
            )
            wait_settled(page, timeout_ms)
            records.append(
                capture(
                    page,
                    output,
                    name="landing-1440-light",
                    width=1440,
                    height=1000,
                    color_scheme="light",
                    reduced_motion=False,
                )
            )

            course_path = f"/studio/programs/{program_id}"
            page.goto(
                f"{COACH_ORIGIN}{course_path}", wait_until="domcontentloaded", timeout=timeout_ms
            )
            wait_settled(page, timeout_ms)
            wait_upload_capability(page, timeout_ms)
            for scheme in ("light", "dark"):
                for width, height in ((1440, 1000), (768, 900), (390, 844), (320, 844)):
                    records.append(
                        capture(
                            page,
                            output,
                            name=f"course-{width}-{scheme}",
                            width=width,
                            height=height,
                            color_scheme=scheme,
                            reduced_motion=width <= 390,
                        )
                    )
            page.set_viewport_size({"width": 390, "height": 844})
            page.locator("body").focus()
            focus_sequence = []
            for _ in range(8):
                page.keyboard.press("Tab")
                focus_sequence.append(focus_snapshot(page))
            proof = {
                "status": "passed",
                "mode": args.mode,
                "environment": "fresh headless Playwright context",
                "actual_vs_fixture": "actual local Coach UI; no route fixture or upload",
                "origin": COACH_ORIGIN,
                "route": "/studio/programs/[sandbox studio_program_id]",
                "identity": "synthetic local Coach (credential not recorded)",
                "records": records,
                "keyboard": {"viewport": 390, "focus_sequence": focus_sequence},
                "blocked_requests": blocked,
                "responses": responses[-120:],
                "console_counts": console_counts,
                "console_messages": console_messages[-40:],
                "captured_at": datetime.now(UTC).isoformat(),
            }
            page.close()
            context.close()
            browser.close()
    except Exception as error:
        proof = {
            "status": "incomplete",
            "mode": args.mode,
            "environment": "fresh headless Playwright context",
            "actual_vs_fixture": "actual local Coach UI; no route fixture or upload",
            "origin": COACH_ORIGIN,
            "identity": "synthetic local Coach (credential not recorded)",
            "records": records,
            "blocked_requests": blocked,
            "responses": responses[-120:],
            "console_counts": console_counts,
            "console_messages": console_messages[-40:],
            "error_type": type(error).__name__,
            "error": compact(str(error)),
            "captured_at": datetime.now(UTC).isoformat(),
        }

    (output / "proof.json").write_text(json.dumps(proof, indent=2), encoding="utf-8")
    print(
        json.dumps(
            {
                "status": proof["status"],
                "output": str(output),
                "records": len(records),
                "blocked_requests": len(blocked),
                "console_types": len(console_counts),
            }
        )
    )
    return 0 if proof["status"] == "passed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
