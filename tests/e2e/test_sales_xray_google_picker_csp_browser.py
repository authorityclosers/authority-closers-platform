"""Chromium enforces the exact Sales X-Ray edge CSP on Google's file picker, with no external
egress (Sheets and Drive, slice 1, 27 Oct 2026).

The local HTTP server emits the policy read from the actual Caddy route. Synthetic bodies
stand in for Google's loader, its picker module and the picker's two frames; this is a
policy proof, not a live pick. The live picker was opened under this policy on ac
(docs/evidence/google-picker-csp-20261027).
"""

from __future__ import annotations

from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from threading import Thread

import pytest
from playwright.sync_api import Route, expect, sync_playwright

from tests.e2e.test_local_bridge_cookie_isolation import _playwright_subprocess_policy
from tests.e2e.test_sales_xray_turnstile_csp_browser import _policy

LOADER = "https://apis.google.com/js/api.js"
MODULE = "https://apis.google.com/_/scs/abc-static/_/js/k=gapi.picker"
FRAMES = {
    "picker": "https://docs.google.com/picker",
    "proxy": "https://content.googleapis.com/static/proxy.html",
}


@pytest.mark.parametrize("environment", ["staging", "production"])
def test_sales_xray_policy_lets_the_google_picker_load(environment: str) -> None:
    policy = _policy(environment)
    html = f"""<!doctype html><meta charset="utf-8"><title>Google picker CSP proof</title>
    <h1>Local policy proof</h1><script src="{LOADER}"></script>
    <img src="https://docs.google.com/synthetic.png" alt="">
    <script>fetch('https://apis.google.com/synthetic-data').catch(()=>{{}});</script>
    <script src="https://unapproved.example.test/payload.js"></script>
    <iframe src="https://unapproved.example.test/frame"></iframe>""".encode()

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
    frame_script = (
        "for(const [name,src] of Object.entries({frames})){{"
        "const frame=document.createElement('iframe');frame.src=src+'?synthetic='+name;"
        "document.body.appendChild(frame);}}"
    ).format(frames=repr(FRAMES).replace("'", '"'))
    try:
        with _playwright_subprocess_policy(), sync_playwright() as playwright:
            browser = playwright.chromium.launch(headless=True)
            try:
                context = browser.new_context()

                def boundary(route: Route) -> None:
                    url = route.request.url
                    if url.startswith(origin + "/"):
                        route.continue_()
                    elif url == LOADER:
                        substituted.append("loader")
                        route.fulfill(
                            content_type="text/javascript",
                            body=(
                                "const module=document.createElement('script');"
                                f"module.src='{MODULE}';document.head.appendChild(module);"
                            ),
                        )
                    elif url == MODULE:
                        substituted.append("module")
                        route.fulfill(
                            content_type="text/javascript",
                            body="document.documentElement.dataset.pickerModule='loaded';"
                            + frame_script,
                        )
                    elif any(url == f"{src}?synthetic={name}" for name, src in FRAMES.items()):
                        name = url.rsplit("=", 1)[1]
                        substituted.append(name)
                        route.fulfill(
                            content_type="text/html",
                            body=(
                                "<!doctype html><script>"
                                f"parent.postMessage('synthetic-{name}-loaded','*')</script>"
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
                    const origins={picker:'https://docs.google.com',
                        proxy:'https://content.googleapis.com'};
                    addEventListener('message',event=>{
                        for(const [name,frameOrigin] of Object.entries(origins))
                            if(event.origin===frameOrigin &&
                                event.data===`synthetic-${name}-loaded`)
                                document.documentElement.dataset[name+'Frame']='loaded';
                    });""")
                response = page.goto(origin, wait_until="networkidle")
                assert (
                    response is not None and response.headers["content-security-policy"] == policy
                )
                html_element = page.locator("html")
                expect(html_element).to_have_attribute("data-picker-module", "loaded", timeout=3000)
                expect(html_element).to_have_attribute("data-picker-frame", "loaded", timeout=3000)
                expect(html_element).to_have_attribute("data-proxy-frame", "loaded", timeout=3000)
                violations = page.evaluate("window.policyViolations")
                blocked = {(item["directive"], item["blocked"]) for item in violations}
                # The page itself may not fetch from or draw Google: only its script and frames.
                assert ("connect-src", "https://apis.google.com/synthetic-data") in blocked
                assert ("img-src", "https://docs.google.com/synthetic.png") in blocked
                assert {item for item in blocked if "unapproved.example.test" not in item[1]} == {
                    ("connect-src", "https://apis.google.com/synthetic-data"),
                    ("img-src", "https://docs.google.com/synthetic.png"),
                }
                assert {"script-src-elem", "frame-src"} <= {
                    directive for directive, uri in blocked if "unapproved" in uri
                }
                assert sorted(substituted) == ["loader", "module", "picker", "proxy"]
                assert not unexpected
                context.close()
            finally:
                browser.close()
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)
