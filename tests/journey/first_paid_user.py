"""T1a: offline fixture validation or one read-only dev pre-sale check, never a full verdict."""

from __future__ import annotations

import argparse
import json
import os
import re
import time
from contextlib import suppress
from pathlib import Path
from urllib.parse import urlsplit
from uuid import UUID

ORIGIN = "https://salesxray-dev.authorityclosers.com"
SOURCE_PIN = "1e784afa128f8d4629aeece5179486d423c0ec52"
MANIFEST = Path(__file__).with_name("fixture_manifest.json")
QA_DIR = Path.home() / ".config/ac-qa"
SHA = re.compile(r"[0-9a-f]{40}")
ROLES = {"personal", "organisation_owner", "organisation_member", "enterprise"}
NOT_ON_SALE = "Not on sale yet"
OFFLINE_COPY = "After you pay, we add your minutes."
BUY = re.compile(r"\b(buy|subscribe|purchase|checkout)\b", re.I)
DETAILS = re.compile(r"\b(UPI|IFSC|bank transfer|account number|bank name)\b", re.I)
PRICE = re.compile(r"₹\s*\d|\b(?:INR|Rs\.?)\s*\d", re.I)


class InvalidConfig(ValueError):
    """Messages and caller input are deliberately never emitted."""


def require(condition: bool) -> None:
    if not condition:
        raise InvalidConfig


def check(condition: bool) -> None:
    if not condition:
        raise AssertionError


class SafeParser(argparse.ArgumentParser):
    def error(self, message: str) -> None:
        raise InvalidConfig


def validate_manifest(manifest: dict) -> str:
    # Strict metadata shape also prevents adding credentials to the manifest.
    require(set(manifest) == {"version", "environment", "accounts", "media"})
    require(manifest["version"] == 1 and manifest["environment"] == "dev")
    accounts = manifest["accounts"]
    require(len(accounts) == 4 and {a["role"] for a in accounts} == ROLES)
    identities = []
    for account in accounts:
        require(set(account) == {"role", "email"})
        email = account["email"]
        require(re.fullmatch(r"admin\+qa-dev-[a-z]+@authorityclosers\.com", email) is not None)
        identities.append(email.casefold())  # Keep the complete plus tag.
    require(len(set(identities)) == len(identities))
    media = manifest["media"]
    require(set(media) == {"synthetic", "provenance", "file", "sha256"})
    require(
        media["synthetic"] is True and re.fullmatch(r"[0-9a-f]{64}", media["sha256"]) is not None
    )
    require(
        all(
            media[key].startswith("/home/acdev/src/test-assets/sales-xray-calls/")
            for key in ("file", "provenance")
        )
    )
    return next(a["email"] for a in accounts if a["role"] == "personal")


def load_session(release_id: str, email: str) -> dict:
    path = Path(os.environ.get("AC_QA_SESSION_FILE", str(QA_DIR / "dev-personal.json"))).resolve()
    require(path.is_relative_to(QA_DIR.resolve()) and path.is_file())
    session = json.loads(path.read_text())
    require(
        set(session)
        == {
            "environment",
            "origin",
            "release_id",
            "email",
            "person_id",
            "offline_enabled",
            "purchase_enabled",
            "storage_state",
        }
    )
    require(session["environment"] == "dev" and session["origin"] == ORIGIN)
    require(session["release_id"] == release_id and session["email"].casefold() == email.casefold())
    UUID(session["person_id"])
    require(type(session["offline_enabled"]) is bool and session["purchase_enabled"] is False)
    state = session["storage_state"]
    require(set(state) == {"cookies", "origins"} and state["origins"] == [])
    cookies = state["cookies"]
    require(bool(cookies))
    for cookie in cookies:
        require(cookie["domain"] == urlsplit(ORIGIN).hostname and bool(cookie["value"]))
        require(
            cookie["secure"] is True
            and (cookie["expires"] == -1 or cookie["expires"] > time.time())
        )
    require(
        any(
            c["name"] == "__Host-ac_session" and c["httpOnly"] is True and c["path"] == "/"
            for c in cookies
        )
    )
    return session


def allowed_request(method: str, url: str) -> bool:
    target = urlsplit(url)
    if method != "GET" or f"{target.scheme}://{target.netloc}" != ORIGIN:
        return False
    if (
        target.username
        or target.password
        or target.fragment
        or "%" in target.path
        or ".." in target.path
    ):
        return False
    return target.path in {
        "/plans",
        "/plans/",
        "/v1/me/workspaces",
        "/v1/plans",
        "/v1/billing/offline-payment",
    } or target.path.startswith("/_next/static/")


def validate_presale_catalogue(response) -> None:
    """Observed C1 §5 evidence must prove this limited check is supported."""
    problem_keys = {"type", "title", "status", "detail", "code"}
    if response.status == 501:
        return
    if response.status == 404:
        require(
            response.headers.get("content-type", "").split(";")[0].strip().lower()
            != "application/problem+json"
        )
        try:
            body = response.json()
        except ValueError:
            return  # A missing route may serve HTML or an empty body.
        require(not isinstance(body, dict) or not problem_keys.intersection(body))
        return
    body = response.json()
    if response.status == 409:
        require(isinstance(body, dict) and set(body) == problem_keys)
        require(type(body["status"]) is int and body["status"] == 409)
        require(all(isinstance(body[key], str) for key in problem_keys - {"status"}))
        require(body["code"] == "not_on_sale")
        return
    require(response.status == 200)
    # Check the C1 sale fields without inventing unrelated catalogue metadata.
    if isinstance(body, dict):
        require(set(body) == {"items"})
        body = body["items"]
    require(isinstance(body, list) and bool(body))
    for plan in body:
        require(isinstance(plan, dict) and {"status", "prices"}.issubset(plan))
        require(plan["status"] in ("coming_soon", "active"))
        prices = plan["prices"]
        if prices is not None:
            require(plan["status"] == "active" and isinstance(prices, dict))
            require(
                set(prices) == {"monthly_paise", "yearly_paise", "monthly_cents", "yearly_cents"}
            )
            require(
                all(
                    value is None or (type(value) is int and value >= 0)
                    for value in prices.values()
                )
            )
            raise InvalidConfig  # Buyable even if the UI and QA purchase pin are stale.


def check_presale(page, offline_enabled: bool) -> None:
    for role in ("button", "link"):
        actions = page.get_by_role(role, name=BUY)
        for index in range(actions.count()):
            action = actions.nth(index)
            if action.is_visible():
                require(not action.is_enabled())  # Paid checks are unsupported, exit 2.
                raise AssertionError  # Even a disabled visible buy violates pre-sale.
    unavailable = page.get_by_text(NOT_ON_SALE, exact=True)
    check(any(unavailable.nth(i).is_visible() for i in range(unavailable.count())))
    content = page.get_by_role("main")
    check(content.count() == 1)
    text = content.inner_text()
    check(not PRICE.search(text))
    copy = page.get_by_text(OFFLINE_COPY, exact=True)
    visible = any(copy.nth(i).is_visible() for i in range(copy.count()))
    check(visible == offline_enabled)
    check(bool(DETAILS.search(text)) == offline_enabled)


def browse(session: dict) -> None:
    # Import only after every local target/session/release check has passed.
    from playwright.sync_api import sync_playwright

    refused = []
    identity_confirmed = []
    catalogue_confirmed = []
    offline_enabled = [False]

    def refuse_socket(socket) -> None:
        refused.append(True)
        socket.close()

    def inspect_request(route) -> None:
        request = route.request
        if not allowed_request(request.method, request.url):
            refused.append(True)
            route.abort()
            return
        path = urlsplit(request.url).path
        if path in {"/plans", "/plans/"} and not identity_confirmed:
            # Verify the supplied fictional person before fetching any chooser data.
            identity = route.fetch(url=ORIGIN + "/v1/me/workspaces", max_redirects=0)
            if identity.status != 200 or identity.json().get("person_id") != session["person_id"]:
                refused.append(True)
                route.abort()
                return
            identity_confirmed.append(True)
        if path.startswith("/v1/") and path != "/v1/me/workspaces" and not identity_confirmed:
            refused.append(True)
            route.abort()
            return
        response = route.fetch(max_redirects=0)
        if 300 <= response.status < 400:
            refused.append(True)
            route.abort()
            return
        if path == "/v1/me/workspaces":
            if response.status != 200 or response.json().get("person_id") != session["person_id"]:
                refused.append(True)
                route.abort()
                return
            identity_confirmed.append(True)
        if path == "/v1/plans":
            validate_presale_catalogue(response)
            catalogue_confirmed.append(True)
        if path == "/v1/billing/offline-payment" and response.status == 200:
            enabled = response.json().get("enabled")
            check(type(enabled) is bool)
            offline_enabled[0] = enabled
        route.fulfill(response=response)

    def route_request(route) -> None:
        try:
            inspect_request(route)
        except Exception:
            # Playwright callback errors must not escape into its event-loop logs.
            refused.append(True)
            with suppress(Exception):
                route.abort()

    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        try:
            context = browser.new_context(
                storage_state=session["storage_state"], service_workers="block"
            )
            context.route("**/*", route_request)
            context.route_web_socket("**/*", refuse_socket)
            page = context.new_page()
            response = page.goto(ORIGIN + "/plans", wait_until="networkidle", timeout=15000)
            require(not refused and bool(identity_confirmed) and bool(catalogue_confirmed))
            check(response is not None and response.status == 200)
            check(offline_enabled[0] == session["offline_enabled"])
            check_presale(page, offline_enabled[0])
            require(not refused)
        finally:
            browser.close()


def main(argv: list[str] | None = None) -> int:
    result = {
        "environment": "offline",
        "release_id": None,
        "source_pin": SOURCE_PIN,
        "covered_steps": [],
        "status": "invalid",
        "failing_step": "configuration",
    }
    code = 2
    try:
        parser = SafeParser(description=__doc__, allow_abbrev=False)
        parser.add_argument("--environment")
        parser.add_argument("--release-id")
        parser.add_argument("--origin", default=ORIGIN)
        parser.add_argument("--mode", default="pre-sale")
        parser.add_argument("--execute", action="store_true")
        args = parser.parse_args(argv)
        require(args.origin == ORIGIN and args.mode == "pre-sale")
        require(args.environment in (None, "dev"))
        if args.release_id is not None or args.execute:
            require(
                isinstance(args.release_id, str)
                and SHA.fullmatch(args.release_id) is not None
                and args.release_id != "0" * 40
            )
        require(not args.execute or args.environment == "dev")
        result.update(environment=args.environment or "offline", release_id=args.release_id)
        result["failing_step"] = "fixture_manifest"
        email = validate_manifest(json.loads(MANIFEST.read_text()))
        result["covered_steps"].append("fixture_manifest")
        if args.execute:
            result["failing_step"] = "qa_session"
            require(not os.environ.get("DEBUG") and not os.environ.get("PWDEBUG"))
            session = load_session(args.release_id, email)
            result["failing_step"] = "plans_pre_sale"
            browse(session)
            result["covered_steps"].append("plans_pre_sale")
        result.update(status="passed", failing_step=None)
        code = 0
    except AssertionError:
        result["status"] = "failed"
        code = 1
    except Exception:
        # No exception strings, input values, DOM, screenshots, trace, session or credentials.
        result["status"] = "invalid"
    print(json.dumps(result))
    return code


if __name__ == "__main__":
    raise SystemExit(main())
