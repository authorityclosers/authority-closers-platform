"""The website line (sx.js) keeps the app's short public cache through the edge (30 Oct 2026)."""

from __future__ import annotations

import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]


def _block(routes: str, opener: str) -> re.Match[str]:
    found = re.search(rf"{re.escape(opener)} \{{(?P<body>.*?)\n\t\}}", routes, re.DOTALL)
    assert found is not None, opener
    return found


@pytest.mark.parametrize("environment", ("production", "staging"))
def test_the_website_line_passes_the_app_cache_and_nothing_else_does(environment: str) -> None:
    routes = (ROOT / f"infra/application/edge-routes/{environment}.caddy").read_text(
        encoding="utf-8"
    )
    site_name = f"{environment}_sales_xray"
    script_name = f"{site_name}_script"
    matcher = _block(routes, f"@{script_name}")
    script = _block(routes, f"handle @{script_name}")
    site = _block(routes, f"handle @{site_name}")
    host = "salesxray" + ("-staging" if environment == "staging" else "")
    assert f"host {host}.authorityclosers.com" in matcher["body"]
    # Only the one file: every other path keeps the page's no-store.
    assert [line.strip() for line in matcher["body"].strip().splitlines()] == [
        f"host {host}.authorityclosers.com",
        "path /sx.js",
    ]
    # Caddy picks the first handle that matches, so the line's comes before the page's.
    assert script.start() < site.start()
    # The app sets the lifetime; an edge failure (a 502 during a release) carries none.
    assert "cache-control" not in script["body"].lower()
    assert 'header Cache-Control "no-store"' in site["body"]
    assert "import base_security_headers" in script["body"]
    assert f'header X-Authority-Closers-Route "sales-xray-{environment}"' in script["body"]
    assert f"reverse_proxy ac-{environment}-sales-xray-web:3016" in script["body"]
