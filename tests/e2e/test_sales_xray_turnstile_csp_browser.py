"""Chromium enforces the exact Sales Xray edge CSP, with no external egress.

The local HTTP server emits the policy read from the actual Caddy route. Only
synthetic Turnstile script/frame bodies are substituted; this is a policy proof,
not live challenge solving or server-side token verification.
"""

from __future__ import annotations

import json
import os
import re
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from threading import Thread

import pytest
from playwright.sync_api import Route, expect, sync_playwright

from tests.e2e.test_local_bridge_cookie_isolation import _playwright_subprocess_policy

ROOT = Path(__file__).resolve().parents[2]
CHALLENGE = "https://challenges.cloudflare.com"
SCRIPT = CHALLENGE + "/turnstile/v0/api.js?render=explicit"


def _policy(environment: str, suffix: str = "") -> str:
    source = (ROOT / f"infra/application/edge-routes/{environment}.caddy").read_text()
    block = source.split(f"handle @{environment}_sales_xray{suffix} {{", 1)[1].split("\n\t}", 1)[0]
    policies = re.findall(r'header Content-Security-Policy "([^"\n]+)"', block)
    assert len(policies) == 1
    return policies[0]


@pytest.mark.parametrize("environment", ["staging", "production"])
def test_sales_xray_policy_loads_only_the_approved_challenge_origin(environment: str) -> None:
    policy = _policy(environment)
    html = f"""<!doctype html><meta charset="utf-8"><title>Sales Xray CSP proof</title>
    <h1>Local policy proof</h1><script src="{SCRIPT}"></script>
    <script src="https://unapproved.example.test/payload.js"></script>
    <iframe src="https://unapproved.example.test/frame"></iframe>
    <script>fetch('https://unapproved.example.test/data').catch(()=>{{}});</script>""".encode()

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self) -> None:  # noqa: N802 -- BaseHTTPRequestHandler interface
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Security-Policy", policy)
            self.send_header("Content-Length", str(len(html)))
            self.end_headers()
            self.wfile.write(html)

        def log_message(self, format: str, *args: object) -> None:
            return

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = Thread(target=server.serve_forever, daemon=True)
    thread.start()
    origin = f"http://127.0.0.1:{server.server_port}"
    substituted: list[str] = []
    unexpected: list[str] = []
    try:
        with _playwright_subprocess_policy(), sync_playwright() as playwright:
            browser = playwright.chromium.launch(headless=True)
            try:
                context = browser.new_context()

                def boundary(route: Route) -> None:
                    url = route.request.url
                    if url.startswith(origin + "/"):
                        route.continue_()
                    elif url == SCRIPT:
                        substituted.append("script")
                        route.fulfill(
                            content_type="text/javascript",
                            body=(
                                "document.documentElement.dataset.challengeScript='loaded';"
                                "const frame=document.createElement('iframe');"
                                f"frame.src='{CHALLENGE}/synthetic-frame';"
                                "document.body.appendChild(frame);"
                            ),
                        )
                    elif url == CHALLENGE + "/synthetic-frame":
                        substituted.append("frame")
                        route.fulfill(
                            content_type="text/html",
                            body=(
                                "<!doctype html><script>"
                                "parent.postMessage('synthetic-frame-loaded','*')</script>"
                            ),
                        )
                    else:
                        unexpected.append(url)
                        route.abort()

                context.route("**/*", boundary)
                page = context.new_page()
                page.add_init_script("""window.policyViolations=[];
                    addEventListener('securitypolicyviolation',event=>window.policyViolations.push({
                        directive:event.effectiveDirective,blocked:event.blockedURI}));
                    addEventListener('message',event=>{
                        if(event.origin==='https://challenges.cloudflare.com' &&
                            event.data==='synthetic-frame-loaded')
                            document.documentElement.dataset.challengeFrame='loaded';
                    });""")
                response = page.goto(origin, wait_until="networkidle")
                assert (
                    response is not None and response.headers["content-security-policy"] == policy
                )
                expect(page.locator("html")).to_have_attribute(
                    "data-challenge-script", "loaded", timeout=3000
                )
                expect(page.locator("html")).to_have_attribute(
                    "data-challenge-frame", "loaded", timeout=3000
                )
                violations = page.evaluate("window.policyViolations")
                assert {item["directive"] for item in violations} >= {
                    "script-src-elem",
                    "frame-src",
                    "connect-src",
                }
                assert all(
                    item["blocked"].startswith("https://unapproved.example.test")
                    for item in violations
                )
                assert substituted == ["script", "frame"] and not unexpected
                # API responses keep their separate deny-all policy.
                assert (
                    _policy(environment, "_api") == "default-src 'none'; frame-ancestors 'none'; "
                    "base-uri 'none'; form-action 'none'"
                )
                evidence = os.environ.get("AC_SALES_XRAY_CSP_EVIDENCE_DIR")
                if evidence:
                    destination = Path(evidence)
                    destination.mkdir(parents=True, exist_ok=True)
                    (destination / f"{environment}.json").write_text(
                        json.dumps(
                            {
                                "environment": environment,
                                "csp": policy,
                                "script_loaded": True,
                                "frame_loaded": True,
                                "synthetic_resource_bodies": substituted,
                                "blocked_unapproved_resources": violations,
                                "unexpected_network_requests": unexpected,
                                "external_network_requests": 0,
                                "live_challenge_or_siteverify": False,
                            },
                            indent=2,
                        ),
                        encoding="utf-8",
                    )
                context.close()
            finally:
                browser.close()
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)
