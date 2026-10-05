#!/usr/bin/env python3
"""Read AUT-1116's approved fictional report through the existing dev studio.

Uses the Admin QA launcher's loopback TLS transport, with the exact dev HTTPS
origin. Chromium supplies Host/Origin and handles Secure __Host- cookies normally;
no request-header overrides, cookie injection or live proxy changes are involved.
The existing AUT-1116 credential handoff is read only into process memory. All
other accounts/reports, external requests and background writes are refused.
"""

from __future__ import annotations

import importlib.util
import json
import os
import re
import stat
import sys
import tempfile
from datetime import UTC, datetime
from pathlib import Path
from urllib.parse import urlsplit

HOST = "salesxray-dev.authorityclosers.com"
ORIGIN = f"https://{HOST}"
EDGE_PORT = 3016
REPORT_ID = "dadaed4c-2f24-4299-b2fa-c0c47f9b374a"
CREDENTIAL = Path("/home/acdev/.config/ac-qa/staging-account-aut1116.env")
LOGIN = "/v1/auth/password/login"
WORKSPACES = "/v1/me/workspaces"
REPORT_API = f"/v1/conversation/acquisition/submissions/{REPORT_ID}/report"
REPORT_PAGE = f"/analysis/calls/{REPORT_ID}?view=reading&section=overview"
OTHER_REPORT = re.compile(r"/(?:submissions|calls)/([^/]+)(?:/|$)")
ACCOUNT_READS = {
    WORKSPACES,
    "/v1/me/sales-xray-workspaces",
    "/v1/me/sales-xray-profile",
    "/v1/me/sales-xray-profile/write-eligibility",
    "/v1/auth/email-code/config",
    "/v1/conversation/acquisition/session",
    "/v1/conversation/acquisition/submissions",
}
REPORT_READ = re.compile(
    rf"/v1/conversation/acquisition/submissions/{REPORT_ID}"
    r"(?:/(?:report|transcript|speaker-map|call-record|report-notes))?"
)
LOGIN_JS = """async c => {
  const r = await fetch('/v1/auth/password/login', {
    method: 'POST', credentials: 'same-origin', redirect: 'error',
    headers: {'content-type': 'application/json'}, body: JSON.stringify(c)
  });
  let j = {}; try { j = await r.json(); } catch {}
  return {status: r.status, code: j.code ?? null};
}"""
WORKSPACES_JS = """async () => {
  const r = await fetch('/v1/me/workspaces', {credentials: 'same-origin', cache: 'no-store'});
  let j = {}; try { j = await r.json(); } catch {}
  return {status: r.status, personPresent: !!j.person_id,
    workspaceCount: Array.isArray(j.workspaces) ? j.workspaces.length : null};
}"""


class Refused(RuntimeError):
    """Value-free failure code; never forward browser/credential exceptions."""


def require(ok: bool, code: str) -> None:
    if not ok:
        raise Refused(code)


def read_credential(path: Path = CREDENTIAL) -> dict[str, str]:
    parent = path.parent.lstat()
    require(
        stat.S_ISDIR(parent.st_mode)
        and parent.st_uid == os.getuid()
        and stat.S_IMODE(parent.st_mode) == 0o700,
        "credential_directory_refused",
    )
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    with os.fdopen(fd, "r", encoding="utf-8") as handle:
        info = os.fstat(handle.fileno())
        require(
            stat.S_ISREG(info.st_mode)
            and info.st_uid == os.getuid()
            and stat.S_IMODE(info.st_mode) == 0o600
            and info.st_size <= 8192,
            "credential_file_refused",
        )
        fields: dict[str, str] = {}
        for line in handle.read(8193).splitlines():
            if line.startswith("#") or "=" not in line:
                continue
            name, value = line.split("=", 1)
            for field in ("email", "password"):
                if field in name.lower():
                    require(field not in fields, "credential_format_refused")
                    fields[field] = value.strip().strip("\"'")
        require(
            set(fields) == {"email", "password"} and all(fields.values()),
            "credential_format_refused",
        )
        return fields


def allowed_request(url: str, method: str) -> bool:
    parsed = urlsplit(url)
    # Turbopack encodes brackets and @ in its chunk filenames. Those static
    # assets must hydrate the real password form; encoded API paths stay denied.
    static_asset = parsed.path.startswith("/_next/static/") and not re.search(
        r"%(?!5[bBdD]|40)", parsed.path
    )
    if (
        parsed.scheme != "https"
        or parsed.netloc != HOST
        or parsed.username
        or parsed.password
        or ("%" in parsed.path and not static_asset)
        or "\\" in parsed.path
        or ".." in parsed.path.split("/")
    ):
        return False
    report = OTHER_REPORT.search(parsed.path)
    if report and report[1] != REPORT_ID:
        return False
    if method == "POST":
        return parsed.path == LOGIN and not parsed.query
    if parsed.path.startswith("/v1/"):
        return method == "GET" and (
            parsed.path in ACCOUNT_READS or REPORT_READ.fullmatch(parsed.path) is not None
        )
    return method in {"GET", "HEAD"}


def load_transport():
    path = Path(__file__).with_name("qa-admin-browser.py")
    spec = importlib.util.spec_from_file_location("qa_admin_transport", path)
    require(spec is not None and spec.loader is not None, "transport_source_unavailable")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def browser_args(port: int, pin: str) -> list[str]:
    return [
        "--no-proxy-server",
        "--disable-quic",
        "--renderer-process-limit=2",
        f"--host-resolver-rules=MAP {HOST} 127.0.0.1:{port}",
        f"--ignore-certificate-errors-spki-list={pin}",
    ]


def browser_environment() -> dict[str, str]:
    # This host supplies Chromium's shared libraries outside /usr/lib.
    return {k: os.environ[k] for k in ("PATH", "HOME", "LD_LIBRARY_PATH") if k in os.environ}


def require_private_logging() -> None:
    # Playwright API debug logs can print the text passed to fill(). Refuse
    # before starting its driver or reading a credential, rather than redact.
    require(not any(os.environ.get(k) for k in ("DEBUG", "PWDEBUG")), "browser_debug_refused")


def verify_report(page, receipt: dict) -> None:
    for width, height in ((1440, 900), (390, 844)):
        page.set_viewport_size({"width": width, "height": height})
        with page.expect_response(
            lambda response: urlsplit(response.url).path == REPORT_API, timeout=45000
        ) as read:
            navigation = page.goto(
                ORIGIN + REPORT_PAGE, wait_until="domcontentloaded", timeout=45000
            )
        response = read.value
        require(response.status == 200, "report_read_failed")
        data = response.json()
        require(data.get("submission_id") == REPORT_ID, "report_binding_failed")
        page.locator('[data-report-mode-section="overview"]').wait_for(timeout=45000)
        row = {
            "width": width,
            "height": height,
            "routeStatus": navigation.status,
            "reportStatus": response.status,
            "submissionMatches": True,
            "readyReportVisible": True,
            "horizontalOverflow": page.evaluate(
                "document.documentElement.scrollWidth > innerWidth + 1"
            ),
        }
        receipt["viewports"].append(row)
        del data


def run(receipt: dict) -> None:
    require_private_logging()
    from playwright.sync_api import sync_playwright

    require(os.geteuid() != 0, "run_as_non_root")
    transport = load_transport()
    # Only public process settings reach Chromium; no injected agent/API secrets.
    browser_env = browser_environment()
    with tempfile.TemporaryDirectory(
        prefix="aut1232-", dir=os.environ.get("PAPERCLIP_RUN_SCRATCH_DIR")
    ) as directory:
        cert, key, pin = transport.ephemeral_certificate(Path(directory), host=HOST)
        bridge = transport.Bridge(cert, key, edge_port=EDGE_PORT)
        bridge.start()
        try:
            with sync_playwright() as playwright:
                receipt["stage"] = "browser_start"
                browser = playwright.chromium.launch(
                    headless=True, args=browser_args(bridge.port, pin), env=browser_env
                )
                try:
                    context = browser.new_context(service_workers="block", reduced_motion="reduce")
                    page = context.new_page()
                    logins = 0

                    def route_request(route):
                        nonlocal logins
                        request = route.request
                        if not allowed_request(request.url, request.method):
                            receipt["blockedRequests"] += 1
                            route.abort()
                            return
                        if request.method == "POST":
                            logins += 1
                            if logins > 2:
                                route.abort()
                                return
                            receipt["loginOriginMatches"] = request.headers.get("origin") == ORIGIN
                            require(receipt["loginOriginMatches"], "login_origin_mismatch")
                        route.continue_()

                    context.route("**/*", route_request)
                    receipt["stage"] = "dev_login_page"
                    page.goto(ORIGIN + "/login", wait_until="domcontentloaded", timeout=45000)
                    receipt["stage"] = "fictional_sentinel"
                    sentinel = page.evaluate(
                        LOGIN_JS,
                        {
                            "email": "fictional-no-such-aut1232@example.test",
                            "password": "Fictional-sentinel-denied1!",  # noqa: S106 - fictional
                        },
                    )
                    receipt["sentinel"] = sentinel
                    require(
                        sentinel == {"status": 401, "code": "password_credentials_rejected"},
                        "sentinel_not_rejected",
                    )
                    require(not context.cookies(), "sentinel_created_cookie")
                    receipt["stage"] = "normal_password_form"
                    page.get_by_role("button", name="Use my existing password").first.click()
                    credential = read_credential()
                    try:
                        page.locator("#account-password-email").fill(credential["email"])
                        page.locator("#account-password").fill(credential["password"])
                        with page.expect_response(
                            lambda response: urlsplit(response.url).path == LOGIN, timeout=30000
                        ) as login:
                            page.get_by_role("button", name="Sign in", exact=True).click()
                        receipt["login"] = {"status": login.value.status}
                    finally:
                        credential.clear()
                    require(receipt["login"]["status"] == 200, "normal_login_failed")
                    page.wait_for_url(ORIGIN + "/dashboard", timeout=30000)
                    cookies = context.cookies()
                    session = [c for c in cookies if c["name"] == "__Host-ac_session"]
                    receipt["secureCookieValid"] = len(session) == 1 and all(
                        c["secure"] and c["httpOnly"] and c["path"] == "/" and c["domain"] == HOST
                        for c in session
                    )
                    del session, cookies
                    require(receipt["secureCookieValid"], "secure_cookie_failed")
                    receipt["stage"] = "canonical_workspace"
                    receipt["workspace"] = page.evaluate(WORKSPACES_JS)
                    require(
                        receipt["workspace"]["status"] == 200
                        and receipt["workspace"]["personPresent"],
                        "workspace_read_failed",
                    )
                    receipt["stage"] = "approved_report"
                    verify_report(page, receipt)
                    context.close()
                finally:
                    browser.close()
        finally:
            bridge.stop()


def main() -> int:
    receipt = {
        "task": "AUT-1232",
        "at": datetime.now(UTC).isoformat(),
        "origin": ORIGIN,
        "edge": f"127.0.0.1:{EDGE_PORT}",
        "reportId": REPORT_ID,
        "credentialSource": "AUT-1116 existing protected handoff",
        "blockedRequests": 0,
        "viewports": [],
        "result": "FAIL",
    }
    try:
        require(len(sys.argv) == 1, "arguments_not_supported")
        run(receipt)
        receipt["result"] = "PASS"
    except Refused as error:
        receipt["failure"] = str(error)
    except Exception as error:
        receipt["failure"] = "bounded_verification_failed"
        receipt["failureType"] = type(error).__name__
    print(json.dumps(receipt, indent=2))
    return 0 if receipt["result"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
