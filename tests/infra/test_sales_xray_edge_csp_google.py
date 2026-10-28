"""Google's file picker may load on the Sales X-Ray sites, and only there (Sheets and Drive,
slice 1, 27 Oct 2026): its loader script from apis.google.com, its frames from
docs.google.com and content.googleapis.com. Opening it showed the page itself fetches,
styles and draws nothing from Google, so no other directive names Google."""

from __future__ import annotations

import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
ROUTES = ROOT / "infra/application/edge-routes"
GOOGLE = ("https://apis.google.com", "https://docs.google.com", "https://content.googleapis.com")
# Microsoft Clarity (28 Oct 2026), production only: its script, beacons and pixels.
CLARITY = {"staging": [], "production": ["https://*.clarity.ms"]}


def policy(environment: str) -> dict[str, list[str]]:
    source = (ROUTES / f"{environment}.caddy").read_text(encoding="utf-8")
    block = source.split(f"handle @{environment}_sales_xray {{", 1)[1].split("\n\t}", 1)[0]
    (header,) = re.findall(r'header Content-Security-Policy "([^"\n]+)"', block)
    directives: dict[str, list[str]] = {}
    for part in header.split(";"):
        if part.strip():
            name, *sources = part.split()
            directives[name] = sources
    return directives


@pytest.mark.parametrize("environment", ["staging", "production"])
def test_the_picker_may_load_its_script_and_frames(environment: str) -> None:
    csp = policy(environment)
    assert csp["script-src"] == [
        "'self'",
        "'unsafe-inline'",
        "https://challenges.cloudflare.com",
        "https://checkout.razorpay.com",
        "https://apis.google.com",
        *CLARITY[environment],
    ]
    assert csp["frame-src"] == [
        "'self'",
        "https://challenges.cloudflare.com",
        "https://api.razorpay.com",
        "https://checkout.razorpay.com",
        "https://docs.google.com",
        "https://content.googleapis.com",
    ]
    assert csp["connect-src"] == [
        "'self'",
        "https://api.razorpay.com",
        "https://lumberjack.razorpay.com",
        *CLARITY[environment],
    ]
    for name, sources in csp.items():
        if name not in {"script-src", "frame-src"}:
            assert not any("google" in source for source in sources), name
    assert csp["object-src"] == ["'none'"]
    assert csp["frame-ancestors"] == ["'none'"]


@pytest.mark.parametrize("environment", ["staging", "production"])
def test_no_other_route_names_google(environment: str) -> None:
    source = (ROUTES / f"{environment}.caddy").read_text(encoding="utf-8")
    for origin in GOOGLE:
        assert source.count(origin) == 1, origin


@pytest.mark.parametrize("environment", ["staging", "production"])
def test_only_production_sales_xray_lets_clarity_in(environment: str) -> None:
    """Clarity loads only in production (its release profile); its CSP sources match."""
    csp = policy(environment)
    for name in ("script-src", "img-src", "connect-src"):
        assert [s for s in csp[name] if "clarity" in s] == CLARITY[environment], name
    for name, sources in csp.items():
        if name not in {"script-src", "img-src", "connect-src"}:
            assert not any("clarity" in source for source in sources), name
    source = (ROUTES / f"{environment}.caddy").read_text(encoding="utf-8")
    policies = re.findall(r'header Content-Security-Policy "([^"\n]+)"', source)
    assert sum("clarity" in header for header in policies) == (environment == "production")
