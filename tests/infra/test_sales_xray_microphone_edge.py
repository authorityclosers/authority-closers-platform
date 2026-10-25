"""#11: voice notes need the microphone on the Sales X-Ray page (owner, 26 Oct 2026)."""

from __future__ import annotations

import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
SNIPPET = (ROOT / "infra/vps-foundation/compose/foundation/Caddyfile").read_text(encoding="utf-8")


def _headers(body: str) -> dict[str, str]:
    block = re.search(r"\n\t\theader \{\n(?P<lines>.*?)\n\t\t\}", body, re.DOTALL)
    assert block is not None, "the page handle carries its own header block"
    pairs = (line.strip().split(" ", 1) for line in block["lines"].splitlines())
    return {name: value.strip('"') for name, *rest in pairs for value in (rest or [""])}


@pytest.mark.parametrize("environment", ("production", "staging"))
def test_the_page_may_use_the_microphone_itself_and_keeps_every_other_header(
    environment: str,
) -> None:
    routes = (ROOT / f"infra/application/edge-routes/{environment}.caddy").read_text(
        encoding="utf-8"
    )
    site = re.search(
        rf"handle @{environment}_sales_xray \{{(?P<body>.*?)\n\t\}}", routes, re.DOTALL
    )
    assert site is not None
    # The snippet would send microphone=() and, being deferred, win over any later line.
    assert "import base_security_headers" not in site["body"]
    headers = _headers(site["body"])
    assert headers["Permissions-Policy"] == (
        "camera=(), microphone=(self), geolocation=(), payment=(), usb=()"
    )
    assert "-Server" in headers
    snippet = SNIPPET.split("(base_security_headers) {", 1)[1].split("\n}\n", 1)[0]
    for name in (
        "Strict-Transport-Security",
        "X-Content-Type-Options",
        "X-Frame-Options",
        "Referrer-Policy",
    ):
        assert f'{name} "{headers[name]}"' in snippet
    # Only the page: the API, static files and the release hold keep the snippet.
    for other in (f"{environment}_sales_xray_api", f"{environment}_sales_xray_static"):
        handle = re.search(rf"handle @{other} \{{(?P<body>.*?)\n\t\}}", routes, re.DOTALL)
        assert handle is not None and "import base_security_headers" in handle["body"]
