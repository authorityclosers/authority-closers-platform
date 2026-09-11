"""Normal local learner login, release inbox, and server receipt browser proof.

Only mutation: marking the compiled release note read for a synthetic learner.
No receipt resets, direct SQL, credentials in output, or remote requests.
"""

from __future__ import annotations

import json
import os
import re
import traceback
from datetime import UTC, datetime
from pathlib import Path
from urllib.parse import urlsplit

from playwright.sync_api import Route, expect, sync_playwright

ROOT = Path(__file__).resolve().parents[1]
ORIGIN = "http://learner.localhost:3100"
VIEWPORTS = ((320, 740), (390, 844), (768, 1024), (1440, 1000))


def local_only(route: Route) -> None:
    parsed = urlsplit(route.request.url)
    if f"{parsed.scheme}://{parsed.netloc}" == ORIGIN:
        route.continue_()
    else:
        route.abort()


def main() -> int:
    output = (
        ROOT
        / ".tmp/local-platform/new/app-updates"
        / datetime.now(UTC).strftime("%Y%m%dT%H%M%S%fZ")
    )
    output.mkdir(parents=True, exist_ok=False)
    proof: dict = {"status": "incomplete", "environment": "local", "views": [], "requests": []}
    stage = "login"
    errors: list[str] = []
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)

        def sign_in():
            context = browser.new_context(viewport={"width": 390, "height": 844})
            context.route("**/*", local_only)
            page = context.new_page()
            page.set_default_timeout(30000)
            page.on("pageerror", lambda _: errors.append("javascript_error"))
            page.goto(ORIGIN + "/login", wait_until="domcontentloaded")
            expect(page.get_by_label("Email address")).to_be_enabled()
            page.get_by_label("Email address").fill("learner@ac.localhost")
            page.get_by_label("Password", exact=True).fill(
                os.environ["AC_LOCAL_BROWSER_TEST_PASSWORD"]
            )
            page.get_by_role("button", name="Sign in", exact=True).click()
            page.wait_for_url(lambda url: url.startswith(ORIGIN) and urlsplit(url).path != "/login")
            assert context.request.get(ORIGIN + "/v1/me").status == 200
            return context, page

        try:
            context, page = sign_in()
            stage = "inbox"

            def record(response) -> None:
                path = urlsplit(response.url).path
                if path.startswith("/v1/me/app-updates"):
                    proof["requests"].append(
                        {
                            "path": path,
                            "status": response.status,
                            "method": response.request.method,
                            "cache_control": response.headers.get("cache-control"),
                        }
                    )

            page.on("response", record)
            page.goto(ORIGIN + "/notifications", wait_until="domcontentloaded")
            heading = page.get_by_role("heading", name="A home for app updates", exact=True)
            expect(heading).to_be_visible()
            initial = context.request.get(ORIGIN + "/v1/me/app-updates")
            assert initial.status == 200
            assert "no-store" in initial.headers["cache-control"]
            before = initial.json()
            proof["unread_before"] = before["unread_count"]
            for theme in ("light", "dark"):
                page.emulate_media(color_scheme=theme, reduced_motion="reduce")
                page.wait_for_timeout(120)
                for width, height in VIEWPORTS:
                    page.set_viewport_size({"width": width, "height": height})
                    page.evaluate("theme => document.documentElement.dataset.theme = theme", theme)
                    page.wait_for_timeout(100)
                    metrics = page.evaluate("""() => ({
                        width: innerWidth, documentWidth: document.documentElement.scrollWidth,
                        theme: document.documentElement.dataset.theme,
                        action: [...document.querySelectorAll('main button')].find(
                            node => /Mark as read|^Read$/.test(node.textContent.trim())
                        )?.getBoundingClientRect().toJSON()
                    })""")
                    assert metrics["theme"] == theme
                    assert metrics["documentWidth"] <= width + 1
                    assert metrics["action"] and metrics["action"]["height"] >= 44
                    filename = f"inbox-{theme}-{width}.png"
                    page.screenshot(path=str(output / filename))
                    proof["views"].append({"file": filename, **metrics})
            page.set_viewport_size({"width": 390, "height": 844})
            stage = "bell"
            bell = page.get_by_role("button", name=re.compile(r"^Notifications(?:,|$)"))
            bell.click()
            expect(
                page.get_by_role("dialog").get_by_role("link", name="View all updates")
            ).to_have_attribute("href", "/notifications")
            page.get_by_role("button", name="Close notifications").click()
            expect(bell).to_be_focused()
            assert (
                context.request.get(ORIGIN + "/v1/me/app-updates").json()["unread_count"]
                == before["unread_count"]
            )
            stage = "read"
            mark = page.get_by_role("button", name="Mark as read", exact=True)
            if mark.count():
                mark.focus()
                page.keyboard.press("Enter")
                read = page.get_by_role("button", name="Read", exact=True)
                expect(read).to_have_attribute("aria-disabled", "true")
                expect(read).to_be_focused()
            after = context.request.get(ORIGIN + "/v1/me/app-updates")
            assert after.status == 200 and after.json()["unread_count"] == 0
            page.get_by_role("button", name="Unread", exact=False).click()
            expect(page.get_by_role("heading", name="You’re up to date")).to_be_visible()
            page.screenshot(path=str(output / "read-confirmed.png"))
            stage = "fresh-session"
            context.close()
            second_context, page = sign_in()
            page.goto(ORIGIN + "/notifications", wait_until="domcontentloaded")
            expect(page.get_by_role("button", name="Read", exact=True)).to_have_attribute(
                "aria-disabled", "true"
            )
            assert (
                second_context.request.get(ORIGIN + "/v1/me/app-updates").json()["unread_count"]
                == 0
            )
            proof["read_persisted_across_new_login"] = True
            proof["page_errors"] = len(errors)
            assert not errors
            assert all(
                row["status"] == 200 and "no-store" in row["cache_control"]
                for row in proof["requests"]
            )
            proof["status"] = "passed"
        except Exception as error:
            proof["status"] = "failed"
            proof["error_type"] = type(error).__name__
            proof["failed_stage"] = stage
            proof["script_line"] = next(
                (
                    frame.lineno
                    for frame in reversed(traceback.extract_tb(error.__traceback__))
                    if Path(frame.filename) == Path(__file__)
                ),
                None,
            )
        finally:
            browser.close()
    (output / "proof.json").write_text(json.dumps(proof, indent=2), encoding="utf-8")
    print(json.dumps({"status": proof["status"], "stage": stage, "evidence": str(output)}))
    return 0 if proof["status"] == "passed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
