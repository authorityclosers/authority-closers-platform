"""Keep immutable asset caching under the upstream's successful-file policy."""

from __future__ import annotations

import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]


@pytest.mark.parametrize("environment", ("production", "staging"))
def test_static_assets_bypass_site_no_store_without_caching_proxy_errors(
    environment: str,
) -> None:
    routes = (ROOT / f"infra/application/edge-routes/{environment}.caddy").read_text(
        encoding="utf-8"
    )
    site_name = f"{environment}_sales_xray"
    static_name = f"{site_name}_static"
    matcher = re.search(rf"@{static_name} \{{(?P<body>.*?)\n\t\}}", routes, re.DOTALL)
    static = re.search(rf"handle @{static_name} \{{(?P<body>.*?)\n\t\}}", routes, re.DOTALL)
    site = re.search(rf"handle @{site_name} \{{(?P<body>.*?)\n\t\}}", routes, re.DOTALL)
    assert matcher is not None and static is not None and site is not None
    host = "salesxray" + ("-staging" if environment == "staging" else "")
    assert f"host {host}.authorityclosers.com" in matcher["body"]
    assert "path /_next/static/*" in matcher["body"]
    assert static.start() < site.start()
    # Caddy-generated failures must not inherit a successful asset's lifetime.
    assert "cache-control" not in static["body"].lower()
    assert 'header Cache-Control "no-store"' in site["body"]
    assert "import base_security_headers" in static["body"]
    assert f"reverse_proxy ac-{environment}-sales-xray-web:3016" in static["body"]
